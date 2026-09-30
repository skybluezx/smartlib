"""Apply a reviewed-input classification package; dry run rolls back by default."""
import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ACTOR='00000000-0000-4000-8000-000000000001'
PREDICATE='publication.classified_as_discipline'
def run(path,apply):
    raw=path.read_bytes(); package=json.loads(raw); batch=package['batch']
    uid=lambda key:uuid5(NAMESPACE_URL,batch+':'+key)
    counts=Counter(); desired={}
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as c:
      with c.transaction(force_rollback=not apply):
        for k,v in {'actor_id':ACTOR,'trace_id':batch,'change_source':batch,'change_reason':'用户授权补齐WoS及教育部学科关系；推断待核验参与分析'}.items():
            c.execute('SELECT set_config(%s,%s,true)',('smartlib.'+k,v))
        c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(batch,))
        source=uid('source')
        c.execute("INSERT INTO smartlib.source_system(source_system_id,code,name,owner_department,source_type,authorization_state,metadata) VALUES(%s,%s,'WoS最新元数据与教育部内容分类补全','科研数据治理','repository','approved',%s) ON CONFLICT DO NOTHING",(source,batch,Jsonb({'package_sha256':hashlib.sha256(raw).hexdigest(),'inference_review_state':'pending'})))
        for r in package['rows']:
            pid=UUID(r['publication_id']);target=UUID(r['target_id'])
            d=c.execute("SELECT attributes FROM smartlib.knowledge_object WHERE object_id=%s AND system_to='infinity'",(target,)).fetchone()
            assert d and (d['attributes']['scheme'],d['attributes']['scheme_code'])==(r['scheme'],r['code'])
            if r['source_kind']=='external_indexing':
                inc=c.execute('SELECT attributes->\'incites\' AS inc FROM smartlib.publication_metadata WHERE publication_id=%s',(pid,)).fetchone()['inc']
                assert inc['source_reference_id']==r['source_reference_id'] and r['code'] in {x.strip().upper() for x in inc['raw_fields']['研究方向'].split(';')}
                ref=UUID(r['source_reference_id']);desired.setdefault(str(pid),set()).add(str(target))
            else:
                f=c.execute('SELECT publication_id::text,content_checksum FROM smartlib.publication_fulltext_resource WHERE fulltext_resource_id=%s',(UUID(r['fulltext_resource_id']),)).fetchone()
                assert f and f['publication_id']==str(pid) and f['content_checksum']==r['source_checksum']
                ref=uid('ref:'+str(pid))
                c.execute("INSERT INTO smartlib.source_reference(source_reference_id,object_id,source_system_id,external_id,source_version,payload_checksum,raw_object_uri,metadata) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",(ref,pid,source,str(pid),batch,r['source_checksum'],r['source_uri'],Jsonb({'fulltext_resource_id':r['fulltext_resource_id'],'scope':'全文文本读取；题名摘要规则生成候选，正文片段支撑；非专家全文语义核验'})))
            attrs={'scheme':r['scheme'],'scheme_version':r['scheme_version'],'code':r['code'],'classification_role':r['role'],'source_kind':r['source_kind'],'rationale':r['rationale'],'evidence_excerpt':r['excerpt'],'source_import_batch':batch,'method_version':batch,'external_source_record':{'checksum':r['source_checksum'],'source_reference_id':str(ref)},'review_note':'用户授权建立关系；不等同人工逐篇确认'}
            if r['scheme']=='MOE_GRADUATE_DISCIPLINE': attrs['discipline_level']=2
            if 'signals' in r:attrs.update(fulltext_resource_id=r['fulltext_resource_id'],fulltext_checksum=r['source_checksum'],score_interpretation='启发式排序分值，不是概率');attrs['external_source_record'].update(signals=r['signals'],heuristic_score=r['heuristic_score'])
            eid=uid('evidence:'+str(pid)+':'+r['scheme']+':'+r['code'])
            c.execute("INSERT INTO smartlib.evidence_record(evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by) VALUES(%s,%s,%s,'business_record',%s,%s,'campus',ARRAY['internal-reference-use'],%s,%s,%s) ON CONFLICT DO NOTHING",(eid,pid,ref,r['source_uri'],r['excerpt'],r['source_checksum'],Jsonb(attrs),ACTOR))
            existing=c.execute("SELECT relation_id,attributes FROM smartlib.relation_assertion WHERE subject_id=%s AND object_id=%s AND predicate=%s AND system_to='infinity' AND smartlib.analysis_state_eligible(review_state)",(pid,target,PREDICATE)).fetchall()
            assert len(existing)<=1,('duplicate active classification',pid,target)
            rid=existing[0]['relation_id'] if existing else uid('relation:'+str(pid)+':'+r['scheme']+':'+r['code'])
            if not existing:
                c.execute("INSERT INTO smartlib.relation_assertion(relation_id,subject_id,predicate,object_id,fact_class,confidence,visibility,license_tags,review_state,model_version,attributes,created_by) VALUES(%s,%s,%s,%s,%s,NULL,'campus',ARRAY['internal-reference-use'],'pending',%s,%s,%s)",(rid,pid,PREDICATE,target,'business_fact' if r['source_kind']=='external_indexing' else 'algorithmic_inference',batch,Jsonb(attrs),ACTOR));counts['inserted_'+r['scheme']]+=1
            elif existing[0]['attributes']!=attrs:
                c.execute('UPDATE smartlib.relation_assertion SET attributes=%s WHERE relation_id=%s',(Jsonb(attrs),rid));counts['updated']+=1
            c.execute('INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',(rid,eid))
            version=c.execute('SELECT version FROM smartlib.relation_assertion WHERE relation_id=%s',(rid,)).fetchone()['version']
            c.execute("INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id) VALUES(%s,'relation_assertion',%s,'knowledge.relation.updated',%s,%s,%s) ON CONFLICT DO NOTHING",(uid('outbox:'+str(rid)+':'+str(version)),rid,version,Jsonb({'relation_id':str(rid),'version':version}),batch))
        for pid,targets in desired.items():
            old=c.execute("SELECT relation_id FROM smartlib.relation_assertion WHERE subject_id=%s AND predicate=%s AND attributes->>'scheme'='INCITES_WOS' AND system_to='infinity' AND smartlib.analysis_state_eligible(review_state) AND NOT(object_id=ANY(%s::uuid[]))",(UUID(pid),PREDICATE,list(targets))).fetchall()
            for row in old:
                rid=row['relation_id'];v=c.execute("UPDATE smartlib.relation_assertion SET review_state='superseded' WHERE relation_id=%s RETURNING version",(rid,)).fetchone()['version'];counts['superseded']+=1
                c.execute("INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id) VALUES(%s,'relation_assertion',%s,'knowledge.relation.updated',%s,%s,%s) ON CONFLICT DO NOTHING",(uid('outbox:'+str(rid)+':'+str(v)),rid,v,Jsonb({'relation_id':str(rid),'version':v}),batch))
        for item in package.get('withdrawals',[]):
            removed=c.execute("UPDATE smartlib.relation_assertion SET review_state='superseded' WHERE subject_id=%s AND object_id=%s AND attributes->>'source_import_batch'=%s AND review_state='pending' RETURNING relation_id,version",(UUID(item['publication_id']),UUID(item['target_id']),batch)).fetchall()
            for row in removed:
                rid=row['relation_id'];v=row['version'];counts['withdrawn_after_content_check']+=1
                c.execute("INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id) VALUES(%s,'relation_assertion',%s,'knowledge.relation.updated',%s,%s,%s) ON CONFLICT DO NOTHING",(uid('outbox:'+str(rid)+':'+str(v)),rid,v,Jsonb({'relation_id':str(rid),'version':v}),batch))
        for r in package['rows']:
            assert c.execute("SELECT 1 FROM smartlib.analysis_relation WHERE subject_id=%s AND object_id=%s AND predicate=%s",(UUID(r['publication_id']),UUID(r['target_id']),PREDICATE)).fetchone()
        result={'applied':apply,'changes':dict(counts),'expected_relations':len(package['rows']),'unclassified_moe':len(package['gaps'])}
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('package',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args();run(a.package,a.apply)
