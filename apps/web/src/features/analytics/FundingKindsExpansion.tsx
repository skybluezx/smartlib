import type { summarizeCommunityResearch } from './communityResearchSummary';

type Rows = ReturnType<typeof summarizeCommunityResearch>['categoryCounts'];
export function FundingKindsExpansion({ rows, missing }: { rows: Rows; missing: number }) {
  return <div className="sg-funding-category-counts" role="group" aria-label="六类资助分类的种类数量">
    {rows.map(row => <small className="sg-community-coverage" key={row.name}>{row.name}：{row.count} 种</small>)}
    {missing > 0 && <small className="sg-community-coverage">未记录分类：{missing} 种（需重新分析）</small>}
  </div>;
}
