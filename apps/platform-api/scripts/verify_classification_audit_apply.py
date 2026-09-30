"""Read-only privileged verification of history and persisted projection policy."""
import contextlib
import io
import json
import subprocess
from pathlib import Path

ROOT=Path('outputs/paper_classification_audit_269_20260909')
SQL="""BEGIN READ ONLY;
SELECT json_build_object(
'history_ids',(SELECT json_agg(DISTINCT r.entity_id) FROM smartlib.entity_revision r JOIN smartlib.change_event c USING(change_id) WHERE c.trace_id='paper-classification-audit-269-20260909-v2' AND r.entity_table='relation_assertion'),
'updated_with_before_after',(SELECT count(*) FROM smartlib.entity_revision r JOIN smartlib.change_event c USING(change_id) WHERE c.trace_id='paper-classification-audit-269-20260909-v2' AND r.entity_table='relation_assertion' AND r.operation='UPDATE' AND r.before_value IS NOT NULL AND r.after_value IS NOT NULL),
'active_relations',(SELECT count(*) FROM smartlib.relation_assertion WHERE attributes->>'source_import_batch' IN ('paper-classification-audit-269-20260909-v2','paper-classification-269-20260909-v1') AND smartlib.analysis_state_eligible(review_state) AND system_to='infinity'),
'excluded_relations',(SELECT count(*) FROM smartlib.relation_assertion WHERE attributes->>'source_import_batch'='paper-classification-269-20260909-v1' AND review_state IN ('rejected','superseded')),
'outbox_events',(SELECT count(*) FROM smartlib.outbox_event WHERE trace_id='paper-classification-audit-269-20260909-v2'),
'wrongly_projectable_excluded',(SELECT count(*) FROM smartlib.relation_assertion WHERE attributes->>'source_import_batch'='paper-classification-269-20260909-v1' AND review_state IN ('rejected','superseded') AND smartlib_projection.graph_relation_json(relation_id) IS NOT NULL)
);
COMMIT;"""
result=subprocess.run(['docker','exec','-i','smartlib-postgres-1','sh','-c','psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At'],input=SQL,text=True,capture_output=True,check=True)
readback=json.loads(result.stdout)
(ROOT/'post_apply_readback.json').write_text(json.dumps(readback,ensure_ascii=False,indent=2))
code='''import json
from pathlib import Path
root=Path(ROOT_PATH)
receipt=json.loads((root/'apply_receipt.json').read_text())
check=json.loads((root/'post_apply_readback.json').read_text())
replay=json.loads((root/'idempotency_receipt.json').read_text())
assert receipt['applied'] and receipt['changed_papers']==112
assert set(check['history_ids'])==set(receipt['relation_manifest'])
assert check['updated_with_before_after']==39
assert check['active_relations']==3010 and check['excluded_relations']==33
assert check['outbox_events']==184 and check['wrongly_projectable_excluded']==0
assert replay['mutations_this_run']=={} and replay['idempotent_replay']
assert receipt['all_269_nsfc_sets_verified'] and receipt['all_269_mesh_sets_verified']
assert receipt['objects_unchanged'] and receipt['deferred']==['C195']
print('PASS: 112 papers applied, 184 relation changes with history, 39 before/after snapshots, 3010 active classifications, replay zero changes, C195 untouched.')
'''
out=io.StringIO()
with contextlib.redirect_stdout(out):exec(compile(code,'<post-apply-qa>','exec'),{'ROOT_PATH':str(ROOT.resolve())})
notebook={'nbformat':4,'nbformat_minor':5,'metadata':{'execution_method':'fresh stdlib Python namespace, stdout captured; not Jupyter kernel'},'cells':[
 {'id':'sql','cell_type':'markdown','metadata':{},'source':['# 执行后验收\n','数据库只读查询：\n```sql\n'+SQL+'\n```\n']},
 {'id':'qa','cell_type':'code','metadata':{},'execution_count':1,'source':(f'ROOT_PATH={str(ROOT.resolve())!r}\n'+code).splitlines(keepends=True),'outputs':[{'output_type':'stream','name':'stdout','text':out.getvalue().splitlines(keepends=True)}]}]}
(ROOT/'执行后验收.ipynb').write_text(json.dumps(notebook,ensure_ascii=False,indent=2))
(ROOT/'执行完成说明.md').write_text('''# 分类审核建议执行完成

仅本地系统：112篇明确建议已执行，C195的主口径未调整。未修改论文、学者、机构和标准对象内容；未同步远端。

- 新增145条关系：44条国自然方向、101条MeSH主题。
- 调整6条既有分类的主次角色。
- 32条旧推断关系标记superseded，1条外部标引关系标记rejected以退出分析；原记录、属性及来源证据保留。
- 原始2,898条记录全部保留；加上新记录共3,043条，其中3,010条按当前pending/approved准入政策可参与分析。
- 184条变更均有历史记录，39条更新均保存修改前后快照。112篇逐篇审核证据已关联；完整审核包保存在MinIO，记录校验和及文件版本。
- 所有269篇NSFC和MeSH实际集合回查通过，重复执行新增/修改均为零，待确认及其他未涉变更的关系保持原状。

新增关系仍为pending，来源保持algorithmic_inference，不伪装为外部标引或逐篇人工确认。当前系统允许pending参与部分分析，因此这次变化可能影响既有图谱/分析；本次未生成独立正式画像，也未对前端逐页验收。投影通知184条已提交，已验证被撤下关系不能通过当前图谱准入函数。

采用数据质量核验流程的精确变更清单、完整集合回查及幂等检查，避免遗漏、重复写入和来源覆盖。原审核文件是执行前快照，实际执行结果以apply_receipt.json及本说明为准。
''')
print(out.getvalue())
