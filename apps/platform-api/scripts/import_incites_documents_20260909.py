"""Source-preserving InCites enrichment; dry-run by default, immutable archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from smartlib_platform.storage.s3 import S3ObjectStore

ACTOR='00000000-0000-4000-8000-000000000001'
TRACE='incites-documents-20260909-v1'
def uid(s): return uuid5(NAMESPACE_URL, TRACE+':'+s)
def digest(x): return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()

def run(root, apply):
    p=json.loads((root/'import_package.json').read_text())
    data=(root/p['file']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==p['sha256']
    s=S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'],'smartlib-incites-data',os.environ['SMARTLIB_S3_ACCESS_KEY'],os.environ['SMARTLIB_S3_SECRET_KEY'],os.environ.get('SMARTLIB_S3_REGION','us-east-1'))
    key=f"incites/2026-09-09/{p['sha256']}/{p['file']}"
    stored=s.put_bytes(key,data,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    assert hashlib.sha256(s.get_bytes(key)).hexdigest()==p['sha256']
    result={'applied':apply,'archive_uri':stored.storage_uri,'sha256':p['sha256'],'archive_verified':True,'rows':len(p['records']),'updated':0,'new_identifiers':{},'year_differences':[]}
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as c:
      with c.transaction(force_rollback=not apply):
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        c.execute('SET LOCAL max_parallel_workers_per_gather=0')
        for k,v in [('actor_id',ACTOR),('trace_id',TRACE),('change_source','incites-document-enrichment'),('change_reason','用户授权导入新版InCites论文指标，保留人工治理字段及资助证据')]: c.execute('SELECT set_config(%s,%s,true)',('smartlib.'+k,v))
        sid=c.execute("SELECT source_system_id FROM smartlib.source_system WHERE code='incites_excel'").fetchone()['source_system_id']
        protected="""SELECT md5(coalesce(string_agg(md5(j::text),'' ORDER BY j::text),'')) AS h FROM (
          SELECT to_jsonb(r) AS j FROM smartlib.relation_assertion r UNION ALL
          SELECT to_jsonb(a) FROM smartlib.publication_authorship a UNION ALL
          SELECT to_jsonb(m)-'attributes'-'metadata_version'-'updated_at' FROM smartlib.publication_metadata m UNION ALL
          SELECT jsonb_build_object('id',publication_id,'attributes',attributes-'incites') FROM smartlib.publication_metadata
          UNION ALL SELECT to_jsonb(k) FROM smartlib.knowledge_object k) t"""
        before=c.execute(protected).fetchone()['h']
        pubs=c.execute("SELECT m.*,i.normalized_value AS doi FROM smartlib.publication_metadata m JOIN smartlib.publication_identifier i ON i.publication_id=m.publication_id WHERE i.identifier_type='doi' AND i.verification_status<>'rejected' FOR UPDATE OF m").fetchall()
        bydoi={x['doi'].lower():x for x in pubs}
        assert len(bydoi)==269
        old={x['doi'].lower() for x in pubs if 'incites' in x['attributes']}
        incoming={r['fields']['DOI'].lower() for r in p['records']}
        assert len(incoming)==261 and incoming<=bydoi.keys()
        result.update(previous_coverage=len(old),added_coverage=len(incoming-old),missing=[{'doi':d,'title':bydoi[d]['title']} for d in sorted(bydoi.keys()-incoming)])
        batch=uid(p['sha256']+':batch')
        c.execute("""INSERT INTO smartlib.ingestion_batch(batch_id,source_system_id,dataset_version,source_uri,source_checksum,expected_item_count,batch_state,processing_rule_version,metadata,created_by,source_kind,pipeline_key,source_locator)
          VALUES(%s,%s,%s,%s,%s,261,'imported',%s,%s,%s,'file','incites_publication_enrichment',%s) ON CONFLICT(batch_id) DO NOTHING""",(batch,sid,TRACE+':'+p['sha256'],stored.storage_uri,p['sha256'],TRACE,Jsonb({'summary':p['summary'],'not_supplied':['funding','affiliations','ESI_flags','journal_quartiles']}),ACTOR,Jsonb({'uri':stored.storage_uri,'sha256':p['sha256']})))
        for r in p['records']:
          f=r['fields']; pub=bydoi[f['DOI'].lower()]; pid=pub['publication_id']; rowkey=f"{p['sha256']}:Web of Science Documents:{r['row']}"; ref=uid(rowkey+':reference'); rec=uid(rowkey+':record'); checksum=digest(f)
          loc={'row':r['row'],'sheet':'Web of Science Documents','file':p['file'],'file_sha256':p['sha256'],'record_id':str(rec)}
          for typ,raw,norm in [('wos',f['入藏号'],f['入藏号']),('pmid',f['Pubmed ID'],str(f['Pubmed ID'] or '').removeprefix('MEDLINE:'))]:
            if not raw: continue
            matches=c.execute("SELECT publication_id,normalized_value FROM smartlib.publication_identifier WHERE identifier_type=%s AND verification_status<>'rejected' AND (publication_id=%s OR lower(normalized_value)=lower(%s))",(typ,pid,norm)).fetchall()
            if matches and any(x['publication_id']!=pid or x['normalized_value'].lower()!=norm.lower() for x in matches): raise ValueError(f'Identifier conflict {f["DOI"]} {typ}')
          c.execute("""INSERT INTO smartlib.source_reference(source_reference_id,object_id,source_system_id,external_id,source_version,payload_checksum,raw_object_uri,metadata) VALUES(%s,%s,%s,%s,'InCites_269_DOI; exported 2026-09-09',%s,%s,%s) ON CONFLICT(source_reference_id) DO NOTHING""",(ref,pid,sid,rowkey,checksum,stored.storage_uri,Jsonb(loc)))
          c.execute("""INSERT INTO smartlib.ingestion_record(record_id,batch_id,raw_payload,normalized_payload,payload_checksum,created_by,source_locator,source_record_key,record_kind,processing_state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'incites_publication_metrics','processed') ON CONFLICT(record_id) DO NOTHING""",(rec,batch,Jsonb(f),Jsonb({'publication_id':str(pid),'doi':f['DOI'].lower()}),checksum,ACTOR,Jsonb(loc),rowkey))
          c.execute("INSERT INTO smartlib.ingestion_record_object(record_id,object_id,output_role) VALUES(%s,%s,'enriched_publication') ON CONFLICT DO NOTHING",(rec,pid))
          c.execute("""INSERT INTO smartlib.evidence_record(evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by) VALUES(%s,%s,%s,'dataset',%s,%s,'restricted',ARRAY['licensed-user-provided','internal-reference-use'],%s,%s,%s) ON CONFLICT(evidence_id) DO NOTHING""",(uid(rowkey+':evidence'),pid,ref,f"{p['file']} / Web of Science Documents / row {r['row']}",f['论文标题'],checksum,Jsonb({'raw_fields':f,'source_locator':loc,'trace_id':TRACE}),ACTOR))
          for typ,raw,norm in [('wos',f['入藏号'],f['入藏号']),('pmid',f['Pubmed ID'],str(f['Pubmed ID'] or '').removeprefix('MEDLINE:'))]:
            if not raw:continue
            n=c.execute("""INSERT INTO smartlib.publication_identifier(publication_identifier_id,publication_id,identifier_type,raw_value,normalized_value,is_primary,verification_status,source_reference_id,created_by) SELECT %s,%s,%s,%s,%s,true,'matched',%s,%s WHERE NOT EXISTS(SELECT 1 FROM smartlib.publication_identifier WHERE publication_id=%s AND identifier_type=%s AND verification_status<>'rejected')""",(uid(str(pid)+':'+typ+':'+norm),pid,typ,raw,norm,ref,ACTOR,pid,typ)).rowcount
            result['new_identifiers'][typ]=result['new_identifiers'].get(typ,0)+n
          snapshot={'dataset':'InCites_269_DOI + ESCI','export_date':'2026-09-09','index_cutoff':'2026-07-31','dataset_updated':'2026-09-02','raw_fields':f,'source_reference_id':str(ref),'raw_object_uri':stored.storage_uri,'file_sha256':p['sha256'],'source_locator':loc}
          if f['出版年']!=pub['publication_year']:result['year_differences'].append({'doi':f['DOI'],'local':pub['publication_year'],'incites':f['出版年'],'action':'retain local; preserve source value separately'})
          if pub['attributes'].get('incites')!=snapshot:
            c.execute("UPDATE smartlib.publication_metadata SET attributes=jsonb_set(attributes,'{incites}',%s),metadata_version=metadata_version+1 WHERE publication_id=%s",(Jsonb(snapshot),pid));result['updated']+=1
            c.execute("""INSERT INTO smartlib.outbox_event(event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id) SELECT %s,'knowledge_object',object_id,'knowledge.object.updated',1,jsonb_build_object('object_id',object_id,'version',version),%s FROM smartlib.knowledge_object WHERE object_id=%s ON CONFLICT(event_id) DO NOTHING""",(uid(rowkey+':event'),TRACE,pid))
        c.execute("UPDATE smartlib.ingestion_batch SET batch_state='completed' WHERE batch_id=%s AND batch_state<>'completed'",(batch,))
        assert c.execute(protected).fetchone()['h']==before,'Governed fields or relationships changed'
        result['coverage_after']=c.execute("SELECT count(*) AS n FROM smartlib.publication_metadata WHERE attributes ? 'incites'").fetchone()['n']
        result['registered_records']=c.execute('SELECT count(*) AS n FROM smartlib.ingestion_record WHERE batch_id=%s',(batch,)).fetchone()['n']
        assert result['coverage_after']==261 and result['registered_records']==261
        result['protected_data_unchanged']=True
    return result

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--apply',action='store_true');args=a.parse_args()
    result=run(args.root,args.apply)
    (args.root/('receipt_applied.json' if args.apply else 'receipt_dryrun.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    print(json.dumps(result,ensure_ascii=False,default=str))
