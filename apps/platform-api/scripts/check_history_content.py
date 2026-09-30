"""Hash business rows without exporting sensitive content. No database writes."""
import json
import subprocess
import sys
from pathlib import Path

tables = ['knowledge_object','relation_assertion','publication_authorship','publication_metadata',
          'evidence_record','relation_evidence','source_reference','source_system',
          'person_profile','person_identifier','person_name_variant','organization_profile',
          'organization_identifier','organization_name_variant','publication_fulltext_resource',
          'publication_relation_provenance','change_submission','change_proposal',
          'journal_metric_release','journal_metric_record','publication_journal_metric_match']
sql = '\nUNION ALL\n'.join(
    "SELECT json_build_object('table','"+t+"','count',count(*),'checksum',md5(COALESCE(string_agg(h,'' ORDER BY h),'')))::text "
    "FROM (SELECT md5(to_jsonb(t)::text) h FROM smartlib."+t+" t) h" for t in tables)+';'
r = subprocess.run(['docker','exec','-i','smartlib-postgres-1','sh','-c',
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At'],
    input=sql,text=True,capture_output=True,check=True)
data = [json.loads(line) for line in r.stdout.splitlines()]
path = Path(sys.argv[1])
if path.exists():
    old=json.loads(path.read_text())
    assert data == old, 'Business content changed: '+str([x['table'] for x,y in zip(data,old) if x!=y])
    print('PASS: all '+str(len(tables))+' business tables have identical row counts and content checksums')
else:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2))
    print('Baseline saved: '+str(len(tables))+' tables')
