"""Convert an already archived InCites document export into immutable metric facts."""
import argparse
import json
import os
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ACTOR = '00000000-0000-4000-8000-000000000001'
RULE = 'incites-metrics-v1'


def import_metrics(sha: str, apply: bool) -> dict:
    release_id = uuid5(NAMESPACE_URL, RULE + sha)
    with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'], row_factory=dict_row) as c:
      with c.transaction(force_rollback=not apply):
        c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        c.execute("SELECT set_config('smartlib.actor_id',%s,true),set_config('smartlib.change_source',%s,true),set_config('smartlib.change_reason',%s,true)", (ACTOR,RULE,'将已归档InCites快照结构化，不改变论文及关系'))
        existing = c.execute('SELECT release_state FROM smartlib.publication_metric_release WHERE release_id=%s', (release_id,)).fetchone()
        if existing:
            assert existing['release_state']=='validated'
            return {'release_id':str(release_id),'reused':True,'inserted_values':0}
        rows = c.execute("""SELECT ir.record_id,ir.batch_id,ir.raw_payload,sr.source_reference_id,sr.object_id,
            sr.raw_object_uri,sr.source_system_id,m.publication_year, m.attributes->'incites' AS incites,
            (ir.source_locator->>'row')::integer AS source_row
            FROM smartlib.ingestion_record ir JOIN smartlib.source_reference sr ON sr.metadata->>'record_id'=ir.record_id::text
            JOIN smartlib.publication_metadata m ON m.publication_id=sr.object_id
            WHERE ir.record_kind='incites_publication_metrics' AND ir.source_locator->>'file_sha256'=%s
            ORDER BY (ir.source_locator->>'row')::integer""", (sha,)).fetchall()
        assert rows and len({r['object_id'] for r in rows})==len(rows)
        assert len({r['batch_id'] for r in rows})==1
        batch=c.execute('SELECT * FROM smartlib.ingestion_batch WHERE batch_id=%s',(rows[0]['batch_id'],)).fetchone()
        assert batch['batch_state']=='completed' and batch['expected_item_count']==len(rows) and batch['source_checksum']==sha
        definitions=c.execute('SELECT * FROM smartlib.publication_metric_definition ORDER BY metric_code').fetchall()
        assert len(definitions)==9
        first=rows[0]; inc=first['incites']
        assert all(r['incites']['file_sha256']==sha and r['incites']['raw_fields']==r['raw_payload'] for r in rows)
        c.execute("""INSERT INTO smartlib.publication_metric_release
            (release_id,source_system_id,ingestion_batch_id,provider,scope_key,dataset_label,exported_on,dataset_updated_on,indexed_through,source_uri,source_sha256,rule_version,expected_publication_count,expected_metric_codes,context,created_by)
            VALUES(%s,%s,%s,'incites','smartlib_269_all_subjects',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (release_id,first['source_system_id'],first['batch_id'],inc['dataset'],inc['export_date'],inc['dataset_updated'],inc['index_cutoff'],first['raw_object_uri'],sha,RULE,len(rows),[d['metric_code'] for d in definitions],
             Jsonb({'export_summary':batch['metadata']['summary'],'classification_scheme':'Web of Science','include_esci':True,'include_early_access':True,'source_verification':'user_export_identity_and_values_checked','not_supplied':['ESI_highly_cited','hot_paper','top_1_percent_flag','top_10_percent_flag','JCR_quartile','citations_without_self'],'jif_year_policy':'source_publication_year_context_not_verified_JCR_release','citation_as_of_policy':'source_dataset_snapshot; exact citation refresh timestamp not supplied'}),ACTOR))
        for row in rows:
            fields=row['raw_payload']; snap=uuid5(release_id,str(row['object_id']))
            c.execute("""INSERT INTO smartlib.publication_metric_snapshot
                (snapshot_id,release_id,publication_id,source_reference_id,ingestion_record_id,source_row,source_publication_year,local_publication_year_at_import,source_document_type,source_research_areas,source_collaboration_type,raw_fields)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(snap,release_id,row['object_id'],row['source_reference_id'],row['record_id'],row['source_row'],fields['出版年'],row['publication_year'],fields['文献类型'],fields['研究方向'],fields['合作类型'],Jsonb(fields)))
            for d in definitions:
                name=d['source_field']; raw=fields.get(name)
                status='not_supplied' if name not in fields else 'source_blank' if raw is None or raw=='' else 'present'
                c.execute("INSERT INTO smartlib.publication_metric_value(snapshot_id,metric_code,numeric_value,value_status,raw_value) VALUES(%s,%s,%s,%s,%s)",
                          (snap,d['metric_code'],str(raw) if status=='present' else None,status,Jsonb(raw) if name in fields else None))
        c.execute("UPDATE smartlib.publication_metric_release SET release_state='validated',validated_at=clock_timestamp() WHERE release_id=%s",(release_id,))
        coverage=c.execute("SELECT metric_code,count(*) AS rows,count(numeric_value) AS populated,count(*) FILTER(WHERE numeric_value=0) AS zeros FROM smartlib.publication_metric_analysis WHERE release_id=%s GROUP BY metric_code ORDER BY metric_code",(release_id,)).fetchall()
        assert len(coverage)==9 and all(r['rows']==len(rows) for r in coverage)
        return {'applied':apply,'release_id':str(release_id),'publications':len(rows),'inserted_values':9*len(rows),'coverage':coverage}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--sha256',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    print(json.dumps(import_metrics(args.sha256,args.apply),ensure_ascii=False,default=str))
