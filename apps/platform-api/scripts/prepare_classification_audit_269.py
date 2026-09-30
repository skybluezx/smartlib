"""Read-only abstract/keyword dossier; never updates stored classifications."""
import hashlib,json,re,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path('outputs/paper_classification_audit_269_20260909');ROOT.mkdir(exist_ok=True)
papers=json.load(open('outputs/paper_classification_269_20260909/inputs.json'))
assign=json.load(open('outputs/paper_classification_269_20260909/assignments.json'))
old={p['n']:p for p in assign['papers']}
rows=[]
for p in papers:
 path=Path(p['pdf_path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==p['content_checksum']
 text=subprocess.run(['pdftotext','-f','1','-l','3',str(path),'-'],capture_output=True,text=True,check=True).stdout
 abstract=p['pubmed'].get('retrieved_abstract')
 source='matched_pubmed_abstract' if abstract else 'pdf_abstract_candidate'
 if not abstract:
  start=re.search(r'(?im)^\s*(?:a\s*b\s*s\s*t\s*r\s*a\s*c\s*t|摘\s*要)\s*[:：]?\s*',text)
  if start:
   rest=text[start.end():];end=re.search(r'(?im)^\s*(?:(?:\d[. ]+|I[. ]+)?Introduction|Key\s*words\s*[:：]|关键词|©|Copyright)',rest)
   abstract=rest[:end.start()] if end and end.start()>200 else rest[:6500]
  else:abstract=text[:11000];source='pdf_opening_no_detected_abstract_heading'
 kws=[]
 for m in re.finditer(r'(?im)^\s*(?:key\s*words|index terms|关键词)\s*[:：—-]?\s*',text):
  kws.append(text[m.end():m.end()+450])
 pm=p['pubmed'].get('pubmed_source')
 if pm:
  tree=ET.parse(pm)
  for a in tree.getroot().findall('PubmedArticle'):
   if a.findtext('MedlineCitation/PMID')==p['pubmed']['pmid']:
    kws.extend(''.join(e.itertext()) for e in a.findall('MedlineCitation/KeywordList/Keyword'))
 rows.append({'n':p['n'],'publication_id':p['publication_id'],'title':p['title'],
 'abstract':abstract,'abstract_source':source,'keywords_candidates':kws,'pdf_opening_text':text,
 'pdf_path':str(path),'pdf_sha256':p['content_checksum'],'fulltext_resource_id':p['fulltext_resource_id'],
 'classifications':[{'id':r['id'],'scheme':r['attributes']['scheme'],'code':r['attributes']['code'],'name':r['name'],
 'role':r['attributes']['classification_role'],'source':r['attributes']['source_kind']} for r in old[p['n']]['classifications']]})
(ROOT/'dossier.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print('Prepared',len(rows),'papers')
