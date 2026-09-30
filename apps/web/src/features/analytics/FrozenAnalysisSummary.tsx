import { Link } from 'react-router-dom';
import type { ScholarGraphAnalytics } from '../../generated/smartlib-api';
import { CooperationAssessmentPanel } from './CooperationAssessmentPanel';

export function FrozenAnalysisSummary({ result }: { result: ScholarGraphAnalytics }) {
  const schemes = result.disciplines?.workspace?.schemes ?? [];
  const paperNames = new Map(result.disciplines?.workspace?.papers.map(p => [p.object_id, p.title]) ?? []);
  const links = (ids: string[]) => <ul>{ids.map(id => <li key={id}><Link to={`/outputs/${id}`}>{paperNames.get(id) ?? id}</Link></li>)}</ul>;
  return <section aria-label="历史分析各模块结果">
    <p>以下数值来自保存时的快照，不发起重新计算。对象链接进入当前详情，可能与保存时的记录版本不同。</p>
    {result.journals && <details><summary>论文与期刊：{result.journals.journal_count} 种期刊</summary>
      <p>同年 JCR 覆盖 {result.journals.jcr_matched_publications} 篇；影响因子中位数 {result.journals.impact_factor.median ?? '缺失'}。</p>
      <ul>{result.journals.top_journals.map(j => <li key={j.object_id}>{j.name} · {j.publication_count} 篇</li>)}</ul></details>}
    {result.funding && <details><summary>基金项目分布</summary><ul>{result.funding.category_shares?.map(k => <li key={k.object_id}>{k.name} · {k.linked_project_count} 篇</li>)}</ul></details>}
    {result.project_journal_metrics && <details><summary>基金项目期刊指标</summary>{result.project_journal_metrics.annual_portfolios?.map(year => <div key={year.funding_year}><h3>{year.funding_year} 年项目</h3><p>{year.project_count} 个项目，去重论文 {year.unique_publications} 篇，同年 JCR 覆盖 {year.jcr_matched_publications} 篇，影响因子中位数 {year.impact_factor.median ?? '缺失'}。</p></div>)}</details>}
    {schemes.length > 0 && <details><summary>学科方向与年度统计依据</summary>{schemes.map(s => <details key={s.key}><summary>{s.name} · {s.version} · 覆盖 {s.covered_publications} 篇</summary>{s.directions.map(d => <details key={d.object_id}><summary>{d.name} · {d.publication_ids.length} 篇</summary>{links(d.publication_ids)}</details>)}</details>)}</details>}
    {result.direction_extensions && <details><summary>潜在合作线索（保存时）</summary><p>已冻结合作候选及其论文依据，保留在结果快照中。</p>{Array.isArray(result.direction_extensions.collaboration) && result.direction_extensions.collaboration.map((raw: unknown, index: number) => {
      if (!raw || typeof raw !== 'object') return null;
      const row = raw as Record<string, unknown>;
      return <details key={index}><summary>{typeof row.a_name === 'string' ? row.a_name : '学者'} — {typeof row.b_name === 'string' ? row.b_name : '学者'}</summary>{links([...(Array.isArray(row.a_papers) ? row.a_papers.filter((v): v is string => typeof v === 'string') : []), ...(Array.isArray(row.b_papers) ? row.b_papers.filter((v): v is string => typeof v === 'string') : [])])}</details>;
    })}</details>}
    {([['学者合作结构', result.people_collaboration], ['机构合作结构', result.institution_collaboration]] as const).map(([title, network]) => network?.assessment ? <details key={title}><summary>{title}</summary><CooperationAssessmentPanel assessment={network.assessment} directory={network.directory ?? []} /></details> : null)}
  </section>;
}
