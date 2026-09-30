import json,re,sys
p=json.load(open('outputs/paper_classification_audit_269_20260909/dossier.json'))
for x in p[int(sys.argv[1])-1:int(sys.argv[2])]:
 a=x['abstract']
 if x['abstract_source']!='matched_pubmed_abstract':
  start=re.search(r'(?im)^(Aim:|Background[: ]|Purpose:|Objectives?:|Objective\n|目\s*的)',a)
  if start:a=a[start.start():]
  end=re.search(r'(?im)^\s*(KEY\s*WORDS|Index Terms|关键词|Abbreviations:|(?:1[. ]+|I[. ]+)?INTRODUCTION)\b',a)
  if end and end.start()>250:a=a[:end.start()]
  flat=re.sub(r'\s+',' ',a)
  end=re.search(r'\b1\.?\s+Introduction\b|\bAbbreviations:',flat,re.I)
  if end and end.start()>500:a=flat[:end.start()]
 print('\nC%03d'%x['n'],x['title']);print('NSFC',' '.join(r['code'] for r in x['classifications'] if r['scheme']=='NSFC_APPLICATION_CODE'))
 print('MESH','; '.join(r['name'] for r in x['classifications'] if r['scheme']=='MESH'))
 a=re.sub(r'\s+',' ',a)
 if len(sys.argv)>3 and len(a)>3000:a=a[:1900]+' [中段省略，必要时另行完整读取] '+a[-1000:]
 print('ABSTRACT',a)
 print('KEYWORDS',re.sub(r'\s+',' ','; '.join(x['keywords_candidates']))[:350])
