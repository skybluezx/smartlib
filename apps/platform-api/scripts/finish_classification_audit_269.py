"""Compile human-readable audit recommendations. No database write operations."""
import argparse
import collections
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path('outputs/paper_classification_audit_269_20260909')
BASE = Path('outputs/paper_classification_269_20260909/assignments.json')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    baseline_hash = sha(BASE)
    papers = json.loads((ROOT / 'dossier.json').read_text())
    notes = [json.loads(s) for s in (ROOT / 'review_notes.jsonl').read_text().splitlines()]
    assert len(notes) == 269 and {n['n'] for n in notes} == set(range(1, 270))
    notes = {n['n']: n for n in notes}
    nsfc = {r['code']: r['name'] for r in json.loads(Path('outputs/research_classification_20260909/nsfc_structured.json').read_text())}
    mesh = {r['name']: r['code'] for r in json.loads(Path('outputs/research_classification_20260909/mesh_descriptors_2026.json').read_text())}
    if args.live:
        sql = """BEGIN READ ONLY;
SELECT json_agg(json_build_object('id',relation_id,'publication_id',subject_id,'review_state',review_state,'attributes',attributes) ORDER BY relation_id)
FROM smartlib.relation_assertion WHERE attributes->>'source_import_batch'='paper-classification-269-20260909-v1';
COMMIT;"""
        command = ['docker', 'exec', '-i', 'smartlib-postgres-1', 'sh', '-c', 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At']
        result = subprocess.run(command, input=sql, text=True, capture_output=True, check=True)
        live = json.loads(result.stdout)
        (ROOT / 'live_readback.json').write_text(json.dumps(live, ensure_ascii=False, indent=2))
    live = json.loads((ROOT / 'live_readback.json').read_text())
    live_by_id = {r['id']: r for r in live}
    expected_ids = {r['id'] for p in papers for r in p['classifications']}
    assert set(live_by_id) == expected_ids and len(live) == 2898
    results = []
    for p in papers:
        n = notes[p['n']]
        assert sha(Path(p['pdf_path'])) == p['pdf_sha256']
        for r in p['classifications']:
            actual = live_by_id[r['id']]
            assert actual['publication_id'] == p['publication_id'] and actual['review_state'] == 'pending'
            for key, attr in [('scheme','scheme'), ('code','code'), ('role','classification_role'), ('source','source_kind')]:
                assert r[key] == actual['attributes'][attr], (p['n'], key)
        original = [r for r in p['classifications'] if r['scheme'] == 'NSFC_APPLICATION_CODE']
        primary = [r['code'] for r in original if r['role'] == 'primary']
        assert len(primary) == 1
        old_secondary = [r['code'] for r in original if r['role'] == 'secondary']
        proposed_primary = n.get('primary', primary[0])
        proposed_secondary = n.get('secondary', old_secondary).copy()
        proposed_secondary = [x for x in proposed_secondary if x not in n.get('drop_secondary', [])]
        proposed_secondary = sorted(set(proposed_secondary + n.get('add_secondary', [])) - {proposed_primary})
        assert all(code in nsfc for code in [proposed_primary] + proposed_secondary)
        added = []
        original_mesh = [r for r in p['classifications'] if r['scheme'] == 'MESH']
        existing = {r['name'] for r in original_mesh}
        for term in n.get('mesh_add', []):
            assert term in mesh, term
            if term not in existing:
                added.append({'code': mesh[term], 'name': term})
        for term in n.get('mesh_remove', []):
            matching = [r for r in original_mesh if r['name'] == term]
            assert matching and all(r['source'] == 'algorithmic_inference' for r in matching)
        nsfc_changed = primary[0] != proposed_primary or set(old_secondary) != set(proposed_secondary)
        topic_changed = bool(added or n.get('mesh_remove') or n.get('external_scope_flag'))
        status = '需确认口径' if n.get('needs_decision') else ('建议调整' if nsfc_changed or topic_changed else '维持')
        followup = []
        pages = n.get('pdf_followup_pages', [])
        if p['n'] == 108:
            # Find the actual abstract after the publisher cover and graphical abstract.
            full = subprocess.run(['pdftotext', p['pdf_path'], '-'],capture_output=True,text=True,check=True).stdout
            pages = [i for i, t in enumerate(full.split('\f'), 1) if '\nAbstract\n' in t][:1]
            pages = pages + [pages[0] + 1] if pages else []
        for page in pages:
            text = subprocess.run(['pdftotext','-f',str(page),'-l',str(page),p['pdf_path'],'-'],capture_output=True,text=True,check=True).stdout
            followup.append({'pdf_page': page, 'text': text})
        results.append({**p, 'audit': n, 'status': status,
                        'current_primary': primary[0], 'current_secondary': old_secondary,
                        'proposed_primary': proposed_primary, 'proposed_secondary': proposed_secondary,
                        'nsfc_changed': nsfc_changed, 'topic_changed': topic_changed,
                        'mesh_add_resolved': added, 'followup_evidence': followup,
                        'fulltext_url': f"http://127.0.0.1:18080/api/v1/catalog/objects/{p['publication_id']}/resources/{p['fulltext_resource_id']}/content"})
    assert sha(BASE) == baseline_hash
    counts = dict(collections.Counter(p['status'] for p in results))
    summary = {'papers': 269, 'reviewed': 269, 'coverage_percent': 100, 'status_counts': counts,
               'nsfc_changed_papers': sum(p['nsfc_changed'] for p in results),
               'primary_changed_papers': sum(p['current_primary'] != p['proposed_primary'] for p in results),
               'topic_changed_papers': sum(p['topic_changed'] for p in results),
               'external_scope_flag_papers': sum(bool(p['audit'].get('external_scope_flag')) for p in results),
               'source_counts': dict(collections.Counter(p['abstract_source'] for p in results)),
               'live_pending_relations': len(live), 'baseline_sha256': baseline_hash,
               'database_writes': False, 'formal_profiles_generated': False,
               'mesh_additions': sum(len(p['mesh_add_resolved']) for p in results),
               'mesh_inferred_removals': sum(len(p['audit'].get('mesh_remove', [])) for p in results)}
    (ROOT / 'audit_results.json').write_text(json.dumps({'summary':summary,'papers':results},ensure_ascii=False,indent=2))
    (ROOT / 'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    def label(code):
        return code + ' ' + nsfc[code]
    def direction(primary, secondary):
        return '主：' + label(primary) + '；次：' + ('、'.join(map(label,secondary)) or '无')
    header = ['# 269篇论文分类内容审核', '',
              '范围：本地系统既有269篇论文，逐篇核对摘要、关键词及必要的PDF开篇/正文。覆盖率269/269（100%）。这是AI内容审核建议，不等于人工批准，也不是对论文科学结论真实性的鉴定。', '',
              '证据：175篇有已匹配PubMed摘要；其余94篇读取PDF摘要候选或开篇，30篇未识别独立摘要标题。长文本审查采用目的/结果重点段，疑点补读正文；本轮不是269篇PDF全页逐字或视觉版面复核。关键词候选可能夹带正文，未改写数据库摘要。', '',
              f"结论：维持 {counts.get('维持',0)} 篇；建议调整 {counts.get('建议调整',0)} 篇；需确认口径 {counts.get('需确认口径',0)} 篇。", '',
              f"其中学科方向建议调整 {summary['nsfc_changed_papers']} 篇（主方向 {summary['primary_changed_papers']} 篇），主题补全/细化/排除建议 {summary['topic_changed_papers']} 篇，两者有重叠。补标签不等于原分类错误。", '',
              '规则：以研究对象、目的和实际贡献为准，不根据机构定学科；已有合理主方向尽量保留；方法仅被使用不自动列独立学科；交叉研究可多归类。新MeSH标签均为系统建议，不伪装为PubMed原始标引。', '',
              'InCites作为评价来源保留：188篇有来源分类，81篇缺该来源，不按摘要补造。期刊/评价研究领域不要求与论文内容学科一一相同。', '',
              '状态：只生成本地建议文件，数据库2898条原关系核对为pending，未批准、未覆盖原标引、未生成正式画像、未同步远端。', '']
    detail = header.copy()
    changes = header + ['## 调整记录', '', '| 编号 | 论文 | 原学科 | 建议学科 | 主题调整 | 理由 |', '|---|---|---|---|---|---|']
    for p in results:
        a = p['audit']
        topic = []
        if p['mesh_add_resolved']: topic.append('补：' + '；'.join(x['name'] for x in p['mesh_add_resolved']))
        if a.get('mesh_remove'): topic.append('移除推断词：' + '；'.join(a['mesh_remove']))
        if a.get('external_scope_flag'): topic.append('原标引保留但建议不进入画像：' + '；'.join(a['external_scope_flag']))
        topic = ' / '.join(topic) or '维持'
        cur = direction(p['current_primary'],p['current_secondary'])
        prop = direction(p['proposed_primary'],p['proposed_secondary'])
        detail += [f"## C{p['n']:03d} · {p['status']}", '', p['title'], '', f"[论文全文]({p['fulltext_url']})", '',
                   '- 当前：' + cur, '- 建议：' + prop, '- MeSH：' + topic, '- 理由：' + a['note'],
                   '- 证据来源：' + p['abstract_source'] + ('；补读PDF页 ' + ','.join(str(x['pdf_page']) for x in p['followup_evidence']) if p['followup_evidence'] else ''), '',
                   '摘要/开篇证据片段（完整候选文本保存在audit_results.json）：', '', '> ' + ' '.join(p['abstract'].split())[:1600], '']
        if p['status'] != '维持':
            cells = [f"C{p['n']:03d}",f"[{p['title']}]({p['fulltext_url']})",cur,prop,topic,a['note']]
            changes.append('| ' + ' | '.join(s.replace('|','／').replace('\n',' ') for s in cells) + ' |')
    (ROOT / '269篇论文分类审核明细.md').write_text('\n'.join(detail))
    (ROOT / '分类调整建议.md').write_text('\n'.join(changes) + '\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
