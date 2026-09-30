import type { OutcomePaper } from '../../generated/smartlib-api';

export const dimensions = ['署名结构', '合作地域', '本校作者角色', '发表年份', '文献类型', '研究方向'] as const;
export type Dimension = typeof dimensions[number];
export interface StrategySettings { focal: string; primary: Dimension; secondary: Dimension | '不交叉'; scheme: string; metric: 'CNCI' | '被引次数' | '同年 JIF' };
export const defaultStrategy: StrategySettings = { focal: '', primary: '署名结构', secondary: '不交叉', scheme: 'NSFC_APPLICATION_CODE', metric: 'CNCI' };
export const median = (values: number[]) => {
  if (!values.length) return null;
  const v = [...values].sort((a, b) => a - b), i = Math.floor(v.length / 2);
  const current = v[i] ?? 0;
  return v.length % 2 ? current : ((v[i - 1] ?? current) + current) / 2;
};
export function settingsConcepts(p: OutcomePaper, scheme: string) {
  return scheme === '研究主题' ? p.topics ?? [] : (p.disciplines ?? []).filter(d => d.scheme === scheme);
}
export function labels(p: OutcomePaper, d: Dimension, s: StrategySettings): string[] {
  if (d === '署名结构') return [p.mode];
  if (d === '发表年份') return [String(p.publication_year ?? '年份未知')];
  if (d === '文献类型') return [p.publication_type ?? '类型未知'];
  if (d === '研究方向') {
    const assigned = settingsConcepts(p, s.scheme);
    const names = [...new Set(assigned.map(x => `${x.code ?? ''} ${x.name}`))].sort();
    return names.length ? names : ['该体系未分类'];
  }
  const affiliations = p.affiliations ?? [];
  if (d === '合作地域') {
    if (p.mode === '机构或作者信息不完整' || !affiliations.length || affiliations.some(a => !a.country_code)) return ['地域信息不足'];
    if (p.author_count < 2) return ['单作者，不判定合作'];
    return [new Set(affiliations.map(a => a.country_code)).size > 1 ? '跨国家或地区合作' : '同一国家或地区合作'];
  }
  if (!s.focal) return ['未选择本校机构'];
  const local = affiliations.filter(a => a.root_ids.includes(s.focal));
  if (!local.length) return [p.mode === '机构或作者信息不完整' ? '机构信息不足' : '未见本校署名'];
  const roles = new Set(local.flatMap(a => a.roles ?? []));
  const first = roles.has('第一作者') || roles.has('共同第一作者');
  const corresponding = roles.has('通讯作者') || roles.has('共同通讯作者');
  if (first && corresponding) return ['本校第一及通讯角色'];
  if (first) return ['本校第一作者角色'];
  if (corresponding) return ['本校通讯作者角色'];
  return ['本校角色待补证据'];
}
export function comparePapers(papers: OutcomePaper[], s: StrategySettings) {
  const groups = new Map<string, Map<string, OutcomePaper>>();
  for (const p of papers) for (const a of labels(p, s.primary, s)) for (const b of s.secondary === '不交叉' ? [''] : labels(p, s.secondary, s)) {
    const key = JSON.stringify([a, b]);
    if (!groups.has(key)) groups.set(key, new Map());
    groups.get(key)?.set(p.publication_id, p);
  }
  return [...groups].map(([key, rows]) => {
    const papers = [...rows.values()];
    const values = papers.map(p => s.metric === 'CNCI' ? p.cnci : s.metric === '被引次数' ? p.times_cited : p.impact_factor).filter((v): v is number => v != null);
    return { key, label: (JSON.parse(key) as string[]).filter(Boolean).join(' × '), papers, covered: values.length, median: median(values) };
  }).sort((a, b) => b.papers.length - a.papers.length || a.label.localeCompare(b.label));
}
export function partnerProfiles(papers: OutcomePaper[], focal: string) {
  const local = papers.filter(p => p.institution_ids?.includes(focal));
  const partners = new Map<string, { name: string; papers: OutcomePaper[] }>();
  for (const p of local) for (const id of (p.institution_ids ?? [])) {
    if (id === focal) continue;
    if (!partners.has(id)) partners.set(id, { name: id, papers: [] });
    const entry = partners.get(id);
    if (!entry) continue;
    // Names and IDs are independently sorted in legacy snapshots. Match only from explicit affiliations.
    entry.name = p.institution_name_by_id?.[id] ?? (p.affiliations ?? []).find(a => a.organization_id === id)?.organization_name ?? entry.name;
    entry.papers.push(p);
  }
  return [...partners].map(([id, x]) => ({ id, ...x,
    years: [...new Set(x.papers.map(p => p.publication_year).filter((y): y is number => y != null))].sort(),
    share: local.length ? x.papers.length / local.length : null,
    median: median(x.papers.map(p => p.cnci).filter((v): v is number => v != null)),
  })).sort((a, b) => b.papers.length - a.papers.length);
}
