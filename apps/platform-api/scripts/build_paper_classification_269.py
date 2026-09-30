"""Evidence-backed first-pass paper classifications, explicitly pending and versioned."""
import hashlib,html,json,re,unicodedata,shutil
from collections import Counter
from pathlib import Path
from uuid import UUID,uuid5

ROOT=Path('outputs/paper_classification_269_20260909')
NS=UUID('e9e7581e-c652-4a1b-bd8a-8a087b549bd9')
BATCH='paper-classification-269-20260909-v1'
def uid(*parts):return str(uuid5(NS,':'.join(parts)))
def norm(t):
 t=html.unescape(re.sub('<[^>]+>','',t))
 return ' '.join(re.sub(r'[^\w]+',' ',unicodedata.normalize('NFKC',t).casefold()).split())
def main():
 papers=json.loads((ROOT/'inputs.json').read_text())
 overrides=json.loads((ROOT/'mesh_semantic_overrides.json').read_text())
 decisions=json.loads((ROOT/'nsfc_decisions.json').read_text())
 package=json.load(open('outputs/standard_library_20260909/package.json'))
 terms={(x['attributes']['scheme'],x['attributes']['scheme_code']):x for x in package['objects']}
 primary={}
 for code,numbers in decisions['primary_groups'].items():
  for n in numbers:
   assert n not in primary;primary[n]=code
 assert set(primary)==set(range(1,270))
 secondary={n:[] for n in primary}
 for code,numbers in decisions['secondary_groups'].items():
  for n in numbers:
   if code!=primary[n]:secondary[n].append(code)
 # Title mention mapping is an inference, not MEDLINE indexing or a relevance proof.
 excluded={'Humans','Animals','Mice','Rats','Male','Female','Cells','Cell Line','Research','Models, Biological',
           'Treatment Outcome','China','Review','Genes','Proteins','Disease','Patients','Time Factors',
           'Clothing','Negotiating','Drive','Social Control, Formal','Organization and Administration',
           'Economics','Forecasting','Skeleton','Lipoylation','Bodily Secretions','Therapeutics',
           'Growth','Methods','Adult','Learning','Classification','Medicine','Biological Products',
           'Mass Screening','Sensitivity and Specificity','Cognition','Equipment and Supplies','Breast'}
 aliases=[]
 for (scheme,code),x in terms.items():
  if scheme!='MESH' or x['attributes'].get('node_type')!='descriptor' or x['name'] in excluded:continue
  for s in {x['name'],*x['attributes'].get('aliases',[])}:
   z=norm(s)
   if len(z)>=6 and len(z.split())<=10:aliases.append((z,code))
 rows=[];results=[];unmapped=[]
 for p in papers:
  n=p['n'];pub=p['publication_id'];local=[]
  def add(scheme,code,role,kind,method,evidence,extra=None):
   term=terms.get((scheme,code))
   if not term:
    unmapped.append({'n':n,'scheme':scheme,'code':code});return
   attrs={'scheme':scheme,'scheme_version':term['attributes']['scheme_version'],'code':code,
          'classification_role':role,'source_kind':kind,'method_version':method,
          'source_import_batch':BATCH,'evidence_excerpt':evidence,
          'fulltext_resource_id':p['fulltext_resource_id'],'fulltext_checksum':p['content_checksum'],
          'review_note':'系统分类建议，未人工审核；不是项目实际申请代码' if kind=='algorithmic_inference' else
                        '外部数据库原始标引，来源匹配已核验；未作为人工分类确认',
          'score_interpretation':'heuristic_not_probability',**(extra or {})}
   rid=uid(BATCH,pub,scheme,code,kind)
   r={'id':rid,'publication_id':pub,'target_id':term['id'],'name':term['name'],
      'predicate':'publication.has_research_topic' if scheme=='MESH' else 'publication.classified_as_discipline',
      'attributes':attrs,'source_uri':p['storage_uri'],'source_path':p['pdf_path'],
      'source_checksum':p['content_checksum'],'supporting_text':p['pdf_opening_text'][:16000],
      'supporting_pages':[1,2,3],'evidence_id':uid('evidence',rid),
      'source_reference_id':uid('source',rid),'review_state':'pending'}
   rows.append(r);local.append(r)
  for code in [primary[n],*secondary[n]]:
   role='primary' if code==primary[n] else 'secondary'
   rationale=f"依据论文研究对象和研究任务，暂归2026二级代码{code}（{terms['NSFC_APPLICATION_CODE',code]['name']}）；交叉方向以次分类保存。"
   add('NSFC_APPLICATION_CODE',code,role,'algorithmic_inference',decisions['method'],p['title'],
       {'rationale':rationale,'content_basis':'title_with_pdf_opening_content_and_targeted_abstract_review',
        'special_note':decisions['special_notes'].get(str(n),'')})
  ext=p['pubmed']['mesh']
  for m in ext:
   assert p['pubmed']['source_match_state']=='exact_normalized_title'
   assert norm(p['title'])==norm(p['pubmed']['title'])
   for q in m['qualifiers']:assert ('MESH',q['code']) in terms
   add('MESH',m['code'],'topic','external_indexing','pubmed-exact-title-descriptor-ui-v1',
       m['name'],{'major_topic':m['major_topic'],'qualifiers':m['qualifiers'],
                  'external_record_url':f"https://pubmed.ncbi.nlm.nih.gov/{p['pubmed']['pmid']}/",
                  'external_source_path':p['pubmed']['pubmed_source'],'assignment_year_known':False})
  if not ext:
   title=' '+norm(p['title'])+' ';matches={}
   for alias,code in aliases:
    if ' '+alias+' ' in title:
     if code not in matches or len(alias)>len(matches[code]):matches[code]=alias
   selected=[]
   for code,alias in sorted(matches.items(),key=lambda v:(-len(v[1]),v[0])):
    if any(' '+alias+' ' in ' '+old+' ' for _,old in selected):continue
    selected.append((code,alias))
    if len(selected)==5:break
   if str(n) in overrides:
    by_name={x['name']:c for (s,c),x in terms.items() if s=='MESH'}
    selected=[(by_name[name],name) for name in overrides[str(n)]]
   for code,alias in selected:
    add('MESH',code,'topic','algorithmic_inference','mesh-2026-title-controlled-alias-v1',p['title'],
        {'matched_phrase':alias,'rationale':('基于题名和必要摘要阅读的语义校正，非字面匹配；不声称PubMed标引。' if str(n) in overrides else
         '题名中的规范名称/同义词精确短语命中；作为主题建议，不声称PubMed标引。'),
         'semantic_override':str(n) in overrides})
  raw=p['pubmed']['evaluation']['raw_research_direction']
  if raw:
   for label in sorted(set(t.strip() for t in raw.split(';') if t.strip())):
    add('INCITES_WOS',label,'secondary','external_indexing','incites-official-research-areas-exact-label-v1',raw,
        {'rationale':'保留InCites导出原始研究方向，不将期刊评价类别替代论文内容分类。',
         'external_source_record':p['attributes'].get('incites',{})})
  results.append({'n':n,'publication_id':pub,'title':p['title'],'old_paper_number':p['old_paper_number'],
                 'fulltext_resource_id':p['fulltext_resource_id'],'classifications':local})
 assert not unmapped,unmapped
 assert len({r['id'] for r in rows})==len(rows)
 sources=[]
 for path in sorted({r['attributes']['external_source_path'] for r in rows if 'external_source_path' in r['attributes']}):
  original=Path(path);dest=ROOT/'sources'/original.name;dest.parent.mkdir(exist_ok=True)
  shutil.copyfile(original,dest)
  sources.append({'path':str(dest.relative_to(ROOT)),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
  for r in rows:
   if r['attributes'].get('external_source_path')==path:r['archive_source_path']=str(dest.relative_to(ROOT))
 summary={'papers':len(papers),'nsfc_primary':269,'relations':len(rows),
          'by_scheme':dict(Counter(r['attributes']['scheme'] for r in rows)),
          'by_source':dict(Counter(r['attributes']['source_kind'] for r in rows)),
          'mesh_external_papers':sum(bool(p['pubmed']['mesh']) for p in papers),
          'mesh_missing':[p['n'] for p in results if not any(r['attributes']['scheme']=='MESH' for r in p['classifications'])],
          'all_review_state':'pending','batch':BATCH}
 (ROOT/'assignments.json').write_text(json.dumps({'batch':BATCH,'rows':rows,'papers':results,'summary':summary,'sources':sources},ensure_ascii=False,indent=2))
 (ROOT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
 lines=['# 269篇论文分类初稿','',
 '本轮编号C001等仅用于此表；不是历史论文P编号。所有关系待审核，来源分类与系统推断分开保存。',
 '国自然主分类采用2026二级代码；不等于项目实际申请代码。MeSH：145篇来自PubMed，其余124篇为系统主题建议。',
 '证据范围：269份PDF校验值核实、开篇最多3页提取；逐题名语义归类，并针对跨学科与题名不足项阅读摘要。不是全篇逐段人工精读。','',
 '|本轮编号|历史论文编号|论文|国自然主方向|次方向|MeSH主题（来源）|InCites原类别|',
 '|---|---|---|---|---|---|---|']
 for p in results:
  ns=[r for r in p['classifications'] if r['attributes']['scheme']=='NSFC_APPLICATION_CODE']
  ms=[r for r in p['classifications'] if r['attributes']['scheme']=='MESH']
  ws=[r for r in p['classifications'] if r['attributes']['scheme']=='INCITES_WOS']
  def names(a):return '；'.join(r['name'] for r in a)
  label='PubMed标引' if ms and ms[0]['attributes']['source_kind']=='external_indexing' else '系统建议'
  link=f"http://127.0.0.1:18080/api/v1/catalog/objects/{p['publication_id']}/resources/{p['fulltext_resource_id']}/content"
  lines.append(f"|C{p['n']:03}|P{p['old_paper_number']:03}|[{p['title'].replace('|','/').replace(chr(10),' ')}]({link})|{ns[0]['attributes']['code']} {ns[0]['name']}|{names(ns[1:]) or '—'}|{names(ms)}（{label}）|{names(ws) or '无原始InCites分类，不推造'}|")
 (ROOT/'269篇论文分类明细.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
