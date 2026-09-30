"""Reproducible, read-only extraction from primary files; no database writes."""
import json, re, hashlib, subprocess, unicodedata, shutil
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'outputs/research_gap_completion_20260909'
OUT.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def clean(t):
    t=unicodedata.normalize('NFKC',t).replace('\u00ad','')
    return re.sub(r'\s+',' ',t).strip()
def norm(t):
    t=unicodedata.normalize('NFKD',clean(re.sub('<[^>]+>','',t)))
    return re.sub(r'[^\w]','',''.join(c for c in t if not unicodedata.combining(c)).casefold())
def pdftext(path,pages=2):
    return subprocess.check_output(['pdftotext','-f','1','-l',str(pages),path,'-'],stderr=subprocess.DEVNULL).decode()

ledger=json.loads((ROOT/'outputs/research_phase_two_20260909/缺项明细.json').read_text())
targets={r['publication_id'] for r in ledger['papers_without_usable_abstract_in_current_pipeline']}
assert len(targets)==86
inputs={r['publication_id']:r for r in json.loads((ROOT/'outputs/paper_classification_269_20260909/inputs.json').read_text())}
audits=json.loads((ROOT/'outputs/paper_classification_audit_269_20260909/audit_results.json').read_text())['papers']
# Exact boundaries checked in the source PDFs, not length-based truncations.
anchors={
 1:('Aim: Chaihu','KEYWORDS'),9:('Impulsivity is a core','X. Wang, Q. Li'),
 27:('Bone organoids hold','1. Introduction'),99:('Periodontitis is associated','1. Introduction'),
 110:('Intestinal ischemia reperfusion injury (II/R injury)','1. Introduction'),
 182:('Although chemodynamic therapy','1. Introduction'),
 197:('The clinical utility of the anticancer','X. Gao, Z. Xiao'),
 213:('摘要 缺氧性','关键词'),218:('Proline aminopeptidase (PAP','1. Introduction'),
 229:('The recent advance','Ó 2020'),233:('Choloylglycine hydrolase (CH','1. Introduction'),
 239:('Epithelial–mesenchymal transition (EMT) has','Oncogenesis (2015) 4, e143; doi:'),
 260:('Interactions among neurons','1. Introduction')}
noabs={3:'letter_without_abstract',36:'letter_without_abstract',49:'lecture_without_abstract',62:'letter_without_abstract',126:'correspondence_without_abstract',165:'preproof_and_pubmed_without_abstract'}
results=[]
for r in audits:
    if r['publication_id'] not in targets:continue
    p=inputs[r['publication_id']];n=r['n'];assert sha(p['pdf_path'])==p['content_checksum']
    t=pdftext(p['pdf_path'],4 if n==165 else 2)
    result={k:p[k] for k in ['publication_id','n','title','fulltext_resource_id','storage_uri','content_checksum','pdf_path']}
    result.update(abstract='',body_excerpt='',source_pages=[1],verification='primary_source_boundary_checked')
    if r['abstract_source']=='matched_pubmed_abstract':
        pm=p['pubmed'];xml=Path(pm['pubmed_source']);root=ET.parse(xml)
        article=next(a for a in root.findall('.//PubmedArticle') if a.findtext('.//PMID')==pm['pmid'])
        title=''.join(article.find('.//ArticleTitle').itertext());assert norm(title)==norm(p['title']),(n,title)
        parts=article.findall('.//Abstract/AbstractText');assert parts,n
        abstract='\n'.join((x.get('Label')+': ' if x.get('Label') else '')+''.join(x.itertext()) for x in parts)
        result.update(abstract=abstract,source_kind='pubmed_abstract',source_url='https://pubmed.ncbi.nlm.nih.gov/'+pm['pmid']+'/',source_file=str(xml),source_sha256=sha(xml),pmid=pm['pmid'],source_pages=[])
        words=set(re.findall(r'[a-z]{4,}',abstract.casefold()));pdfwords=set(re.findall(r'[a-z]{4,}',clean(t).casefold()))
        result['pdf_word_support']=round(len(words&pdfwords)/len(words),3)
    elif n in anchors:
        start,end=anchors[n];assert start in t,(n,start)
        piece=t.split(start,1)[1];assert end in piece,(n,end)
        piece=start+piece.split(end,1)[0]
        if n==1:
            piece=re.sub(r'Frontiers in Pharmacology\s+01\s+frontiersin.org\s+\fZhao et al.\s+10.3389/fphar.2023.1257617\s*','',piece)
            result['source_pages']=[1,2]
        if n==213:piece=piece.removeprefix('摘要 ');piece=re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])','',piece)
        result.update(abstract=clean(piece),source_kind='pdf_abstract',source_url=r['fulltext_url'])
    else:
        assert n in noabs,n
        # Store non-abstract evidence separately; never place it in abstract.
        if n==3:piece=t.split('To the Editor,',1)[1].split('Table 1A compares',1)[0]
        elif n in (36,62):piece=t.split('Dear Editor,',1)[1].split('This is an open access',1)[0]
        elif n==126:
            piece=t.split('\nW\n',1)[1].split('There is a reply',1)[0];piece='W'+piece.lstrip()
            piece=piece.replace('nature reviews urology','').replace('Check for updates','')
        elif n==165:
            alltext=pdftext(p['pdf_path'],55)
            piece=alltext.split('In summary, our study integrated',1)[1].split('Acknowledgments',1)[0]
            piece='In summary, our study integrated'+piece
            piece=re.sub(r'\n(?:of|ro|-p|re|lP|na|Jo|ur)\n','\n',piece)
            result['source_pages']=[alltext[:alltext.index('In summary, our study integrated')].count('\f')+1]
        else:
            # Chinese two-column page needs a visually transcribed opening paragraph.
            piece='丙酮酸脱氢酶（pyruvate dehydrogenase，PDH）催化丙酮酸氧化脱羧形成乙酰辅酶A、二氧化碳、连接糖酵解和三羧酸循环，在葡萄糖氧化中占据关键位置，在线粒体能量生产和细胞存活中起关键作用。在哺乳动物中，PDH在丙酮酸代谢中起“守门人”作用，维持葡萄糖的稳态。心血管病与能量代谢密切相关，线粒体中的PDH作为能量和代谢稳态的关键调节因子，被认为是一种潜在治疗靶点。'
        result.update(body_excerpt=clean(piece),source_kind='pdf_body_excerpt_not_abstract',abstract_absence_reason=noabs[n],source_url=r['fulltext_url'])
    assert result['abstract'] or result['body_excerpt']
    results.append(result)
assert len(results)==86
(OUT/'abstracts_and_exceptions.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
sources=OUT/'sources';sources.mkdir(exist_ok=True)
for r in results:
    if r.get('source_file'):
        path=Path(r['source_file']);shutil.copyfile(path,sources/(r['source_sha256']+path.suffix))
shutil.copyfile('/private/tmp/pubmed-40967537.xml',sources/'pubmed-40967537-no-abstract.xml')

# Parse every official entry, including professional codes embedded in medical notes.
shutil.copyfile('/private/tmp/moe-2022.pdf',OUT/'教育部研究生目录2022原件.pdf')
shutil.copyfile('/private/tmp/moe-notice.html',OUT/'教育部目录发布通知.html')
text=subprocess.check_output(['pdftotext','-layout','/private/tmp/moe-2022.pdf','-']).decode()
terms=[]
for page_number,page in enumerate(text.split('\f'),1):
    matches=list(re.finditer(r'^\s*(\d{4}|\d{2})\s+([^\n]+)',page,re.M))
    for i,m in enumerate(matches):
        code=m[1];raw=m[2].strip()
        if '（' in raw and '）' not in raw:
            tail=page[m.end():matches[i+1].start() if i+1<len(matches) else len(page)]
            raw+=re.sub(r'\s+','',tail.split('）')[0])+'）'
        name=re.split(r'[（*]',raw)[0].strip()
        locator={'pdf_page':page_number,'raw_entry':raw,'term_kind':'category' if len(code)==2 else ('professional_degree' if int(code[2])>=5 else 'academic_discipline'),'masters_only':raw.endswith('*')}
        terms.append({'code':code,'name':name,'parent_code':code[:2] if len(code)==4 else None,'source_locator':locator})
        for professional in re.findall(r'代码为\s*(\d{4})',raw):
            terms.append({'code':professional,'name':name,'parent_code':code[:2],'source_locator':{**locator,'term_kind':'professional_degree','embedded_in_code':code,'masters_only':False}})
assert len(terms)==198,len(terms)
assert sum(t['source_locator']['term_kind']=='academic_discipline' for t in terms)==117
assert sum(t['source_locator']['term_kind']=='professional_degree' for t in terms)==67
package={'version':'2022','source_url':'https://www.moe.gov.cn/srcsite/A22/moe_833/202209/t20220914_660828.html','verified_against_official':True,'terms':terms}
(OUT/'moe_package.json').write_text(json.dumps(package,ensure_ascii=False,indent=2))
print(json.dumps({'abstracts':sum(bool(r['abstract']) for r in results),'no_abstract':[{ 'n':r['n'],'reason':r['abstract_absence_reason']} for r in results if not r['abstract']],'moe_terms':len(terms),'pubmed_low_pdf_support':[(r['n'],r['pdf_word_support']) for r in results if r.get('pdf_word_support',1)<.65]},ensure_ascii=False))
