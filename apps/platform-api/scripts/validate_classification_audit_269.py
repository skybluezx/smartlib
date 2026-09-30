"""Execute the audit QA companion in a fresh stdlib Python namespace."""
import contextlib
import io
import json
from pathlib import Path

root = Path(__file__).resolve().parents[3] / 'outputs/paper_classification_audit_269_20260909'
code = '''import hashlib, json
from pathlib import Path
root = Path(AUDIT_ROOT)
data = json.loads((root / 'audit_results.json').read_text())
papers, summary = data['papers'], data['summary']
assert len(papers) == 269
assert len({p['publication_id'] for p in papers}) == 269
assert {p['n'] for p in papers} == set(range(1, 270))
assert all(p['audit']['note'] and p['abstract'] and p['pdf_sha256'] for p in papers)
assert sum(summary['status_counts'].values()) == 269
assert not summary['database_writes'] and not summary['formal_profiles_generated']
assert all(not p['audit'].get('followup_pdf') for p in papers)
live = json.loads((root / 'live_readback.json').read_text())
assert len(live) == 2898 and all(x['review_state'] == 'pending' for x in live)
assert {x['id'] for x in live} == {r['id'] for p in papers for r in p['classifications']}
baseline = root.parent / 'paper_classification_269_20260909/assignments.json'
assert hashlib.sha256(baseline.read_bytes()).hexdigest() == summary['baseline_sha256']
for name in ['269篇论文分类审核明细.md', '分类调整建议.md']:
    text = (root / name).read_text()
    assert '未生成正式画像' in text
detail = (root / '269篇论文分类审核明细.md').read_text()
assert sum(detail.count(f'## C{i:03d} ·') for i in range(1, 270)) == 269
print('PASS: 269 unique reviewed papers; 2898 pending baseline relations; no database writes; original package unchanged.')
print(json.dumps(summary['status_counts'], ensure_ascii=False))
'''
capture = io.StringIO()
with contextlib.redirect_stdout(capture):
    exec(compile(code, '<audit-qa>', 'exec'), {'AUDIT_ROOT': str(root)})
notebook = {
    'nbformat': 4, 'nbformat_minor': 5,
    'metadata': {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'},
                 'execution_method': 'Fresh Python stdlib namespace, sequential execution, stdout captured; not executed by Jupyter kernel'},
    'cells': [
        {'id': 'scope', 'cell_type': 'markdown', 'metadata': {}, 'source': [
            '# 269篇分类内容审核验收\n',
            '只验收覆盖、可追溯性与未改写边界，不把断言通过等同于学术判断绝对准确。\n',
            '本机无Jupyter依赖；代码已由独立Python进程内新命名空间执行，结果原样记录。\n']},
        {'id': 'qa', 'cell_type': 'code', 'metadata': {}, 'execution_count': 1,
         'source': (f'AUDIT_ROOT = {str(root)!r}\n' + code).splitlines(keepends=True),
         'outputs': [{'output_type': 'stream', 'name': 'stdout', 'text': capture.getvalue().splitlines(keepends=True)}]}
    ]}
(root / '审核验收.ipynb').write_text(json.dumps(notebook, ensure_ascii=False, indent=2))
(root / '验收结果.txt').write_text(capture.getvalue())
print(capture.getvalue())
