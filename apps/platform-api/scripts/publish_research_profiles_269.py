"""Approve the accepted audit and archive reproducible profiles. Default rolls back."""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from smartlib_platform.knowledge.research_profiles import BATCHES, load_profiles
from smartlib_platform.storage.s3 import S3ObjectStore

ACTOR = UUID('00000000-0000-4000-8000-000000000001')
NS = UUID('19a157be-f6ed-47c7-8737-a5ce1333d191')
BATCH = 'paper-research-profiles-269-20260909-v1'
def uid(value): return uuid5(NS, value)

def run(root, output, apply):
    audit = json.loads((root/'audit_results.json').read_text())
    deferred = next(p['publication_id'] for p in audit['papers'] if p['n']==195)
    reason = '用户确认后入库形成画像；确认已实施AI审核结果，非逐篇专家人工标引；C195国自然方向暂缓。'
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'], row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=not apply):
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(BATCH,))
            for key,value in [('actor_id',str(ACTOR)),('trace_id',BATCH),('change_source','user-authorized-profile-publication'),('change_reason',reason)]:
                conn.execute('SELECT set_config(%s,%s,true)',('smartlib.'+key,value))
            already=conn.execute('SELECT metadata FROM smartlib.source_system WHERE source_system_id=%s',(uid('system'),)).fetchone()
            if already:
                return {'applied':False,'idempotent_replay':True,**already['metadata']}
            checksum="SELECT md5(string_agg(md5(to_jsonb(k)::text),'' ORDER BY object_id)) value FROM smartlib.knowledge_object k"
            before=conn.execute(checksum).fetchone()['value']
            rows=conn.execute("SELECT relation_id,subject_id,attributes,review_state FROM smartlib.relation_assertion WHERE attributes->>'source_import_batch'=ANY(%s) AND system_to='infinity' FOR UPDATE",(BATCHES,)).fetchall()
            assert len(rows)==3043, len(rows)
            active=[r for r in rows if r['review_state']=='pending']
            assert len(active)==3010, len(active)
            selected=[r for r in active if not(str(r['subject_id'])==deferred and r['attributes']['scheme']=='NSFC_APPLICATION_CODE')]
            assert len(selected)==3009
            excluded={str(r['relation_id']):r for r in rows if r not in selected}
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
            for r in selected:
                attrs={**r['attributes'],'reviewed_by':str(ACTOR),'reviewed_at':timestamp,
                       'review_note':r['attributes'].get('review_note','')+'；'+reason}
                version=conn.execute("UPDATE smartlib.relation_assertion SET review_state='approved',attributes=%s WHERE relation_id=%s RETURNING version",(Jsonb(attrs),r['relation_id'])).fetchone()['version']
                conn.execute("""INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
                    VALUES(%s,'relation_assertion',%s,'knowledge.relation.updated',%s,%s,%s)""",
                    (uid('outbox:'+str(r['relation_id'])),r['relation_id'],version,Jsonb({'relation_id':str(r['relation_id']),'version':version}),BATCH))
            profiles=load_profiles(conn)
            counts=collections.Counter(p['object_type'] for p in profiles.values())
            assert counts['publication']==269 and counts['project']==58, counts
            assert profiles[deferred]['coverage']['NSFC_APPLICATION_CODE']==0
            coverage={s:sum(p['coverage'][s] for p in profiles.values() if p['object_type']=='publication') for s in ['NSFC_APPLICATION_CODE','MESH','INCITES_WOS']}
            assert coverage['NSFC_APPLICATION_CODE']==268
            for p in profiles.values():
                ids={x['publication_id'] for x in p['papers']}
                assert len(ids)==p['total_papers']
                for row in p['rows']:
                    assert set(row['publication_ids'])<=ids and row['paper_count']==len(set(row['publication_ids']))
            for rid,r in excluded.items():
                now=conn.execute('SELECT review_state,attributes FROM smartlib.relation_assertion WHERE relation_id=%s',(UUID(rid),)).fetchone()
                assert now['review_state']==r['review_state'] and now['attributes']==r['attributes']
            assert conn.execute(checksum).fetchone()['value']==before
            # Immutable snapshot contains classification and membership relation IDs; source evidence retains their history.
            document={'batch':BATCH,'created_at':timestamp,'scope':'269篇已导入论文，不代表全校全部成果','deferred':['C195 NSFC'],
                      'confirmation':reason,'approved_relation_ids':[str(r['relation_id']) for r in selected],'profiles':profiles}
            payload=json.dumps(document,ensure_ascii=False,sort_keys=True).encode()
            digest=hashlib.sha256(payload).hexdigest()
            key=f'research-profiles/{BATCH}/{digest}/profiles.json'
            archive={'uri':'s3://smartlib-reference-data/'+key,'sha256':digest}
            if apply:
                store=S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'],'smartlib-reference-data',os.environ['SMARTLIB_S3_ACCESS_KEY'],os.environ['SMARTLIB_S3_SECRET_KEY'],os.environ.get('SMARTLIB_S3_REGION','us-east-1'))
                saved=store.put_bytes(key,payload,'application/json')
                assert hashlib.sha256(store.get_bytes(key)).hexdigest()==digest
                archive['version_id']=saved.version_id
            receipt={'batch':BATCH,'approved':len(selected),'pending':1,'profile_counts':dict(counts),'coverage':coverage,'archive':archive,'knowledge_objects_checksum':before,'reviewed_at':timestamp}
            conn.execute("""INSERT INTO smartlib.source_system(source_system_id,code,name,owner_department,source_type,authorization_state,metadata)
                VALUES(%s,%s,'269篇论文确认分类与成果画像','科研数据治理','repository','approved',%s)""",(uid('system'),BATCH,Jsonb(receipt)))
            for oid,p in profiles.items():
                ref,eid=uid('ref:'+oid),uid('evidence:'+oid)
                conn.execute("""INSERT INTO smartlib.source_reference(source_reference_id,object_id,source_system_id,external_id,source_version,payload_checksum,raw_object_uri,metadata)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",(ref,UUID(oid),uid('system'),oid,BATCH,digest,archive['uri'],Jsonb({'json_pointer':'/profiles/'+oid,**archive})))
                conn.execute("""INSERT INTO smartlib.evidence_record(evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by)
                    VALUES(%s,%s,%s,'business_record',%s,%s,'campus',ARRAY['internal-reference-use'],%s,%s,%s)""",
                    (eid,UUID(oid),ref,archive['uri'],reason,digest,Jsonb({'record_kind':'derived_research_profile','profile':p,'archive':archive}),ACTOR))
            output.mkdir(parents=True,exist_ok=True)
            (output/'profiles.json').write_bytes(payload)
            return {'applied':apply,**receipt}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();result=run(args.root,args.output,args.apply)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/('apply_receipt.json' if args.apply else 'dryrun_receipt.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))
