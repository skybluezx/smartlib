import type { CommunityResearch } from '../../generated/smartlib-api';

// Derive from the same paper sets as the detail panel; no second data source.
export function summarizeCommunityResearch(r: CommunityResearch, papers: string[], scheme: string) {
  const scope = new Set(papers);
  const within = (ids: string[]) => new Set(ids.filter(id => scope.has(id)));
  const funded = within(r.funded_publication_ids);
  const groups = r.funding.filter(f => f.basis === 'funded' && within(f.publication_ids).size > 0);
  const directions = r.directions.filter(d => JSON.stringify([d.scheme, d.version]) === scheme)
    .map(d => ({ ...d, ids: within(d.publication_ids) })).filter(d => d.ids.size > 0);
  const perPaper = new Map<string, Set<string>>();
  for (const d of directions) for (const id of d.ids) {
    const keys = perPaper.get(id) ?? new Set<string>(); keys.add(d.key); perPaper.set(id, keys);
  }
  const classified = new Set(perPaper.keys());
  const largest = Math.max(0, ...directions.map(d => d.ids.size));
  const categoryNames = ['境内中央公共资助','境内地方公共资助','高校／科研院所／医院资助','境内社会组织／企业资助','境外及国际资助','来源待确认'];
  const categoryCounts = categoryNames.map(name => ({ name, count: new Set(groups.filter(g => g.object_id && g.category_label === name).map(g => g.object_id)).size }));
  return {
    categoryCounts,
    missingCategoryCount: new Set(groups.filter(g => g.object_id && (!g.category_label || !categoryNames.includes(g.category_label))).map(g => g.object_id)).size,
    fundingKinds: groups.map(g => ({ key:g.key, name:g.name, objectId:g.object_id,
      projects:new Set(g.project_ids ?? []).size, publications:within(g.publication_ids).size }))
      .sort((a,b) => b.publications-a.publications || a.name.localeCompare(b.name)),
    total: scope.size, funded: funded.size, representative: within(r.representative_publication_ids).size,
    projects: new Set(groups.flatMap(g => g.project_ids ?? [])).size,
    kinds: new Set(groups.filter(g => g.object_id != null).map(g => g.object_id)).size,
    untyped: new Set(groups.filter(g => g.object_id == null).flatMap(g => g.project_ids ?? [])).size,
    classified: classified.size, directionCount: new Set(directions.map(d => d.key)).size,
    multiple: [...perPaper.values()].filter(keys => keys.size > 1).length,
    leading: directions.filter(d => d.ids.size === largest).map(d => d.name).sort(),
    leadingCount: largest,
    cross: [...classified].filter(id => funded.has(id)).length,
  };
}
