"""Controlled append-only standard import. Default run rolls the DB transaction back."""
from __future__ import annotations
import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from smartlib_platform.storage.s3 import S3ObjectStore

ACTOR='00000000-0000-4000-8000-000000000001'
BUCKET='smartlib-reference-data'
TRACE='research-standard-import-20260909-v1'

def archive(package, root):
    store=S3ObjectStore(os.environ['SMARTLIB_S3_ENDPOINT_URL'],BUCKET,
                        os.environ['SMARTLIB_S3_ACCESS_KEY'],os.environ['SMARTLIB_S3_SECRET_KEY'],
                        os.environ.get('SMARTLIB_S3_REGION','us-east-1'))
    empty=hashlib.sha256(b'').hexdigest()
    response=store._request('HEAD','/'+BUCKET,empty)
    if response.status_code==404:
        response=store._request('PUT','/'+BUCKET,empty)
    if response.status_code not in (200,204):raise ValueError(f'Bucket unavailable: {response.status_code}')
    body=b'<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Enabled</Status></VersioningConfiguration>'
    response=store._request('PUT','/'+BUCKET,hashlib.sha256(body).hexdigest(),content=iter([body]),query='versioning=')
    if response.status_code not in (200,204):raise ValueError('Cannot enable source versioning')
    receipts=[]
    for source in package['sources']:
        data=(root/source['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=source['sha256']:raise ValueError('Raw source checksum mismatch')
        key=f"research-standards/{source['sha256']}/{Path(source['path']).name}"
        stored=store.put_bytes(key,data,mimetypes.guess_type(source['path'])[0] or 'application/octet-stream')
        if hashlib.sha256(store.get_bytes(key)).hexdigest()!=source['sha256']:raise ValueError('MinIO readback mismatch')
        receipts.append({'path':source['path'],'uri':stored.storage_uri,'version_id':stored.version_id,
                         'sha256':source['sha256'],'reused':not stored.created})
    return receipts

def import_package(package, apply):
    sources={r['path']:r for r in package['sources']}
    for row in package['objects']:
        source=sources[row['source_path']]
        row['uri']=f"s3://{BUCKET}/research-standards/{source['sha256']}/{Path(source['path']).name}"
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as conn:
        def execute(query, params=()):
            # Inline staging uses ordinary SELECT/INSERT permissions, no TEMP or admin role.
            ctes=[]; values=[]
            for table,key in [('standard_objects','objects'),('standard_relations','relations')]:
                if table in query:
                    ctes.append(f'{table} AS MATERIALIZED (SELECT value AS j FROM jsonb_array_elements(%s::jsonb))')
                    values.append(Jsonb(package[key]))
            if ctes:query='WITH '+','.join(ctes)+' '+query
            return conn.execute(query,(*values,*params))
        with conn.transaction(force_rollback=not apply):
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            # Container /dev/shm is small. Scope serial execution to this import only.
            conn.execute('SET LOCAL max_parallel_workers_per_gather=0')
            for key,value in [('actor_id',ACTOR),('trace_id',TRACE),('change_source','controlled-standard-import'),
                              ('change_reason','导入经结构核验的NSFC、MeSH与InCites分类标准；不修改业务对象')]:
                conn.execute("SELECT set_config(%s,%s,true)",('smartlib.'+key,value))
            # Detect any accidental content mutation to pre-existing business objects.
            baseline_sql="""SELECT md5(string_agg(md5(to_jsonb(k)::text),'' ORDER BY object_id)) AS checksum
                              FROM smartlib.knowledge_object k WHERE object_type NOT IN ('concept','discipline')"""
            before=conn.execute(baseline_sql).fetchone()['checksum']
            for row in {r['source_code']:r for r in package['objects']}.values():
                conn.execute("""INSERT INTO smartlib.source_system
                 (source_system_id,code,name,owner_department,source_type,authorization_state,metadata)
                 VALUES (%s,%s,%s,%s,'repository','approved',%s) ON CONFLICT DO NOTHING""",
                 (UUID(row['source_id']),row['source_code'],row['source_name'],row['source_name'],
                  Jsonb({'dataset_id':package['dataset_id'],'batch':package['batch']})))
            inserted=execute("""INSERT INTO smartlib.knowledge_object
             (object_id,object_type,canonical_name,description,visibility,quality_state,review_state,attributes,created_by)
             SELECT (j->>'id')::uuid,j->>'type',j->>'name',j->'attributes'->>'scheme','campus',j->>'quality',
                    'approved',j->'attributes',%s FROM standard_objects
             ON CONFLICT (object_id) DO NOTHING""",(UUID(ACTOR),)).rowcount
            mismatch=execute("""SELECT count(*) AS n FROM standard_objects s
             JOIN smartlib.knowledge_object k ON k.object_id=(s.j->>'id')::uuid
             WHERE k.canonical_name IS DISTINCT FROM s.j->>'name'
                OR k.attributes IS DISTINCT FROM s.j->'attributes'
                OR k.object_type IS DISTINCT FROM s.j->>'type'
                OR k.system_to<>'infinity' OR k.review_state<>'approved'""").fetchone()['n']
            if mismatch:raise ValueError('Existing standard object differs; explicit revision required')
            execute("""INSERT INTO smartlib.source_reference
             (source_reference_id,object_id,source_system_id,external_id,source_version,payload_checksum,raw_object_uri,metadata)
             SELECT (j->>'reference_id')::uuid,(j->>'id')::uuid,(j->>'source_id')::uuid,
                    j->'attributes'->>'scheme_code',j->'attributes'->>'scheme_version',j->>'checksum',j->>'uri',
                    jsonb_build_object('source_url',j->'attributes'->>'source_url',
                                       'source_file_sha256',j->'attributes'->>'source_checksum',
                                       'source_locator',j->'attributes'->'source_locator')
             FROM standard_objects ON CONFLICT (source_reference_id) DO NOTHING""")
            execute("""INSERT INTO smartlib.evidence_record
             (evidence_id,object_id,source_reference_id,evidence_type,citation,excerpt,visibility,license_tags,content_checksum,metadata,created_by)
             SELECT (j->>'evidence_id')::uuid,(j->>'id')::uuid,(j->>'reference_id')::uuid,'business_record',
                    concat(j->>'source_name',': ',j->'attributes'->>'scheme_version'),j->>'name','campus',
                    ARRAY['source-attributed','internal-reference-use'],j->>'checksum',
                    jsonb_build_object('standard_record',j->'evidence','raw_object_uri',j->>'uri','trace_id',%s::text),%s
             FROM standard_objects ON CONFLICT (evidence_id) DO NOTHING""",(TRACE,UUID(ACTOR)))
            relations=execute("""INSERT INTO smartlib.relation_assertion
             (relation_id,subject_id,predicate,object_id,fact_class,confidence,visibility,license_tags,review_state,attributes,created_by)
             SELECT (j->>'id')::uuid,(j->>'subject')::uuid,j->>'predicate',(j->>'object')::uuid,
                    'business_fact',1,'campus',ARRAY['source-attributed','internal-reference-use'],'approved',j->'attributes',%s
             FROM standard_relations ON CONFLICT (relation_id) DO NOTHING""",(UUID(ACTOR),)).rowcount
            mismatch=execute("""SELECT count(*) AS n FROM standard_relations s
              JOIN smartlib.relation_assertion r ON r.relation_id=(s.j->>'id')::uuid
              WHERE r.subject_id<>(s.j->>'subject')::uuid OR r.object_id<>(s.j->>'object')::uuid
                 OR r.predicate<>s.j->>'predicate' OR r.attributes<>s.j->'attributes'
                 OR r.system_to<>'infinity' OR r.review_state<>'approved'""").fetchone()['n']
            if mismatch:raise ValueError('Existing standard relation differs')
            execute("""INSERT INTO smartlib.relation_evidence(relation_id,evidence_id)
             SELECT (j->>'id')::uuid,(j->>'evidence_id')::uuid FROM standard_relations ON CONFLICT DO NOTHING""")
            # Existing graph/search projectors consume the same governed outbox contract.
            for table,kind,idkey in [('standard_objects','knowledge_object','object_id'),('standard_relations','relation_assertion','relation_id')]:
                execute(f"""INSERT INTO smartlib.outbox_event
                 (event_id,aggregate_type,aggregate_id,event_type,event_version,payload,trace_id)
                 SELECT md5('standard-import-event:'||(j->>'id'))::uuid,%s,(j->>'id')::uuid,%s,1,
                        jsonb_build_object(%s::text,j->>'id','version',1),%s FROM {table}
                 ON CONFLICT (event_id) DO NOTHING""",(kind,'knowledge.object.imported' if kind=='knowledge_object' else 'knowledge.relation.imported',idkey,TRACE))
            after=conn.execute(baseline_sql).fetchone()['checksum']
            if before!=after:raise ValueError('Business objects changed unexpectedly')
            result={'applied':apply,'inserted_objects':inserted,'inserted_relations':relations,
                    'expected_objects':len(package['objects']),'expected_relations':len(package['relations']),
                    'business_objects_unchanged':before==after,'business_checksum':after,'trace_id':TRACE}
        return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--receipt-dir',type=Path,default=Path('/tmp/research_standard_receipts'))
    parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    args.receipt_dir.mkdir(parents=True,exist_ok=True)
    package=json.loads((args.root/'package.json').read_text())
    if args.apply:
        receipts=archive(package,args.root)
        (args.receipt_dir/'minio_receipt.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2))
    result=import_package(package,args.apply)
    (args.receipt_dir/('commit_receipt.json' if args.apply else 'dryrun_receipt.json')).write_text(json.dumps(result,indent=2))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
