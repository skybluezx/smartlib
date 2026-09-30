import { useSessionState } from './useSessionState';
import { analysisPosition, analysisTabs, analysisSections } from './analysisNavigation';
import type { ReactNode } from 'react';
import { requiredValue } from '../../shared/requiredValue';
import { CooperationAssessmentPanel } from './CooperationAssessmentPanel';
import { DisciplinePanel } from './DisciplinePanel';
import { CollaborationOutcomesPanel } from './CollaborationOutcomesPanel';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render as baseRender, screen, within } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getScholarGraphAnalyticsView } from '../../shared/api/smartlib';
import { ScholarGraphAnalyticsPage } from './ScholarGraphAnalyticsPage';

beforeEach(() => sessionStorage.clear());

HTMLElement.prototype.scrollIntoView = vi.fn();
function render(ui: ReactNode) { const client = new QueryClient({defaultOptions:{queries:{retry:false}}}); return baseRender(ui, {wrapper: ({children}) => <QueryClientProvider client={client}>{children}</QueryClientProvider>}); }

vi.mock('../../shared/api/smartlib', () => ({
  getProjectKindFilterOptions: vi.fn().mockResolvedValue({ items: [] }),
  listCustomGraphScopesView: vi.fn().mockResolvedValue([]),
  deleteCustomGraphScopeView: vi.fn().mockResolvedValue(undefined),
  saveCustomGraphScopeView: vi.fn().mockResolvedValue({
    scope_id: 'scope-1', name: '王姓学者论文', graph_query: 'MATCH ...', query_language: 'cypher',
    last_result_count: 12, created_at: '2026-09-09T10:00:00+08:00', updated_at: '2026-09-09T10:00:00+08:00',
  }),
  previewCustomGraphScopeView: vi.fn().mockResolvedValue({
    query_hash: 'hash-1', publication_count: 12, publications_with_authors: 12,
    publications_with_affiliations: 10, minimum_year: 2021, maximum_year: 2026,
    top_journals: [], sample_publications: [{ object_id: 'publication-1', title: '合作论文', publication_year: 2024, journal_name: 'Journal A' }],
    truncated: false, took_ms: 18,
  }),
  getGraphAnalysisScopeOptionsView: vi.fn().mockResolvedValue({
    minimum_year: 2021,
    maximum_year: 2026,
    project_kinds: [{ object_id: 'kind-1', name: '国家自然科学基金项目', publication_count: 166 }],
    organizations: [{ object_id: 'org-1', name: '大连医科大学', publication_count: 191 }],
    scholars: [{ object_id: 'scholar-1', name: '张三', publication_count: 12 }],
  }),
  getScholarGraphAnalyticsView: vi.fn().mockResolvedValue({
    scope: { publication_count: 271, project_kind_ids: [], organization_ids: [], scholar_ids: [] },
    coverage: { publications: 271, publications_with_authors: 271, publications_with_affiliations: 191, publications_with_disciplines: 271, graph_backend: 'hugegraph', aggregation_source: 'authoritative_relation_records', generated_at: '2026-09-04T03:00:00+08:00' },
    funding: {
      verified_programs: [{ object_id: 'fund-1', name: '国家自然科学基金委员会（NSFC）', funding_agency: '国家自然科学基金委员会（NSFC）', linked_project_count: 166, share: 1 }],
      verified_project_links: 305,
      category_shares: [{ object_id: 'kind-1', name: '国家自然科学基金项目', linked_project_count: 195, share: 195/271, funding_agency: null }],
      candidate_programs: [{ object_id: 'kind-1', name: '国家自然科学基金项目', relation_count: 460, linked_item_count: 195, share: 1, average_confidence: 0, review_state: 'pending' }],
      pending_program_relation_count: 3242,
      pending_grant_relation_count: 1578,
      pending_program_candidate_count: 700,
      pending_grant_candidate_count: 939,
      pending_project_kind_count: 318,
      included_project_kind_count: 318,
      pending_relation_count: 4820,
      pending_candidate_count: 1639,
      scope_note: '当前基金分布以 InCites 为有效统计口径。',
    },
    people_collaboration: network('person', '甲', '乙'),
    institution_collaboration: network('organization', '大连医科大学校本部', '大连理工大学', '医工合作'),
    disciplines: { workspace: disciplineFixture(), broad_disciplines: [direction('基础医学', 158, 0, .58)], nsfc_directions: [direction('肿瘤学', 36, 14, .13)], gbt_directions: [direction('内科学', 88, 15, .32)], classified_publications: 271, primary_relation_count: 813, secondary_relation_count: 330, review_state: 'pending', scope_note: '全文分析结果待核验。' },
    journals: { linked_publications: 270, journal_count: 165, top_journals: [{ object_id: 'journal-1', name: 'Journal A', publication_count: 5, share: 5 / 270 }], jcr_matched_publications: 1, cas_matched_publications: 1, impact_factor: { matched_publications: 1, mean: 8.2, median: 8.2, minimum: 8.2, maximum: 8.2 }, jcr_quartiles: quartiles('Q1'), cas_partitions: quartiles('Q2'), incites: incitesAnalysis(), scope_note: '只使用发表年完全一致的已发布指标。' },
    project_journal_metrics: {
      year_policy: 'publication_year', scope_note: '项目内按论文去重，多分类等权分摊。',
      projects: [projectMetric()],
      annual_portfolios: [{ funding_year: 2026, project_count: 1, project_publication_links: 1, unique_publications: 1, shared_publication_links: 0, publications_with_journal: 1, jcr_matched_publications: 1, cas_matched_publications: 1, impact_factor: { matched_publications: 1, mean: 8.2, median: 8.2, minimum: 8.2, maximum: 8.2 }, jcr_quartiles: quartiles('Q1'), cas_partitions: quartiles('Q2'), jcr_project_coverage: { full: 1, partial: 0, none: 0 }, cas_project_coverage: { full: 1, partial: 0, none: 0 }, top_journals: [{ object_id: 'journal-1', name: 'Journal A', publication_count: 1, share: 1 }], projects: [projectMetric()] }],
    },
  }),
}));

function direction(name: string, primary: number, secondary: number, share: number) {
  return { object_id: name, scheme: 'test', code: 'H01', name, level: 2, primary_publications: primary, secondary_publications: secondary, publication_count: primary + secondary, share };
}

function quartiles(selected: 'Q1' | 'Q2' | 'Q3' | 'Q4') {
  return (['Q1', 'Q2', 'Q3', 'Q4'] as const).map((quartile) => ({ quartile, paper_equivalents: quartile === selected ? 1 : 0, share: quartile === selected ? 1 : 0 }));
}

function incitesAnalysis() {
  const metric = (code: string, label: string, median: number, semanticLevel: 'publication' | 'journal_context' | 'normalization_baseline' = 'publication') => ({
    code, label, semantic_level: semanticLevel, unit: 'ratio', aggregation_rule: semanticLevel === 'publication' ? 'mean' : 'none', definition: `${label}的测试口径。`,
    covered_publications: 1, missing_publications: 270, mean: median, median, minimum: median, maximum: median,
    reference: code.includes('cnci') || code.endsWith('jnci') ? 1 : null,
    above_reference_count: code.includes('cnci') || code.endsWith('jnci') ? Number(median > 1) : null,
    total: code === 'incites.times_cited' ? median : null,
  });
  return {
    release_id: 'release-1', exported_on: '2026-09-09', indexed_through: '2026-07-31', dataset_updated_on: '2026-09-02',
    scope_publications: 271, snapshot_publications: 1,
    metrics: [
      metric('incites.times_cited', '被引频次', 12),
      metric('incites.cnci', '学科规范化的引文影响力', 1.5),
      metric('incites.jnci', '期刊规范化的引文影响力', .8),
      metric('incites.collab_cnci', '合作规范化的引文影响力', 1.2),
      metric('incites.subject_percentile', '学科领域百分位', 76),
      metric('incites.journal_expected_citations', '期刊预期被引频次', 13.8, 'normalization_baseline'),
      metric('incites.category_expected_citations', '类别预期被引频次', 10.1, 'normalization_baseline'),
      metric('incites.collaboration_expected_citations', '合作学科预期被引频次', 8.7, 'normalization_baseline'),
      metric('incites.jif_context', '期刊影响因子（来源上下文）', 7.3, 'journal_context'),
    ],
    publications: [{ publication_id: 'publication-1', title: '合作论文', publication_year: 2024, journal_name: 'Journal A', source_collaboration_type: '国际合作', metric_values: { 'incites.times_cited': 12, 'incites.cnci': 1.5, 'incites.jnci': .8, 'incites.collab_cnci': 1.2, 'incites.subject_percentile': 76 } }],
    scope_note: '固定使用同一份已验证 InCites 快照。',
  };
}

function projectMetric() {
  return { project_id: 'project-1', project_name: '甲 | 2026年度国家自然科学基金获批项目', funding_year: 2026, publication_count: 1, publications_with_journal: 1, jcr_matched_publications: 1, cas_matched_publications: 1, impact_factor: { matched_publications: 1, mean: 8.2, median: 8.2, minimum: 8.2, maximum: 8.2 }, jcr_quartiles: quartiles('Q1'), cas_partitions: quartiles('Q2'), publications: [{ publication_id: 'publication-1', title: '合作论文', publication_year: 2024, journal_id: 'journal-1', journal_name: 'Journal A', impact_factor: 8.2, jcr_quartiles: ['Q1'], cas_partitions: ['Q2'], jcr_metric_year: 2024, cas_metric_year: 2024 }] };
}

function network(nodeType: 'person' | 'organization', left: string, right: string, collaborationKind?: string) {
  return { scope_node_count: 3, matched_node_count: 2, matched_edge_count: 1, directory: [{ object_id: 'outside', name: '图外学者', node_type: nodeType, publication_count: 1, organizations: { 'org-1': '大连医科大学' } }], nodes: [{ object_id: 'left', name: left, node_type: nodeType, publication_count: 5, group_key: null }, { object_id: 'right', name: right, node_type: nodeType, publication_count: 4, group_key: null }], edges: [{ edge_id: 'edge-1', source_id: 'left', target_id: 'right', publication_count: 3, evidence_publications: [{ object_id: 'publication-1', title: '合作论文' }], collaboration_kind: collaborationKind ?? null, highlighted: Boolean(collaborationKind) }], total_node_count: 2, total_edge_count: 1, displayed_edge_count: 1, minimum_publication_count: 2, truncated: false, metric_note: '共同论文定义合作。' };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter><ScholarGraphAnalyticsPage /></MemoryRouter></QueryClientProvider>);
}

describe('ScholarGraphAnalyticsPage', () => {
  it('separates basic modules, topics and saved records while preserving the basic selection', async () => {
    renderPage();
    expect(await screen.findByRole('tablist', { name: '分析工作区' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '基础分析' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: '分析记录' })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('tab', { name: '论文与期刊' }));
    fireEvent.click(screen.getByRole('tab', { name: '专题分析' }));
    expect(screen.getByRole('heading', { name: '专题分析' })).toBeVisible();
    expect(screen.queryByRole('tab', { name: '基金项目分布' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '基础分析' }));
    expect(screen.getByRole('tab', { name: '论文与期刊' })).toHaveAttribute('aria-selected', 'true');
  });
  it('applies one shared analysis scope to every module', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { name: '分析范围' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '限定项目种类' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '限定机构' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: '限定学者' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('开始年份'), { target: { value: '2023' } });
    fireEvent.click(screen.getByRole('button', { name: '应用范围' }));
    expect(vi.mocked(getScholarGraphAnalyticsView)).toHaveBeenLastCalledWith(
      expect.objectContaining({ startYear: 2023, endYear: 2026, minimumPublicationCount: 2 }),
      expect.any(AbortSignal),
    );
  });

  it('integrates aggregate InCites impact metrics without a paper detail table', async () => {
    renderPage();
    expect(await screen.findByRole('region', { name: '发表期刊分布列表，可上下滚动' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'InCites 论文影响指标' })).toBeInTheDocument();
    expect(screen.getByText('索引截至 2026年7月31日')).toBeInTheDocument();
    expect(screen.getByText('累计被引频次')).toBeInTheDocument();
    expect(screen.getByText('CNCI 中位数')).toBeInTheDocument();
    expect(screen.getByText('规范化基准与期刊上下文')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: '论文明细' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '合作论文' })).not.toBeInTheDocument();
  });

  it('shows source-backed funding scope and coverage', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('tab', { name: '基金项目分布' }));
    expect((await screen.findAllByText('国家自然科学基金委员会（NSFC）')).length).toBeGreaterThan(0);
    expect(screen.getByText('PostgreSQL 权威聚合 · HugeGraph 图投影已启用')).toBeInTheDocument();
    expect(screen.getByText('全文提取项目关系')).toBeInTheDocument();
    expect(screen.getByText('4,820')).toBeInTheDocument();
    expect(screen.getByText('3,242')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'InCites 资助机构论文覆盖' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /项目种类论文覆盖/ })).toBeInTheDocument();
    expect(screen.getByText('166 篇论文')).toBeInTheDocument();
  });

  it('uses scoped distinct paper counts for full-width funding coverage instead of donut shares', async () => {
    renderPage();
    await screen.findByRole('heading', {name: '论文与期刊分析'});
    fireEvent.click(await screen.findByRole('tab', { name: '基金项目分布' }));
    const name = (await screen.findAllByRole('article', {name: '国家自然科学基金项目，195 篇论文，占当前范围 72%'}))[0];
    if (!name) throw new Error('Funding item absent');
    const row = name.closest('article');
    if (!row) throw new Error('Funding row missing');
    expect(within(row).getByText('72%')).toBeInTheDocument();
    expect(row.style.getPropertyValue('--coverage-width')).toBe(`${195 / 271 * 100}%`);
    expect(screen.queryByRole('img', { name: '项目种类占比环形图' })).not.toBeInTheDocument();
  });

  it('previews a read-only custom graph scope before applying it', async () => {
    renderPage();
    await screen.findByRole('heading', { name: '分析范围' });
    fireEvent.click(screen.getByRole('button', { name: '添加自定义范围' }));
    expect(screen.getByRole('dialog', { name: 'HugeGraph · 只读 Cypher' })).toBeInTheDocument();
    expect(screen.getByLabelText<HTMLTextAreaElement>('Cypher 查询语句').value).toContain('publication_id');
    fireEvent.click(screen.getByRole('button', { name: '执行并预览' }));
    expect(await screen.findByText('范围简报')).toBeInTheDocument();
    expect(screen.getAllByText('12').length).toBeGreaterThan(0);
    expect(screen.getAllByText('合作论文').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '应用此范围' })).toBeInTheDocument();
  });

  it('renders people, institution and discipline analysis tabs', async () => {
    renderPage();
    await screen.findByRole('heading', {name: '论文与期刊分析'});
    fireEvent.click(screen.getByRole('tab', { name: '学者合作' }));
    expect(await screen.findByLabelText(/甲与乙共同发表3篇论文/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '机构合作' }));
    expect(await screen.findByText('医工合作')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '学科方向' }));
    expect((await screen.findAllByText('基础医学')).length).toBeGreaterThan(0);
    expect(screen.getByRole('heading', { name: '各方向论文数量' })).toBeInTheDocument();
  });

  it('renders journal analysis without the retired project metric tab', async () => {
    renderPage();
    await screen.findByRole('heading', {name: '论文与期刊分析'});
    fireEvent.click(screen.getByRole('tab', { name: '论文与期刊' }));
    expect((await screen.findAllByText('Journal A')).length).toBeGreaterThan(0);
    expect(screen.getByText('165')).toBeInTheDocument();
    const journalPanel = screen.getByRole('tabpanel', { name: '论文与期刊' });
    expect(within(journalPanel).queryByText('同年中科院分区')).not.toBeInTheDocument();
    expect(within(journalPanel).queryByText('中科院分区')).not.toBeInTheDocument();
    expect(within(journalPanel).getByText('统计论文的发表期刊分布，期刊指标按论文的发表年份进行匹配。')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: '基金项目期刊指标' })).not.toBeInTheDocument();
    expect(analysisPosition(new URLSearchParams('tab=project_journal_metrics'))).toEqual({tab:0,section:0});
  });

  it('aligns collaboration graphs with drag, evidence, remove and enlarged interactions', async () => {
    renderPage();
    await screen.findByRole('heading', {name: '论文与期刊分析'});
    fireEvent.click(screen.getByRole('tab', { name: '学者合作' }));
    const node = await screen.findByRole('button', { name: /甲，关联5篇论文/ });
    const shell = node.closest<HTMLElement>('.sg-collaboration-shell');
    if (!shell) throw new Error('学者合作图没有找到交互容器');
    const graph = within(shell);
    const canvas = graph.getByLabelText('可拖拽的合作关系图');
    Object.defineProperty(node, 'setPointerCapture', { value: vi.fn() });
    Object.defineProperty(node, 'hasPointerCapture', { value: vi.fn().mockReturnValue(false) });
    const before = node.getAttribute('transform');
    fireEvent.pointerDown(node, { pointerId: 4, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(canvas, { pointerId: 4, clientX: 160, clientY: 130 });
    fireEvent.pointerUp(canvas, { pointerId: 4, clientX: 160, clientY: 130 });
    expect(node.getAttribute('transform')).not.toBe(before);

    fireEvent.click(node);
    fireEvent.click(graph.getByRole('button', { name: '查看关系来源' }));
    expect(screen.getByRole('dialog', { name: '甲的关系来源' })).toHaveTextContent('合作论文');
    fireEvent.click(screen.getByRole('button', { name: '关闭' }));

    fireEvent.click(graph.getByRole('button', { name: '从当前图中移除' }));
    fireEvent.click(screen.getByRole('button', { name: '从当前视图移除' }));
    expect(screen.queryByRole('button', { name: /甲，关联5篇论文/ })).not.toBeInTheDocument();
    fireEvent.click(graph.getByRole('button', { name: '恢复已移除节点（1）' }));
    expect(graph.getByRole('button', { name: /甲，关联5篇论文/ })).toBeInTheDocument();

    fireEvent.click(graph.getByRole('button', { name: '放大图谱区域' }));
    expect(screen.getByRole('dialog', { name: '合作关系图放大视图' })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '合作关系图放大视图' })).not.toBeInTheDocument();
  });
});


describe('CollaborationOutcomesPanel', () => {
  it('keeps zero distinct from missing and paginates the evidence papers', () => {
    const papers = Array.from({ length: 11 }, (_, i) => ({
      publication_id: `paper-${i}`, title: `论文依据${i}`, publication_year: 2024,
      mode: '单机构共同署名', author_count: 2, institution_names: ['机构甲'],
      institution_count: 1, affiliation_author_count: 2, cnci: i === 0 ? 0 : null,
      times_cited: null, impact_factor: null,
    }));
    render(<MemoryRouter><CollaborationOutcomesPanel data={{
      definition_version: 'collaboration-outcomes-v1', scope_hash: 'test-scope',
      groups: [{ mode: '单机构共同署名', publication_count: 11, cnci_covered: 1,
        cnci_median: 0, cnci_mean: 0, cited_covered: 0, jcr_covered: 0 }],
      papers, notes: ['缺失不补零'],
    }} /></MemoryRouter>);
    expect(screen.getAllByRole('link')).toHaveLength(10);
    expect(screen.getByRole('link', { name: '论文依据0' })).toHaveAttribute('href', '/outputs/paper-0');
    expect(screen.getAllByText('未覆盖').length).toBeGreaterThan(0);
    expect(screen.getAllByText('0').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: '下一页' }));
    expect(screen.getAllByRole('link')).toHaveLength(1);
    expect(screen.getByRole('link', { name: '论文依据10' })).toBeInTheDocument();
  });
});

// Shared cross-analysis selectors must preserve paper grain and missingness.
import { comparePapers, defaultStrategy, labels, partnerProfiles } from './strategyAnalysis';
import type { OutcomePaper } from '../../generated/smartlib-api';
const strategyPaper = (id: string, cnci: number | null): OutcomePaper => ({
  publication_id:id, title:id, mode:'多机构共同署名', author_count:2, institution_count:2,
  institution_names:['A','B'], institution_ids:['a','b'], institution_name_by_id:{a:'A',b:'B'},
  affiliation_author_count:2, cnci, publication_year:2024,
});
it('cross comparisons deduplicate within groups and retain absent metrics', () => {
  const p = strategyPaper('p1', 0), q = strategyPaper('p2', null);
  const groups = comparePapers([p,p,q], {...defaultStrategy,secondary:'发表年份'});
  expect(groups).toHaveLength(1);
  expect(groups[0]?.papers).toHaveLength(2);
  expect(groups[0]?.covered).toBe(1);
  expect(groups[0]?.median).toBe(0);
  expect(comparePapers([q],defaultStrategy)[0]?.median).toBeNull();
});
it('missing geography or author role is not inferred from names or order', () => {
  const p = strategyPaper('p1', 1);
  expect(labels(p,'合作地域',defaultStrategy)).toEqual(['地域信息不足']);
  p.affiliations = [{person_id:'x',person_name:'Name',organization_id:'a',organization_name:'A',root_ids:['a'],role_source:'bibliographic_order',roles:[],relation_id:'r',review_state:'pending'}];
  expect(labels(p,'本校作者角色',{...defaultStrategy,focal:'a'})).toEqual(['本校角色待补证据']);
});
it('partners use root identity mapping, not independently sorted names', () => {
  const p = strategyPaper('p1',1);
  p.institution_names=['B','A'];
  expect(partnerProfiles([p],'a')[0]?.name).toBe('B');
  expect(partnerProfiles([p],'a')[0]?.share).toBe(1);
});


function disciplineFixture() {
  return {
    publication_count: 3,
    papers: [{ object_id: 'p1', title: '分类证据论文', year: 2024,
      scholars: [{ object_id: 's1', name: '关联学者甲' }], organizations: [] }],
    schemes: [{ key: 'NSFC:2026', scheme: 'NSFC_APPLICATION_CODE', name: '国自然申请代码', version: '2026',
      dictionary_count: 100, covered_publications: 1, missing_publications: 2, multiclass_publications: 0,
      pending_publications: 1, intersections: [],
      directions: [{ object_id: 'c1', name: '基础医学', code: 'H01', level: 2, publication_ids: ['p1'],
        primary_publications: 1, secondary_publications: 0, unspecified_publications: 0,
        pending_publications: 1, scholar_count: 1, organization_count: 0, share: 1/3 }],
      evidence: [{ publication_id: 'p1', concept_id: 'c1', role: 'primary', review_state: 'pending',
        source_kind: 'algorithmic_inference', rationale: '依据研究对象分类', excerpt: '正文片段' }],
    }, { key: 'MOE:2022', scheme: 'MOE_GRADUATE_DISCIPLINE', name: '教育部学科目录', version: '2022',
      dictionary_count: 198, covered_publications: 0, missing_publications: 3, multiclass_publications: 0,
      pending_publications: 0, intersections: [], directions: [], evidence: [] }],
  };
}

it('explores discipline evidence, filters directions and reports empty dictionaries honestly', () => {
  Element.prototype.scrollIntoView = vi.fn();
  render(<MemoryRouter><DisciplinePanel workspace={disciplineFixture()} /></MemoryRouter>);
  expect(screen.getByRole('table', { name: '学科方向覆盖分布' })).toHaveTextContent('33.3%');
  fireEvent.click(screen.getByRole('button', { name: '查看基础医学的论文依据' }));
  const dialog = screen.getByRole('dialog', {name: '国自然申请代码 · 2026'});
  expect(within(dialog).getByRole('link', { name: '分类证据论文' })).toHaveAttribute('href', '/outputs/p1');
  expect(within(dialog).getByText(/系统内容分类/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/待核验|已采纳/)).not.toBeInTheDocument();
  expect(screen.queryByRole('columnheader', { name: '待核论文' })).not.toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: /close/i }));
  fireEvent.change(screen.getByRole('searchbox', {name: '搜索方向名称或代码'}), { target: { value: '不存在' } });
  expect(screen.getByText('没有匹配的方向，请更换关键词或清除搜索。')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '清除搜索' }));
  fireEvent.click(screen.getByRole('combobox', { name: '分类体系与版本' }));
  fireEvent.click(screen.getByRole('option', { name: '教育部学科目录 · 2022' }));
  expect(screen.getByText(/已收录 198 个字典条目/)).toBeInTheDocument();
  expect(screen.queryByRole('table', {name: '学科方向覆盖分布'})).not.toBeInTheDocument();
});

it('keeps discipline search during refresh and recomputes evidence from current relations', () => {
  const fixture = disciplineFixture();
  const { rerender } = render(<MemoryRouter><DisciplinePanel workspace={fixture} /></MemoryRouter>);
  fireEvent.change(screen.getByRole('searchbox', {name: '搜索方向名称或代码'}), { target: { value: 'H01' } });
  fireEvent.click(screen.getByRole('button', { name: '查看基础医学的论文依据' }));
  const updated = structuredClone(fixture);
  updated.schemes = updated.schemes.map((scheme) => ({ ...scheme,
    directions: scheme.directions.map((direction) => ({ ...direction, publication_ids: [] })), evidence: [],
  }));
  rerender(<MemoryRouter><DisciplinePanel workspace={updated} /></MemoryRouter>);
  expect(screen.getByRole('searchbox', {name: '搜索方向名称或代码'})).toHaveValue('H01');
  expect(within(screen.getByRole('dialog', {name: '国自然申请代码 · 2026'})).queryByRole('link', { name: '分类证据论文' })).not.toBeInTheDocument();
});


it('keeps GB/T in supplied data without exposing it as an analysis entry', () => {
  Element.prototype.scrollIntoView = vi.fn();
  const fixture = disciplineFixture();
  const catalog = fixture.schemes[1];
  if (!catalog) throw new Error('Missing catalog fixture');
  fixture.schemes.unshift({ ...catalog, key: 'GBT:2009', scheme: 'GBT_13745', name: 'GB/T 13745 学科分类', version: '2009' });
  render(<MemoryRouter><DisciplinePanel workspace={fixture} /></MemoryRouter>);
  expect(screen.getByRole('table', { name: '学科方向覆盖分布' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('combobox', { name: '分类体系与版本' }));
  expect(screen.queryByRole('option', { name: /GB\/T/ })).not.toBeInTheDocument();
  expect(screen.getByRole('option', { name: '国自然申请代码 · 2026' })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: '教育部学科目录 · 2022' })).toBeInTheDocument();
  expect(fixture.schemes[0]?.scheme).toBe('GBT_13745');
});


it('lets users find and explore people outside the bounded graph', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('tab', { name: '学者合作' }));
  await screen.findByRole('heading', { name: '关联人员目录' });
  expect(screen.getByRole('heading', { name: '关联人员目录' })).toBeVisible();
  fireEvent.change(screen.getByRole('textbox', { name: '搜索人员或署名机构' }), { target: { value: '图外学者' } });
  expect(screen.getByRole('link', { name: '图外学者' })).toHaveAttribute('href', '/scholars/outside');
  fireEvent.click(screen.getByRole('button', { name: '查看合作' }));
  await vi.waitFor(() => expect(getScholarGraphAnalyticsView).toHaveBeenLastCalledWith(expect.objectContaining({ peopleFocusId: 'outside', edgeLimit: 120 }), expect.any(AbortSignal)));
});


it('applies an arbitrary positive edge limit only on submit', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('tab', { name: '学者合作' }));
  await screen.findByRole('heading', { name: '关联人员目录' });
  const input = screen.getByRole('spinbutton', { name: '最多显示连线' });
  fireEvent.change(input, { target: { value: '500' } });
  fireEvent.click(screen.getByRole('button', { name: '应用连线数量' }));
  await vi.waitFor(() => expect(getScholarGraphAnalyticsView).toHaveBeenLastCalledWith(expect.objectContaining({ edgeLimit: 500 }), expect.any(AbortSignal)));
  fireEvent.change(await screen.findByRole('spinbutton', { name: '最多显示连线' }), { target: { value: '0' } });
  expect(screen.getByRole('button', { name: '应用连线数量' })).toBeDisabled();
});


it('filters visual clusters by membership and restores them without changing scope', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('tab', { name: '学者合作' }));
  await screen.findByRole('heading', { name: '关联人员目录' });
  fireEvent.change(screen.getByRole('spinbutton', { name: '合作簇最少人数' }), { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: '应用簇过滤' }));
  expect(screen.getByText('没有符合条件的合作簇，请降低最少成员数或显示全部合作簇。')).toBeVisible();
  expect(screen.getByRole('link', { name: '图外学者' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '显示全部合作簇' }));
  expect(screen.getByRole('button', { name: '甲，关联5篇论文' })).toBeInTheDocument();
});


it('defaults external collaborators to off until an institution is selected', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('tab', { name: '学者合作' }));
  await screen.findByRole('heading', { name: '关联人员目录' });
  const checkbox = screen.getByRole('checkbox', { name: '包含外部合作者' });
  expect(checkbox).not.toBeChecked();
  expect(checkbox).toBeDisabled();
});


it('preserves the scholar and external switch when the institution changes', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('tab', { name: '学者合作' }));
  await screen.findByRole('heading', { name: '关联人员目录' });
  fireEvent.click(screen.getByRole('button', { name: '查看合作' }));
  await vi.waitFor(() => expect(getScholarGraphAnalyticsView).toHaveBeenLastCalledWith(expect.objectContaining({ peopleFocusId: 'outside' }), expect.any(AbortSignal)));
  const institution = await screen.findByRole('combobox', { name: '探索署名机构' });
  fireEvent.change(institution, { target: { value: '大连' } });
  fireEvent.click(await screen.findByRole('option', { name: '大连医科大学' }));
  await vi.waitFor(() => expect(getScholarGraphAnalyticsView).toHaveBeenLastCalledWith(expect.objectContaining({ peopleFocusId: 'outside', peopleOrganizationId: 'org-1' }), expect.any(AbortSignal)));
  fireEvent.click(await screen.findByRole('checkbox', { name: '包含外部合作者' }));
  await vi.waitFor(() => expect(getScholarGraphAnalyticsView).toHaveBeenLastCalledWith(expect.objectContaining({ peopleFocusId: 'outside', peopleOrganizationId: 'org-1', peopleIncludeExternal: true }), expect.any(AbortSignal)));
  expect(await screen.findByRole('combobox', { name: '探索学者的一度合作' })).toHaveValue('图外学者');
});


it.each(['person', 'organization'] as const)('shows separate assessment evidence for %s', (entityType) => {
  render(<MemoryRouter><CooperationAssessmentPanel directory={[]} assessment={{
    entity_type: entityType, method_version: 'cooperation-louvain-v1', library_version: '3.6.1', input_hash: 'frozen-input', parameters: {},
    scope_publication_ids: ['paper'], missing_author_publication_ids: [], node_count: 2, edge_count: 1,
    isolated_node_count: 0, connected_component_count: 1, modularity: 0,
    sensitivity: [], warnings: [], publications: [{ publication_id: 'paper', title: '可核对的合作论文' }],
    communities: [{community_id: 7, member_ids: ['a', 'b'], publication_ids: ['paper'],
      internal_edge_count: 1, external_edge_count: 0, density: 1, internal_weight_share: 1,
      connected_components: 1, seed_stability: 1,
      centers: [{person_id:'a', roles:['簇内桥梁'], internal_degree:1, internal_strength:1, betweenness:.5}],
      metrics:[{code:'incites.cnci',label:'CNCI',publication_ids:['paper'],missing_publication_ids:[], count:1,mean:0,median:0,minimum:0,maximum:0,reference:1,above_reference_count:0}],
      quartiles:{jcr:{publication_ids:[],missing_publication_ids:['paper'],count:0,paper_equivalents:{Q1:0,Q2:0,Q3:0,Q4:0},shares:{Q1:null,Q2:null,Q3:null,Q4:null}}}}],
  }} /></MemoryRouter>);
  expect(screen.getByRole('heading', {name: '合作结构分析'})).toBeInTheDocument();
  expect(screen.getByText('簇 8')).toBeInTheDocument();
  fireEvent.click(screen.getByText('成员与论文'));
  expect(screen.getByRole('link', {name: '可核对的合作论文'})).toHaveAttribute('href', '/outputs/paper');
  expect(screen.getByRole('button', {name: '导出计算依据'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name:'查看全部指标'}));
  expect(screen.getByRole('heading', {name:'期刊与论文影响指标'})).toBeInTheDocument();
  expect(screen.getByText('高于 1：0 篇（0.0%）')).toBeInTheDocument();
  expect(screen.getAllByText('缺少同年分区')).toHaveLength(4);
  expect(screen.queryByRole('columnheader', {name:'介数中心性'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name:'查看中心依据'}));
  expect(screen.getByRole('columnheader', {name:'介数中心性'})).toBeInTheDocument();
  expect(screen.getByRole('heading', {name: entityType === 'organization' ? '中心机构候选及依据' : '中心学者候选及依据'})).toBeInTheDocument();
  expect(screen.queryByRole('heading', {name:'期刊与论文影响指标'})).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', {name:'同年分区构成'})).not.toBeInTheDocument();
});


it('zooms SVG coordinates rather than scaling a composited surface', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('tab', { name: '学者合作' }));
  await screen.findByRole('heading', { name: '关联人员目录' });
  const svg = screen.getByRole('img', { name: '合作关系图' });
  const before = svg.getAttribute('viewBox')?.split(' ').map(Number) ?? [];
  fireEvent.click(screen.getByRole('button', { name: '放大合作图谱' }));
  const after = svg.getAttribute('viewBox')?.split(' ').map(Number) ?? [];
  expect(after[2]).toBeCloseTo((before[2] ?? 0) / 1.1);
  expect(svg.parentElement?.style.transform).toBe('');
  fireEvent.click(screen.getByRole('button', { name: '重置合作图谱位置' }));
  expect(svg.getAttribute('viewBox')?.split(' ').map(Number)).toEqual(before);
});

it('distinguishes visible cluster nodes from full members and opens the complete roster', async () => {
  const response = await getScholarGraphAnalyticsView({});
  vi.mocked(getScholarGraphAnalyticsView).mockResolvedValueOnce(response).mockResolvedValueOnce({ ...response, people_collaboration: {
    ...requiredValue(response.people_collaboration),
    nodes: requiredValue(response.people_collaboration).nodes.map((n) => ({ ...n, community_id: 0 })),
    assessment: { method_version: 'v1', library_version: '3.6.1', input_hash: 'test', parameters: {},
      scope_publication_ids: [], missing_author_publication_ids: [], node_count: 3, edge_count: 1,
      isolated_node_count: 0, connected_component_count: 1, modularity: 0, sensitivity: [], publications: [], warnings: [],
      communities: [{community_id: 0, member_ids: ['left', 'right', 'outside'], publication_ids: [], internal_edge_count: 1,
        external_edge_count: 0, density: 1, internal_weight_share: 1, connected_components: 1, seed_stability: 1,
      centers: [{person_id:'a', roles:['簇内桥梁'], internal_degree:1, internal_strength:1, betweenness:.5}],
      metrics:[{code:'incites.cnci',label:'CNCI',publication_ids:['paper'],missing_publication_ids:[], count:1,mean:0,median:0,minimum:0,maximum:0,reference:1,above_reference_count:0}],
      quartiles:{jcr:{publication_ids:[],missing_publication_ids:['paper'],count:0,paper_equivalents:{Q1:0,Q2:0,Q3:0,Q4:0},shares:{Q1:null,Q2:null,Q3:null,Q4:null}}}}],
    },
  }});
  renderPage();
  fireEvent.click(await screen.findByRole('tab', { name: '学者合作' }));
  await screen.findByRole('heading', { name: '关联人员目录' });
  expect(screen.getByText('簇 1 · 当前显示 2 人 / 全部 3 人')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: '查看簇 1 全部成员'}));
  const dialog = screen.getByRole('dialog', {name: '簇 1 · 全部成员'});
  expect(within(dialog).getByRole('link', {name: '图外学者'})).toHaveAttribute('href', '/scholars/outside');
  expect(within(dialog).getByText('当前图中未显示')).toBeInTheDocument();
});

it('aligns institution exploration controls without scholar-only filters', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('tab', {name:'机构合作'}));
  await screen.findByRole('combobox', {name: '探索机构的一度合作'});
  expect(screen.getByRole('combobox', {name:'探索机构的一度合作'})).toBeInTheDocument();
  expect(screen.queryByRole('checkbox', {name:'包含外部合作者'})).not.toBeInTheDocument();
  expect(screen.getByRole('spinbutton', {name:'最多显示连线'})).toBeInTheDocument();
  expect(screen.getByRole('spinbutton', {name:'合作簇最少机构数'})).toBeInTheDocument();
  expect(screen.getByRole('heading', {name:'关联机构目录'})).toBeInTheDocument();
  expect(screen.getByRole('link', {name:'图外学者'})).toHaveAttribute('href','/institutions/outside');
});

it('applies institution granularity and disjoint internal groups explicitly', async () => {
  const { InstitutionGranularityControls, defaultInstitutionSettings } = await import('./InstitutionGranularityControls');
  const apply=vi.fn();
  render(<MemoryRouter><InstitutionGranularityControls options={[
    {id:'r',name:'学校A',root_id:'r',level:1},
    {id:'other',name:'其他大学',root_id:'other',level:1},
    {id:'a',name:'学院A',root_id:'r',level:2},
    {id:'b',name:'学院B',root_id:'r',level:2},
  ]} applied={defaultInstitutionSettings} onApply={apply} context={{mapped_publication_count:5}}/></MemoryRouter>);
  fireEvent.click(screen.getByRole('combobox',{name:'分析模式'}));
  fireEvent.click(screen.getByRole('option',{name:'校内单位合作'}));
  expect(screen.getByRole('button',{name:'应用配置并重新分析'})).toBeDisabled();
  fireEvent.change(screen.getByRole('combobox',{name:'校内分析范围'}),{target:{value:'校a'}});
  expect(screen.queryByRole('option',{name:'其他大学'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('option',{name:'学校A'}));
  fireEvent.change(screen.getByRole('textbox',{name:'组合名称'}),{target:{value:'研究组合'}});
  fireEvent.click(screen.getByRole('combobox',{name:/组合成员/}));
  fireEvent.click(screen.getByRole('option',{name:'学院A'}));
  expect(screen.getByRole('button',{name:'应用配置并重新分析'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'添加组合'}));
  expect(screen.getByRole('button',{name:'应用配置并重新分析'})).toBeEnabled();
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'应用配置并重新分析'}));
  expect(apply).toHaveBeenLastCalledWith({mode:'internal',root_ids:['r'],groups:[{name:'研究组合',member_ids:['a']}]});
  fireEvent.click(screen.getByRole('button',{name:'移除组合'}));
  fireEvent.click(screen.getByRole('button',{name:'应用配置并重新分析'}));
  expect(apply).toHaveBeenLastCalledWith({mode:'internal',root_ids:['r'],groups:[]});
});

it.each(['root','expanded'] as const)('supports custom institution groups in %s mode', async mode => {
  const {InstitutionGranularityControls}=await import('./InstitutionGranularityControls');
  const apply=vi.fn();
  const options=[{id:'r',name:'学校A',root_id:'r',level:1},{id:'a',name:'学院A',root_id:'r',level:2},
    {id:'b',name:'学校B',root_id:'b',level:1},{id:'bb',name:'学院B',root_id:'b',level:2}];
  render(<MemoryRouter><InstitutionGranularityControls options={options} applied={{mode,root_ids:mode==='expanded'?['r']:[],groups:[]}} onApply={apply} context={{}}/></MemoryRouter>);
  fireEvent.change(screen.getByRole('textbox',{name:'组合名称'}),{target:{value:'跨机构组合'}});
  fireEvent.click(screen.getByRole('combobox',{name:/组合成员/}));
  expect(screen.queryByRole('option',{name:'学院B'})).not.toBeInTheDocument();
  if(mode==='expanded') expect(screen.queryByRole('option',{name:'学校A'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('option',{name:mode==='root'?'学校A':'学校A / 学院A'}));
  fireEvent.click(screen.getByRole('option',{name:'学校B'}));
  expect(screen.getByRole('button',{name:'应用配置并重新分析'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'添加组合'}));
  expect(screen.getByRole('button',{name:'应用配置并重新分析'})).toBeEnabled();
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'应用配置并重新分析'}));
  expect(apply).toHaveBeenLastCalledWith({mode,root_ids:mode==='expanded'?['r']:[],groups:[{name:'跨机构组合',member_ids:[mode==='root'?'r':'a','b']}]});
});

it('restores every analysis tab and section by stable URL names',()=>{
  analysisTabs.forEach((tab,index)=>expect(analysisPosition(new URLSearchParams({tab})).tab).toBe(index));
  analysisSections.forEach((section,index)=>expect(analysisPosition(new URLSearchParams({section})).section).toBe(index));
  expect(analysisPosition(new URLSearchParams('tab=invalid&section=invalid'))).toEqual({tab:0,section:0});
});

function NavigationProbe() { const location=useLocation(), navigate=useNavigate(); return <><output aria-label="当前地址">{location.search}</output><button onClick={()=>{ void navigate(-1); }}>测试后退</button></>; }
it('updates stale discipline URL when switching to scholars and follows browser history',async()=>{
  render(<MemoryRouter initialEntries={['/graph-analytics?tab=disciplines&ui=keep']}><ScholarGraphAnalyticsPage/><NavigationProbe/></MemoryRouter>);
  fireEvent.click(screen.getByRole('tab',{name:'学者合作'}));
  expect(screen.getByLabelText('当前地址')).toHaveTextContent('tab=people_collaboration');
  expect(screen.getByLabelText('当前地址')).toHaveTextContent('ui=keep');
  fireEvent.click(screen.getByRole('button',{name:'测试后退'}));
  expect(await screen.findByRole('tab',{name:'学科方向',selected:true})).toBeInTheDocument();
});
function SessionProbe() { const [n,setN]=useSessionState('test',1); return <button onClick={()=>setN(n+1)}>值{n}</button>; }
it('restores session settings after remount and tolerates broken stored JSON',()=>{
  const first=render(<SessionProbe/>); fireEvent.click(screen.getByRole('button',{name:'值1'})); first.unmount();
  const second=render(<SessionProbe/>); expect(screen.getByRole('button',{name:'值2'})).toBeInTheDocument(); second.unmount();
  sessionStorage.setItem('smartlib.analytics.session.v1.test','broken');
  render(<SessionProbe/>); expect(screen.getByRole('button',{name:'值1'})).toBeInTheDocument();
});
