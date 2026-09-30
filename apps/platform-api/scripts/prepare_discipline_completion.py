"""Prepare source-bound WoS labels and conservative, pending MOE content candidates."""
import hashlib
import importlib.util
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path('outputs/discipline-completion-20260910')
spec = importlib.util.spec_from_file_location('rules', 'apps/platform-api/scripts/prepare_publication_discipline_review.py')
import sys
rules = importlib.util.module_from_spec(spec)
sys.modules['rules'] = rules
spec.loader.exec_module(rules)
live = json.loads((ROOT/'live.json').read_text())
prior = {p['publication_id']:p for p in json.loads(Path('outputs/paper_classification_269_20260909/inputs.json').read_text())}
standards = {(d['attributes']['scheme'],d['attributes']['scheme_code'].strip().upper()):d for d in live['standards'] if d['attributes'].get('scheme_code')}
rows, gaps, texts = [], [], []
for p in live['papers']:
    pid = p['publication_id']
    incites = p['attributes'].get('incites')
    if incites:
        labels = sorted(set(x.strip().upper() for x in incites['raw_fields']['研究方向'].split(';') if x.strip()))
        for code in labels:
            d = standards.get(('INCITES_WOS',code))
            if not d: raise ValueError(('Unknown source label',code))
            rows.append(dict(publication_id=pid,target_id=d['object_id'],scheme='INCITES_WOS',code=code,scheme_version=d['attributes']['scheme_version'],role='secondary',source_kind='external_indexing',source_reference_id=incites['source_reference_id'],source_uri=incites['raw_object_uri'],source_checksum=incites['file_sha256'],excerpt=incites['raw_fields']['研究方向'],rationale='按最新已导入 InCites 记录的研究方向原值关联；保留来源记录。'))
    old = prior[pid]
    path = Path(old['pdf_path'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == old['content_checksum']
    full = subprocess.run(['pdftotext','-layout',str(path),'-'],capture_output=True,text=True,check=True).stdout
    # Exclude reference list; body is supporting evidence, never sole classification signal.
    body = re.split(r'(?im)^\s*(?:references|bibliography|参考文献)\s*$',full)[0]
    abstract = p.get('abstract') or ''
    fields = {'题名':rules.normalize(p['title']), '摘要':rules.normalize(abstract)}
    scores, evidence = Counter(), {}
    for profile in rules.PROFILES:
        hits = [(name,m.group(0)) for name,text in fields.items() for pattern in profile.patterns if (m:=re.search(pattern,text,re.I))]
        if not hits: continue
        # Only direct profile targets; implicit secondary mappings are not adopted.
        code = profile.targets[rules.SCHEMES[0]][0][0]
        if ('MOE_GRADUATE_DISCIPLINE',code) not in standards: continue
        score = sum(12 if field=='题名' else 4 for field,_ in hits)*rules.PROFILE_FACTORS.get(profile.key,1)
        scores[code] += score
        evidence.setdefault(code,[]).append({'profile':profile.label,'rationale':profile.rationale,'hits':hits})
    ranked = scores.most_common()
    chosen = [(code,score) for code,score in ranked[:2] if score>=8 and (not ranked or score>=ranked[0][1]*0.55)]
    if not chosen: gaps.append({'publication_id':pid,'title':p['title'],'reason':'题名及摘要中缺少足够明确的分类信号，保留全文供后续语义核验'})
    for i,(code,score) in enumerate(chosen):
        d=standards['MOE_GRADUATE_DISCIPLINE',code]
        signals=evidence[code]
        terms=[term for signal in signals for _,term in signal['hits']]
        excerpt=rules.excerpt(body,terms,260)
        rows.append(dict(publication_id=pid,target_id=d['object_id'],scheme='MOE_GRADUATE_DISCIPLINE',code=code,scheme_version='2022',role='primary' if i==0 else 'secondary',source_kind='algorithmic_inference',source_uri=old['storage_uri'],source_checksum=old['content_checksum'],fulltext_resource_id=old['fulltext_resource_id'],excerpt=excerpt,rationale='内容规则候选，尚未经专家核验；'+ '；'.join(x['rationale'] for x in signals),signals=signals,heuristic_score=score))
    texts.append({'publication_id':pid,'title':p['title'],'fulltext_resource_id':old['fulltext_resource_id'],'sha256':old['content_checksum'],'fulltext_characters':len(full),'body':body,'abstract':abstract})
(ROOT/'content_evidence.json').write_text(json.dumps(texts,ensure_ascii=False,indent=2))
(ROOT/'assignments.json').write_text(json.dumps({'batch':'discipline-completion-20260910-v1','rows':rows,'gaps':gaps},ensure_ascii=False,indent=2))
print(json.dumps({'relations':dict(Counter(r['scheme'] for r in rows)),'papers':{s:len({r['publication_id'] for r in rows if r['scheme']==s}) for s in ['INCITES_WOS','MOE_GRADUATE_DISCIPLINE']},'fulltexts_read':len(texts),'gaps':len(gaps)},ensure_ascii=False))
