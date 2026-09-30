"""Read back the served workflow, not just the database import result."""
import json
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[3]/'outputs/research_gap_completion_20260909'
def get(path):
    with urlopen('http://127.0.0.1:18080'+path,timeout=60) as response:return json.load(response)
w=get('/api/v1/research/workspace')
rows=json.loads((ROOT/'abstracts_and_exceptions.json').read_text())
tasks={t['object_id']:t for t in w['tasks'] if t['state']=='open'}
for r in rows:
    s=tasks[r['publication_id']]['machine_suggestion']
    assert s['has_abstract']==bool(r['abstract']),r['n']
    assert s.get('has_body_evidence')==bool(r['body_excerpt']),r['n']
    assert (r['abstract'] or r['body_excerpt']) in s['text'],r['n']
    assert not any('教育部' in g for g in s['gaps'])
assert not w['gaps'],w['gaps']
medical=get('/api/v1/research/standards?'+urlencode({'scheme':'MOE_GRADUATE_DISCIPLINE','version':'2022','parent':'10'}))
terms=medical if isinstance(medical,list) else medical['items']
codes={t['code'] for t in terms};assert {'10','1001','1002','1051','1052','1055'}<=codes,codes
readback={'moe_standards':[x for x in w['standards'] if x['scheme']=='MOE_GRADUATE_DISCIPLINE'],
    'medical_terms':terms,'checked_target_count':len(rows),'target_real_abstracts':sum(bool(r['abstract']) for r in rows),
    'target_body_evidence_not_abstract':sum(bool(r['body_excerpt']) for r in rows),
    'all_tasks':len(tasks),'current_pipeline_has_abstract':sum(bool(t['machine_suggestion'].get('has_abstract')) for t in tasks.values()),
    'current_pipeline_has_body_evidence':sum(bool(t['machine_suggestion'].get('has_body_evidence')) for t in tasks.values()),
    'current_pipeline_title_only':sum(not t['machine_suggestion'].get('has_abstract') and not t['machine_suggestion'].get('has_body_evidence') for t in tasks.values())}
assert readback['current_pipeline_title_only']==0
(ROOT/'live_readback.json').write_text(json.dumps(readback,ensure_ascii=False,indent=2))
lines=['# 教育部目录与摘要补齐结果','',
    '已写入本地数据库并通过运行中的接口核验。未同步远端。','',
    '## 教育部目录','',
    '教育部《研究生教育学科专业目录（2022年）》：14个学科门类、117个一级学科、67个专业学位类别，共198条，184条上下级关系。',
    '保留官方代码、名称、学位类型及备注、PDF页码；医学条目注释中的1051、1052、1055专业学位代码也已补齐。',
    '同名不同代码分别保存，不擅自改动官方名称；官方PDF、发布通知、规范化文件存MinIO。未把2025年新旧对应表误当成一套新版目录。',
    '本次只补标准，不自动给论文新增教育部分类。','',
    '## 86篇论文','',
    '80篇真实摘要：67篇来自已匹配题名的PubMed原始XML，13篇重新按PDF版面核定摘要边界。',
    '6篇当前来源未提供常规摘要：另存正文摘录，在页面明确显示“不是摘要”。不填写虚构摘要。',
    '摘要和正文摘录写入来源证据层，当前分类流程直接读取；publication_metadata原字段和已确认分类均未改动。',
    '已刷新269篇待审建议：263篇可读取摘要或既有摘要候选，6篇读取明确标注的正文依据，没有仅靠题名的记录。既有183篇摘要候选未在本轮全面重审。','',
    '## 6篇无常规摘要的具体记录','',
    '|编号|论文与全文链接|已保存依据|','|---|---|---|']
for r in rows:
    if not r['abstract']:
        lines.append(f"|C{r['n']:03d}|[{r['title']}]({r['source_url']})|PDF第{','.join(map(str,r['source_pages']))}页正文；{r['abstract_absence_reason']}|")
lines+=['','## 验收与追溯','',
    '全部86篇主PDF校验值与数据库全文记录一致；67篇PubMed题名核对通过；人工限定13篇PDF摘要起止范围。',
    '数据库事务校验：原有知识对象、论文元数据、全部已有分类关系摘要校验值前后相同。新标准代码无重复、父级无缺失、无层级循环；重复执行新增数量为0。',
    '原始来源文件已存MinIO并回读校验SHA-256；每篇记录关联论文ID、来源、校验值、PDF页码或PMID及本次批次。',
    '针对目录同名不同代码及正文不冒充摘要的回归测试通过。',
    '', '[查看当前治理页面](http://127.0.0.1:18080/knowledge-hub/research)']
(ROOT/'完成说明.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({k:v for k,v in readback.items() if k!='medical_terms'},ensure_ascii=False))
