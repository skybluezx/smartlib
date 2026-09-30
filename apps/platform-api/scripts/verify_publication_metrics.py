"""Read-back and rollback-only negative tests for the InCites metric release."""
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from smartlib_platform.publications.metrics import metric_summary, publication_metrics

RID=UUID('1104e186-e81e-5424-929e-7e1dfb82597a')
with psycopg.connect(os.environ['SMARTLIB_DATABASE_URL'],row_factory=dict_row) as c:
  with c.transaction(force_rollback=True):
    c.execute("SELECT set_config('smartlib.actor_id','00000000-0000-4000-8000-000000000001',true)")
    summary=metric_summary(c,RID,None)
    assert summary['scope_papers']==269
    bycode={r['metric_code']:r for r in summary['metrics']}
    assert len(bycode)==9
    assert bycode['incites.times_cited']['sum_value']==5935
    assert bycode['incites.times_cited']['zero_papers']==15
    assert bycode['incites.jif_context']['value_papers']==247
    assert bycode['incites.jif_context']['source_blank_papers']==14
    assert bycode['incites.jif_context']['mean_value'] is None
    assert all(m['uncovered_papers']==8 for m in bycode.values())
    present=c.execute('SELECT publication_id,snapshot_id FROM smartlib.publication_metric_snapshot WHERE release_id=%s LIMIT 1',(RID,)).fetchone()
    one=metric_summary(c,RID,[present['publication_id'],present['publication_id']])
    assert one['scope_papers']==1
    assert len(publication_metrics(c,present['publication_id'],RID))==9
    assert metric_summary(c,RID,[])['scope_papers']==0
    differences=c.execute("""SELECT count(*) AS n FROM smartlib.publication_metric_value v
        JOIN smartlib.publication_metric_snapshot s USING(snapshot_id)
        JOIN smartlib.publication_metric_definition d USING(metric_code)
        WHERE s.release_id=%s AND (v.raw_value IS DISTINCT FROM s.raw_fields->d.source_field
          OR (v.value_status='present' AND v.numeric_value IS DISTINCT FROM (s.raw_fields->>d.source_field)::numeric))""",(RID,)).fetchone()['n']
    assert differences==0
    rejected=[]
    def rejects(name,sql,args):
        try:
            with c.transaction(): c.execute(sql,args)
        except psycopg.Error:
            rejected.append(name)
        else: raise AssertionError('Invalid operation accepted: '+name)
    rejects('validated_release_rewrite',"UPDATE smartlib.publication_metric_release SET dataset_label='overwrite' WHERE release_id=%s",(RID,))
    rejects('validated_value_insert',"INSERT INTO smartlib.publication_metric_value SELECT snapshot_id,metric_code,numeric_value,value_status,raw_value FROM smartlib.publication_metric_value WHERE snapshot_id=%s LIMIT 1",(present['snapshot_id'],))
    fixture=uuid4()
    c.execute("""INSERT INTO smartlib.publication_metric_release
       (release_id,source_system_id,ingestion_batch_id,provider,scope_key,dataset_label,exported_on,dataset_updated_on,indexed_through,source_uri,source_sha256,rule_version,expected_publication_count,expected_metric_codes,context,created_by)
       SELECT %s,source_system_id,ingestion_batch_id,provider,scope_key,dataset_label,exported_on,dataset_updated_on,indexed_through,source_uri,source_sha256,%s,expected_publication_count,expected_metric_codes,context,created_by
       FROM smartlib.publication_metric_release WHERE release_id=%s""",(fixture,str(fixture),RID))
    rejects('incomplete_release_publish',"UPDATE smartlib.publication_metric_release SET release_state='validated',validated_at=clock_timestamp() WHERE release_id=%s",(fixture,))
    fixture_snap=uuid4()
    c.execute("""INSERT INTO smartlib.publication_metric_snapshot
       (snapshot_id,release_id,publication_id,source_reference_id,ingestion_record_id,source_row,source_publication_year,local_publication_year_at_import,source_document_type,source_research_areas,source_collaboration_type,raw_fields)
       SELECT %s,%s,publication_id,source_reference_id,ingestion_record_id,source_row,source_publication_year,local_publication_year_at_import,source_document_type,source_research_areas,source_collaboration_type,raw_fields FROM smartlib.publication_metric_snapshot WHERE snapshot_id=%s""",(fixture_snap,fixture,present['snapshot_id']))
    for code,value in [('incites.subject_percentile','101'),('incites.times_cited','-1'),('incites.times_cited','1.5'),('incites.cnci','NaN')]:
        rejects('invalid_'+code+'_'+value,"INSERT INTO smartlib.publication_metric_value(snapshot_id,metric_code,numeric_value,value_status,raw_value) SELECT %s,%s,%s,'present',s.raw_fields->d.source_field FROM smartlib.publication_metric_snapshot s CROSS JOIN smartlib.publication_metric_definition d WHERE s.snapshot_id=%s AND d.metric_code=%s",(fixture_snap,code,value,fixture_snap,code))
    c.execute("SELECT set_config('smartlib.actor_id',%s,true)",(str(uuid4()),))
    assert c.execute('SELECT count(*) AS n FROM smartlib.publication_metric_analysis').fetchone()['n']==0
    result=json.dumps({'status':'passed','raw_value_mismatches':differences,'rejected_invalid_operations':rejected,'unauthorized_rows':0,'summary':summary},ensure_ascii=False,default=str)
    Path('/tmp/publication_metric_verification.json').write_text(result)
    print(result)
