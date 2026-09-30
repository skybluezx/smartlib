"""Append-only pending classifications. Default is transaction rollback."""
import argparse,hashlib,json,os
from pathlib import Path
from uuid import UUID,uuid5
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from smartlib_platform.storage.s3 import S3ObjectStore

NS=UUID('e9e7581e-c652-4a1b-bd8a-8a087b549bd9');ACTOR=UUID('00000000-0000-4000-8000-000000000001')
def uid(x):return uuid5(NS,x)
def run(root,apply):
 package=json.loads((root/'assignments.json').read_text());rows=package['rows'];batch=package['batch']
 inputs=json.loads((root/'inputs.json').read_text());assert len(inputs)==269
 archive={}
 paths=['inputs.json','assignments.json','nsfc_decisions.json','mesh_semantic_overrides.json']+[s['path'] for s in package['sources']]
 store=None
 if apply:
  store=S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'],'smartlib-reference-data',os.environ['SMARTLIB_S3_ACCESS_KEY'],os.environ['SMARTLIB_S3_SECRET_KEY'],os.environ.get('SMARTLIB_S3_REGION','us-east-1'))
 for path in paths:
  payload=(root/path).read_bytes();sha=hashlib.sha256(payload).hexdigest();key=f'paper-classifications/{batch}/{sha}/{Path(path).name}'
  entry={'uri':f's3://smartlib-reference-data/{key}','sha256':sha}
  if store:
   saved=store.put_bytes(key,payload,'application/xml' if path.endswith('.xml') else 'application/json')
   assert hashlib.sha256(store.get_bytes(key)).hexdigest()==sha
   entry['version_id']=saved.version_id
  archive[path]=entry
 with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as conn:
  with conn.transaction(force_rollback=not apply):
   for k,v in [('actor_id',str(ACTOR)),('trace_id',batch),('change_source','paper-classification-import'),('change_reason','269篇论文分类：仅新增待审核关系与证据，不修改论文内容和其他对象')]:
    conn.execute('SELECT set_config(%s,%s,true)',('smartlib.'+k,v))
   checksum="SELECT md5(string_agg(md5(to_jsonb(k)::text),'' ORDER BY object_id)) value FROM smartlib.knowledge_object k"
   before=conn.execute(checksum).fetchone()['value']
   for p in inputs:
    source=conn.execute("SELECT publication_id::text,content_checksum FROM smartlib.publication_fulltext_resource WHERE fulltext_resource_id=%s",(UUID(p['fulltext_resource_id']),)).fetchone()
    assert source and source['publication_id']==p['publication_id'] and source['content_checksum']==p['content_checksum']
   standards={str(x['object_id']):x for x in conn.execute("SELECT object_id,object_type,attributes FROM smartlib.knowledge_object WHERE attributes->>'standard_library'='research-classification' AND system_to='infinity'")}
   source_system=uid('source-system:'+batch)
   conn.execute("""INSERT INTO smartlib.source_system(source_system_id,code,name,owner_department,source_type,authorization_state,metadata)
   VALUES(%s,%s,'论文内容分类与外部标引核验','科研数据治理','repository','approved',%s) ON CONFLICT DO NOTHING""",
   (source_system,'paper_classification_269_20260909',Jsonb({'batch':batch,'sources_separated':True})))
   inserted=0
   for r in rows:
    a=r['attributes'];s=standards[r['target_id']]['attributes']
    assert (a['scheme'],a['scheme_version'],a['code'])==(s['scheme'],s['scheme_version'],s['scheme_code'])
    assert r['review_state']=='pending'
    source_path=r.get('archive_source_path','inputs.json');raw=archive[source_path]
    evidence_meta={'assignment':a,'pdf_uri':r['source_uri'],'pdf_sha256':r['source_checksum'],
       'pdf_opening_text':r['supporting_text'] if a['source_kind']=='algorithmic_inference' else '',
       'source_scope':'PDF开篇最多3页及匹配的外部记录；非全篇逐段精读',
       'classification_package_uri':archive['assignments.json']['uri'],
       'source_file_version':raw.get('version_id'),'batch':batch}
    ref=UUID(r['source_reference_id']);eid=UUID(r['evidence_id']);rid=UUID(r['id'])
    conn.execute("""INSERT INTO smartlib.source_reference(source_reference_id,object_id,source_system_id,external_id,source_version,payload_checksum,raw_object_uri,metadata)
    VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
    (ref,UUID(r['publication_id']),source_system,r['id'],batch,raw['sha256'],raw['uri'],Jsonb({'source_kind':a['source_kind'],'method':a['method_version'],'pdf_uri':r['source_uri']})))
    conn.execute("""INSERT INTO smartlib.evidence_record(evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by)
    VALUES(%s,%s,%s,'business_record',%s,%s,'campus',ARRAY['internal-reference-use'],%s,%s,%s) ON CONFLICT DO NOTHING""",
    (eid,UUID(r['publication_id']),ref,a.get('external_record_url',r['source_uri']),a['evidence_excerpt'],raw['sha256'],Jsonb(evidence_meta),ACTOR))
    fact='algorithmic_inference' if a['source_kind']=='algorithmic_inference' else 'business_fact'
    existing=conn.execute('SELECT subject_id::text,object_id::text,predicate,attributes FROM smartlib.relation_assertion WHERE relation_id=%s',(rid,)).fetchone()
    if existing:
     assert existing=={'subject_id':r['publication_id'],'object_id':r['target_id'],'predicate':r['predicate'],'attributes':a},'Existing assignment differs; use a new version'
    else:
     conn.execute("""INSERT INTO smartlib.relation_assertion(relation_id,subject_id,predicate,object_id,fact_class,confidence,visibility,license_tags,review_state,model_version,attributes,created_by)
     VALUES(%s,%s,%s,%s,%s,%s,'campus',ARRAY['internal-reference-use'],'pending',%s,%s,%s)""",
     (rid,UUID(r['publication_id']),r['predicate'],UUID(r['target_id']),fact,0.7 if fact=='algorithmic_inference' else 1,a['method_version'],Jsonb(a),ACTOR));inserted+=1
    conn.execute('INSERT INTO smartlib.relation_evidence(relation_id,evidence_id) VALUES(%s,%s) ON CONFLICT DO NOTHING',(rid,eid))
    conn.execute("""INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
    VALUES(%s,'relation_assertion',%s,'knowledge.relation.imported',1,%s,%s) ON CONFLICT DO NOTHING""",
    (uid('outbox:'+r['id']),rid,Jsonb({'relation_id':r['id'],'version':1}),batch))
   actual=conn.execute("SELECT count(*) n,count(DISTINCT subject_id) papers FROM smartlib.relation_assertion WHERE attributes->>'source_import_batch'=%s",(batch,)).fetchone()
   assert actual['n']==len(rows) and actual['papers']==269
   after=conn.execute(checksum).fetchone()['value'];assert before==after
   result={'applied':apply,'inserted_relations':inserted,'total_relations':actual['n'],'papers':actual['papers'],
     'existing_objects_unchanged':True,'object_checksum':after,'review_state':'pending','batch':batch}
 receipts=Path('/tmp/paper_classification_269_receipts');receipts.mkdir(exist_ok=True)
 (receipts/('commit_receipt.json' if apply else 'dryrun_receipt.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
 if apply:(receipts/'archive_receipt.json').write_text(json.dumps(archive,ensure_ascii=False,indent=2))
 print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args();run(a.root,a.apply)
