"""Read-only live snapshot plus checksum-verified local PDF content for classification."""
import hashlib,json,subprocess
from pathlib import Path

OUT=Path('outputs/paper_classification_269_20260909');OUT.mkdir(exist_ok=True)
sql="""SELECT coalesce(jsonb_agg(to_jsonb(x)),'[]') FROM (
 SELECT k.object_id::text publication_id,k.canonical_name title,m.publication_year,m.attributes,
 r.fulltext_resource_id::text,r.content_checksum,r.storage_uri
 FROM smartlib.knowledge_object k JOIN smartlib.publication_metadata m ON m.publication_id=k.object_id
 JOIN LATERAL (SELECT * FROM smartlib.publication_fulltext_resource r WHERE r.publication_id=k.object_id
 AND r.resource_role='article' ORDER BY r.updated_at DESC LIMIT 1) r ON true
 WHERE k.object_type='publication' AND k.system_to='infinity' ORDER BY k.object_id) x;"""
p=subprocess.run(['docker','exec','-i','smartlib-postgres-1','sh','-c',
 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At'],input=sql,text=True,capture_output=True,check=True)
live=json.loads(p.stdout);assert len(live)==269,len(live)
old=json.load(open('outputs/author_details_review_20260907/author_identity_abstract_review_20260908/review_269_identity_current.json'))
lookup={r['publication_id']:r for r in old['papers']}
pubmed={r['publication_id']:r for r in json.load(open('outputs/research_classification_20260909/论文分类来源核验初稿.json'))}
for i,row in enumerate(live,1):
 prior=lookup[row['publication_id']]
 path=Path('/private/tmp/smartlib-author-details.uAagIS')/f"{prior['n']:03}.pdf"
 sha=hashlib.sha256(path.read_bytes()).hexdigest()
 if sha!=row['content_checksum']:
  url=f"http://127.0.0.1:18080/api/v1/catalog/objects/{row['publication_id']}/resources/{row['fulltext_resource_id']}/content"
  payload=subprocess.run(['curl','--fail','--silent',url],capture_output=True,check=True).stdout
  assert hashlib.sha256(payload).hexdigest()==row['content_checksum'],(i,'live file mismatch')
  path=OUT/f"{row['publication_id']}.pdf";path.write_bytes(payload)
 result=subprocess.run(['pdftotext','-f','1','-l','3','-layout',str(path),'-'],capture_output=True,text=True,check=True)
 row.update(n=i,old_paper_number=prior['n'],pdf_path=str(path),pdf_opening_text=result.stdout,pdf_warnings=result.stderr,
            pubmed=pubmed[row['publication_id']])
 assert len(result.stdout.strip())>100,(i,'empty PDF text')
(OUT/'inputs.json').write_text(json.dumps(live,ensure_ascii=False,indent=2))
print(json.dumps({'papers':len(live),'pdf_hash_verified':len(live),'opening_pages_read':len(live),'output':str(OUT)}))
