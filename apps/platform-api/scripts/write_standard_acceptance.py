"""Execute a stdlib-only QA companion and retain its cell outputs in a notebook."""
import contextlib
import io
import json
from pathlib import Path

root=Path('outputs/standard_library_20260909').resolve()
cells=[]
scope={}

def markdown(text):
    cells.append({'cell_type':'markdown','id':f'cell-{len(cells)}','metadata':{},'source':text})

def code(text):
    stream=io.StringIO()
    with contextlib.redirect_stdout(stream):exec(compile(text,'standard_acceptance','exec'),scope)
    cells.append({'cell_type':'code','id':f'cell-{len(cells)}','metadata':{},'source':text,
                  'execution_count':1+sum(c['cell_type']=='code' for c in cells),
                  'outputs':[{'output_type':'stream','name':'stdout','text':stream.getvalue()}]})

markdown('## tl;dr\n本地标准库入库验收。只核验标准对象，不对论文分类。下方单元格已按顺序执行。')
markdown('## Context & Methods\n粒度：体系＋版本＋标准代码。InCites无官方代码时使用原始名称作本地键。'
         '\n### Key Assumptions\n保留MeSH官方树位置冲突，不据树位置合并不同主题词；OCR原文和修正记录同时保留。')
markdown('## Data\n来源为官方NSFC图片、NLM XML及Clarivate Excel。所有原件的哈希和MinIO版本见minio_receipt.json。')
code(f"""import json, hashlib
from pathlib import Path
from collections import Counter
root=Path({str(root)!r})
package=json.loads((root/'package.json').read_text())
receipt=json.loads((root/'commit_receipt.json').read_text())
archive=json.loads((root/'minio_receipt.json').read_text())
assert receipt['applied'] and receipt['business_objects_unchanged']
assert len(package['objects'])==receipt['expected_objects']
assert len(package['relations'])==receipt['expected_relations']
print('对象',len(package['objects']),'关系',len(package['relations']),'原件',len(archive))
""")
markdown('## Results')
code("""objects={r['id']:r for r in package['objects']}
assert len(objects)==len(package['objects'])
for source in package['sources']:
    assert hashlib.sha256((root/source['path']).read_bytes()).hexdigest()==source['sha256']
    assert any(a['path']==source['path'] and a['sha256']==source['sha256'] and a['version_id'] for a in archive)
for edge in package['relations']:
    a=objects[edge['subject']]['attributes'];b=objects[edge['object']]['attributes']
    assert (a['scheme'],a['scheme_version'])==(b['scheme'],b['scheme_version'])
    assert edge['predicate'].startswith('taxonomy.')
print(dict(Counter(r['attributes']['scheme'] for r in objects.values())))
print('来源校验、MinIO版本、关系端点和体系边界：通过')
""")
markdown('## Takeaways\n业务对象内容校验未发生变化。标准库与论文分类分离。MeSH两个主题词存在3个官方树位置冲突，已记录告警；不宣称消除了源数据问题。')
notebook={'nbformat':4,'nbformat_minor':5,'metadata':{'kernelspec':{'name':'python3','display_name':'Python 3','language':'python'},
            'language_info':{'name':'python'},'execution_method':'sequential Python execution; stdlib only'},'cells':cells}
assert all(c['id'] and isinstance(c['source'],str) for c in cells)
(root/'标准库核验记录.ipynb').write_text(json.dumps(notebook,ensure_ascii=False,indent=2))
print('QA notebook executed and saved:',root/'标准库核验记录.ipynb')
