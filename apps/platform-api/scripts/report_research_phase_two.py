"""Export the implemented scope and concrete missing-data ledger from live APIs."""
import json
from pathlib import Path
from urllib.request import urlopen
root=Path('outputs/research_phase_two_20260909');root.mkdir(parents=True,exist_ok=True)
with urlopen('http://127.0.0.1:18080/api/v1/research/workspace') as r:workspace=json.load(r)
with urlopen('http://127.0.0.1:18080/api/v1/research/analysis') as r:analysis=json.load(r)
missing=[{'publication_id':t['object_id'],'title':t['name'],'missing':t['machine_suggestion'].get('gaps',[])} for t in workspace['tasks'] if not t['machine_suggestion'].get('has_abstract')]
ledger={'missing_standards':workspace['gaps'],'projects':[{'id':p['id'],'name':p['name'],'missing':p['missing']} for p in workspace['projects'] if p['missing']],
        'papers_without_usable_abstract_in_current_pipeline':missing,'scope':workspace['scope']}
(root/'缺项明细.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2))
lines=['# 第二期功能交付与数据缺项','',
'仅更新本地服务，未同步远端。功能可用不等于所有数据已齐或精细分类已审核。','',
'## 已实现','',
'1. 分类细化：按标准版本、代码前缀、名称检索；候选词面匹配、原文证据核对、主辅方向编辑。教育部目录具备版本化导入、原文件MinIO归档、重复/层级校验，尚无正式目录数据。',
'2. 科研分析：论文去重方向分布、年度变化、同篇交叉方向、潜在合作线索；支持学者/机构和年份筛选，均可追溯论文。不作为学者消歧或全校竞争力评价。',
'3. 项目对照：代表作方向与权威实际代码分开；支持实际代码年度、项目摘要/研究内容、来源、依据的提交与审核。同版本按代码层级相容比较，不等于内容合理性评价。',
'4. 日常治理：新增/修改题名或摘要自动排队；后台服务生成待审建议；人工编辑后才能批准，支持批量审核和任务/对象/分类并发版本检查；历史修改留存，画像实时更新。','',
f"当前可分析论文 {analysis['papers']} 篇，已分类 {analysis['classified']} 篇，国自然方向 {len(analysis['directions'])} 项。",
f"本轮建立 {len(workspace['tasks'])} 个细化待审任务，未修改既有 3,010 条已确认分类。",'',
'自动建议仅做标准词面命中，不声称完成全文语义精细分类。找不到足够证据时保留原分类并明确提示人工核验。','',
'## 仍需数据','',*['- '+x for x in workspace['gaps']],
f"- {len(ledger['projects'])} 个项目缺少权威实际申请代码、代码年度、项目摘要/研究内容及来源；请提供申请书、立项通知或权威数据库记录。",
f"- {len(missing)} 篇在当前自动流程中未取得可用摘要，只能基于题名生成候选；并非认定其PDF没有摘要。需要从全文补取或通过现有论文补充流程提供。",'',
'## 验收','',
'11项后端单元测试、6项前端组件测试通过，类型检查、页面构建通过。真实数据库回滚验收覆盖建议、审核、重复保护、项目资料、标准导入及幂等、画像刷新、新论文排队和内容变更重排；模拟记录零残留。',
'本地接口和浏览器验证：269篇覆盖、年份筛选（2025年起为90篇）、269项待审队列、项目逐项缺失提示。后台自动服务已运行。','',
'## 入口','',
'- [研究方向分析](http://127.0.0.1:18080/research-directions)',
'- [研究方向治理](http://127.0.0.1:18080/knowledge-hub/research)','',
'## 当前流程中缺少可用摘要的论文','']
lines += [f"- [{p['title']}](http://127.0.0.1:18080/outputs/{p['publication_id']})" for p in missing]
(root/'交付说明与缺项清单.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'papers':analysis['papers'],'tasks':len(workspace['tasks']),'missing_project_data':len(ledger['projects']),'missing_usable_abstract':len(missing)},ensure_ascii=False))
