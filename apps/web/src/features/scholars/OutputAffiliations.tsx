import { requiredValue } from '../../shared/requiredValue';
import { Link } from 'react-router-dom';
import { Link as LinkIcon } from '@carbon/icons-react';
import type { ScholarAffiliation } from '../../generated/smartlib-api';

export function groupOutputAffiliations(items: ScholarAffiliation[]) {
  const organizations = new Map<string, { id: string; name: string; papers: Map<string, ScholarAffiliation[]> }>();
  for (const item of items) {
    if (item.category !== 'output') continue;
    // Group by governed entity identity, never by a potentially ambiguous name.
    const id = item.organization_id || `unresolved:${item.relation_id}`;
    let group = organizations.get(id);
    if (!group) {
      group = { id, name: item.organization_name, papers: new Map() };
      organizations.set(id, group);
    }
    const key = item.context_object_id ?? `unresolved:${item.relation_id}`;
    const records = group.papers.get(key) ?? [];
    records.push(item);
    group.papers.set(key, records);
  }
  return [...organizations.values()];
}

export function OutputAffiliations({ items }: { items: ScholarAffiliation[] }) {
  const groups = groupOutputAffiliations(items);
  const parents = new Map<string, string>();
  for (const group of groups) {
    const record = requiredValue(requiredValue([...group.papers.values()][0])[0]);
    const candidates = record.parent_organization_ids ?? [];
    // Ambiguous parents and missing parent affiliations stay separate, never invented.
    if (candidates.length !== 1 || !groups.some((g) => g.id === candidates[0])) continue;
    const parent = requiredValue(candidates[0]);
    const visited = new Set([group.id]);
    let cursor: string | undefined = parent;
    while (cursor && !visited.has(cursor)) { visited.add(cursor); cursor = parents.get(cursor); }
    if (!cursor) parents.set(group.id, parent);
  }
  function renderGroup(group: typeof groups[number]) {
    const record = requiredValue(requiredValue([...group.papers.values()][0])[0]);
    const level = record.organization_level;
    const levelLabel = level && level > 0 ? `${['', '一', '二', '三', '四', '五'][level] ?? level}级机构` : '层级待补';
    const paperCount = [...group.papers.values()].filter((records) => records[0]?.context_object_id).length;
    const children = groups.filter((child) => parents.get(child.id) === group.id);
    return <li className="sg-affiliation-node" key={group.id}><article className="sg-affiliation-record">
      <h3 className="sg-affiliation-heading"><span className="sg-affiliation-level">{levelLabel}</span><span>{group.name}</span>
        {record.organization_id && <Link className="sg-affiliation-link" to={`/institutions/${record.organization_id}`} aria-label={`查看${group.name}的机构详情`} title="查看机构详情"><LinkIcon size={18} /></Link>}
      </h3>
      <details className="sg-affiliation-support">
      <summary className="sg-affiliation-count">{paperCount} 篇论文支持此机构署名</summary>
      <ol className="sg-affiliation-papers">{[...group.papers.entries()].map(([key, records]) => {
        const first = requiredValue(records[0]);
        const title = records.find((r) => r.context_title)?.context_title;
        const rawTexts = [...new Set(records.map((r) => r.raw_affiliation).filter(Boolean))];
        const evidence = [...new Map(records.flatMap((r) => r.evidence ?? []).map((e) => [e.evidence_id, e])).values()];
        return <li key={key}>
          <p>{first.context_object_id ? <Link to={`/outputs/${first.context_object_id}`}>{title ?? first.context_object_id}</Link> : '来源成果尚未关联'}</p>
          {rawTexts.map((text) => <p key={text}>机构原文：{text}</p>)}
          <details><summary>查看 {evidence.length} 条来源依据</summary>{evidence.map((e) => <div key={e.evidence_id}><p>{e.source_name ?? '来源未标注'} · {e.citation}</p><p>{e.excerpt ?? ''}</p>{e.page_number != null && <p>PDF 页码：{e.page_number}</p>}</div>)}</details>
        </li>;
      })}</ol>
      </details>
    </article>{children.length > 0 && <ul className="sg-affiliation-children">{children.map(renderGroup)}</ul>}</li>;
  }
  return <ul className="sg-affiliation-tree">{groups.filter((group) => !parents.has(group.id)).map(renderGroup)}</ul>;
}
