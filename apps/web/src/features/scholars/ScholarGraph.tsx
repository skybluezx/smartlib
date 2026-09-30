import { Notice as InlineNotification } from '../../shared/components/Notice';
import { useDeferredValue, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ResearchProfilePanel } from '../catalog/ResearchProfilePanel';
import { OutputAffiliations } from './OutputAffiliations';
import {
  ArrowLeft, ArrowRight, ChartRelationship, Copy, Document,
  Information, Search as SearchIcon,
} from '@carbon/icons-react';
import {
  Breadcrumb, BreadcrumbItem, Button, Dropdown, InlineLoading, 
  Pagination, Search, SkeletonText, Tab, TabList, TabPanel, TabPanels, Tabs, Tag,
} from '@carbon/react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import type { GraphEdge, GraphNode, NeighborhoodResult, ScholarEvidenceBundle, ScholarEvidenceItem, ScholarProfile, ScholarSummary } from '../../generated/smartlib-api';
import { getScholarEvidenceView, getScholarNetworkView, getScholarProfileView, searchScholarDirectory } from '../../shared/api/smartlib';
import { InteractiveRelationshipGraph } from '../graph/InteractiveRelationshipGraph';

const PAGE_SIZES = [10, 20, 50];
const sortOptions = [
  { id: 'name', label: '姓名顺序' },
  { id: 'publications', label: '关联成果数' },
  { id: 'updated', label: '最近更新' },
];
const objectTypeLabels: Record<string, string> = {
  person: '学者', publication: '论文', organization: '机构', department: '院系', discipline: '学科',
  funding_program: '资助计划', project: '项目', journal: '期刊', concept: '研究主题', dataset: '数据集', patent: '专利', resource: '资源',
};
const predicateLabels: Record<string, string> = {
  'person.authored': '发表', 'person.affiliated_with': '论文署名关联', 'person.authoritatively_affiliated_with': '人事登记机构',
  'person.member_of_discipline': '所属学科', 'person.researches': '研究', 'person.participates_in': '参与',
  'person.leads_project': '主持', 'person.collaborates_with': '合作',
  'person.awardee_of': '获批人', 'project.has_representative_publication': '代表性论著',
  'project.under_program': '属于资助计划',
};

function graphRelationLabel(edge: GraphEdge) {
  const roles = Array.isArray(edge.attributes?.roles)
    ? edge.attributes.roles.filter((role): role is string => typeof role === 'string' && role !== 'author')
    : [];
  if (edge.predicate === 'person.authored' && roles.length) {
    const labels: Record<string, string> = { first_author: '第一作者', co_first_author: '共同第一作者', corresponding_author: '通讯作者', co_corresponding_author: '共同通讯作者' };
    return roles.map((role) => labels[role] ?? role).join('、');
  }
  return predicateLabels[edge.predicate] ?? edge.predicate;
}

function formatDate(value: string | null | undefined) {
  if (!value) return '尚未记录';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN');
}

function statusLabel(value: string | null | undefined) {
  return value === 'approved' ? '已核验' : value === 'rejected' ? '已驳回' : '待核验';
}

function missing(value: string | null | undefined, fallback = '尚未收录') {
  const normalized = value?.trim();
  return normalized && normalized.length > 0 ? normalized : fallback;
}

export function ScholarGraph() {
  const { scholarId } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  useEffect(() => {
    const objectId = params.get('object');
    if (!scholarId && objectId) void navigate(`/scholars/${encodeURIComponent(objectId)}`, { replace: true });
  }, [navigate, params, scholarId]);
  return scholarId ? <ScholarDetail scholarId={scholarId} /> : <ScholarDirectory />;
}

function ScholarDirectory() {
  const navigate = useNavigate();
  const location = useLocation();
  const [urlParams, setUrlParams] = useSearchParams();
  const query = urlParams.get('q') ?? '';
  const deferredQuery = useDeferredValue(query.trim().toLocaleLowerCase());
  const department = urlParams.get('department') ?? 'all';
  const outputOrganization = urlParams.get('outputOrganization') ?? 'all';
  const discipline = urlParams.get('discipline') ?? 'all';
  const direction = urlParams.get('direction') ?? 'all';
  const sort = urlParams.get('sort') ?? 'name';
  const parsedPage = Number(urlParams.get('page') ?? '1');
  const parsedPageSize = Number(urlParams.get('pageSize') ?? '10');
  const page = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1;
  const pageSize = PAGE_SIZES.includes(parsedPageSize) ? parsedPageSize : 10;
  const updateDirectory = (changes: Record<string, string | number | null>) => {
    const next = new URLSearchParams(urlParams);
    for (const [key, value] of Object.entries(changes)) {
      const isDefault = value === null || value === '' || value === 'all' || (key === 'sort' && value === 'name') || (key === 'page' && value === 1) || (key === 'pageSize' && value === 10);
      if (isDefault) next.delete(key); else next.set(key, String(value));
    }
    setUrlParams(next, { replace: true });
  };
  const directory = useQuery({ queryKey: ['scholars', 'directory', 'all'], queryFn: ({ signal }) => searchScholarDirectory({ limit: 2000 }, signal), staleTime: 60_000 });
  const scholars = useMemo(() => directory.data ?? [], [directory.data]);
  const options = useMemo(() => ({
    departments: Array.from(new Set(scholars.flatMap((item) => item.authoritative_organizations ?? []))).sort(),
    outputOrganizations: Array.from(new Set(scholars.flatMap((item) => item.output_organizations ?? []))).sort(),
    disciplines: Array.from(new Set(scholars.map((item) => item.discipline).filter(Boolean) as string[])).sort(),
    directions: Array.from(new Set(scholars.map((item) => item.primary_direction).filter(Boolean) as string[])).sort(),
  }), [scholars]);
  const filtered = useMemo(() => scholars.filter((item) => {
    const haystack = [item.canonical_name, item.title, item.department, ...(item.output_organizations ?? []), item.discipline, item.primary_direction].filter(Boolean).join(' ').toLocaleLowerCase();
    return (!deferredQuery || haystack.includes(deferredQuery))
      && (department === 'all' || (item.authoritative_organizations ?? []).includes(department))
      && (outputOrganization === 'all' || (item.output_organizations ?? []).includes(outputOrganization))
      && (discipline === 'all' || item.discipline === discipline)
      && (direction === 'all' || item.primary_direction === direction);
  }).sort((left, right) => {
    if (sort === 'publications') return right.metrics.publications - left.metrics.publications || left.canonical_name.localeCompare(right.canonical_name, 'zh-CN');
    if (sort === 'updated') return new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime();
    return left.canonical_name.localeCompare(right.canonical_name, 'zh-CN');
  }), [department, outputOrganization, deferredQuery, direction, discipline, scholars, sort]);
  const safePage = Math.min(page, Math.max(1, Math.ceil(filtered.length / pageSize)));
  useEffect(() => {
    if (safePage !== page) updateDirectory({ page: safePage });
  // The URL is the source of truth; normalize only when the filtered result count changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safePage, page]);
  const pageRows = filtered.slice((safePage - 1) * pageSize, safePage * pageSize);
  const clearFilters = () => setUrlParams({}, { replace: true });
  const knownAffiliation = scholars.filter((item) => item.department).length;
  const knownDirections = scholars.filter((item) => item.primary_direction).length;
  const approvedPublications = scholars.reduce((sum, item) => sum + item.metrics.publications, 0);

  return <div className="sg-scholars-page sg-scholar-directory-page">
    <header className="sg-page-heading"><div><h1>学者目录</h1><span>浏览当前成果关联学者（含校外作者），查看成果与关系网络。</span></div><Button kind="secondary" renderIcon={SearchIcon} onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))}>全局搜索</Button></header>
    {directory.isSuccess && <section className="sg-directory-metrics" aria-label="学者目录统计">
      <Metric label="已登记学者" value={scholars.length} note="当前目录记录" />
      <Metric label="已有人事登记机构" value={knownAffiliation} note={`当前有效；占目录 ${scholars.length ? Math.round(knownAffiliation / scholars.length * 100) : 0}%`} />
      <Metric label="已有成果研究方向" value={knownDirections} note={`占目录 ${scholars.length ? Math.round(knownDirections / scholars.length * 100) : 0}%`} />
      <Metric label="成果关联篇次" value={approvedPublications} note="同一论文可关联多位学者" />
    </section>}
    <section className="sg-directory-toolbar" aria-label="学者目录筛选">
      <Search size="lg" labelText="搜索学者目录" placeholder="姓名、机构、学科或研究方向" value={query} onChange={(event) => updateDirectory({ q: event.target.value, page: 1 })} />
      <FilterDropdown id="department-filter" title="人事登记机构" value={department} values={options.departments} onChange={(value) => updateDirectory({ department: value, page: 1 })} />
      <FilterDropdown id="output-organization-filter" title="成果署名机构" value={outputOrganization} values={options.outputOrganizations} onChange={(value) => updateDirectory({ outputOrganization: value, page: 1 })} />
      <FilterDropdown id="discipline-filter" title="学科" value={discipline} values={options.disciplines} onChange={(value) => updateDirectory({ discipline: value, page: 1 })} />
      <FilterDropdown id="direction-filter" title="研究方向" value={direction} values={options.directions} onChange={(value) => updateDirectory({ direction: value, page: 1 })} />
      <Dropdown id="scholar-sort" label="排序方式" titleText="排序" items={sortOptions} itemToString={(item) => item?.label ?? ''} selectedItem={sortOptions.find((item) => item.id === sort) ?? sortOptions[0]} onChange={({ selectedItem }) => { if (selectedItem) updateDirectory({ sort: selectedItem.id, page: 1 }); }} />
      {(query || department !== 'all' || outputOrganization !== 'all' || discipline !== 'all' || direction !== 'all' || sort !== 'name') && <Button kind="ghost" onClick={clearFilters}>清除条件</Button>}
    </section>
    {directory.isPending && <DirectoryLoading />}
    {directory.isError && <section className="sg-state-section"><InlineNotification kind="error" title="学者目录暂不可用" subtitle={`${directory.error.message}。其他页面仍可使用。`} actionButtonLabel="重试" onActionButtonClick={() => void directory.refetch()} /></section>}
    {directory.isSuccess && filtered.length === 0 && <EmptyState icon={<SearchIcon size={32} />} title="没有符合条件的学者" text="请调整关键词或清除筛选条件。" action={<Button kind="tertiary" onClick={clearFilters}>清除筛选</Button>} />}
    {directory.isSuccess && filtered.length > 0 && <section className="sg-directory-results">
      <div className="sg-results-summary"><strong>{filtered.length}</strong><span>位学者</span><small>共登记 {scholars.length} 位</small></div>
      <div className="sg-scholar-table" role="table" aria-label="学者目录">
        <div className="sg-scholar-table-head" role="row"><span>学者</span><span>机构与职称</span><span>学科与研究方向</span><span>成果概况</span><span>数据更新</span><span /></div>
        {pageRows.map((scholar) => <button role="row" key={scholar.scholar_id} onClick={() => void navigate(`/scholars/${encodeURIComponent(scholar.scholar_id)}`, { state: { from: `${location.pathname}${location.search}` } })}>
          <span className="sg-person-cell"><b className="sg-avatar">{scholar.initials}</b><span><strong>{scholar.canonical_name}</strong><code>{scholar.scholar_id}</code></span></span>
          <span><strong>{missing(scholar.department)}</strong><small>{missing(scholar.title, '职称尚未收录')}</small></span>
          <span><strong>{missing(scholar.discipline)}</strong><small>{missing(scholar.primary_direction, '研究方向尚未收录')}</small></span>
          <span><strong>{scholar.metrics.publications} 篇论文</strong><small>{scholar.metrics.projects} 个项目 · {scholar.metrics.collaborators} 位合作者</small></span>
          <span><strong>{formatDate(scholar.updated_at)}</strong><small>{scholar.synthetic ? '演示记录' : '真实业务记录'}</small></span>
          <ArrowRight size={18} aria-label="查看学者" />
        </button>)}
      </div>
      <Pagination page={safePage} pageSize={pageSize} pageSizes={PAGE_SIZES} totalItems={filtered.length} itemsPerPageText="每页" itemRangeText={(min, max, total) => `${min}–${max} / ${total}`} pageRangeText={(_, total) => `共 ${total} 页`} onChange={({ page: nextPage, pageSize: nextSize }) => updateDirectory({ page: nextPage, pageSize: nextSize })} />
    </section>}
  </div>;
}

function Metric({ label, value, note }: { label: string; value: number; note: string }) {
  return <article><span>{label}</span><strong>{value}</strong><small>{note}</small></article>;
}

function FilterDropdown({ id, title, value, values, onChange }: { id: string; title: string; value: string; values: string[]; onChange: (value: string) => void }) {
  const items = [{ id: 'all', label: `全部${title}` }, ...values.map((item) => ({ id: item, label: item }))];
  return <Dropdown id={id} label={title} titleText={title} items={items} itemToString={(item) => item?.label ?? ''} selectedItem={items.find((item) => item.id === value) ?? items[0]} onChange={({ selectedItem }) => onChange(selectedItem?.id ?? 'all')} />;
}

function ScholarDetail({ scholarId }: { scholarId: string }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const requestedView = params.get('view') ?? 'overview';
  const views = ['overview', 'publications', 'network'];
  const selectedIndex = Math.max(0, views.indexOf(requestedView));
  const profile = useQuery({ queryKey: ['scholars', 'profile', scholarId], queryFn: ({ signal }) => getScholarProfileView(scholarId, signal) });
  const network = useQuery({ queryKey: ['scholars', 'network', scholarId], queryFn: ({ signal }) => getScholarNetworkView(scholarId, signal) });
  const evidence = useQuery({ queryKey: ['scholars', 'evidence', scholarId], queryFn: ({ signal }) => getScholarEvidenceView(scholarId, signal), enabled: profile.isSuccess });
  const routeState = location.state as { from?: unknown } | null;
  const backTarget = typeof routeState?.from === 'string' ? routeState.from : '/scholars';

  if (profile.isPending) return <DetailLoading />;
  if (profile.isError) return <div className="sg-scholars-page"><Breadcrumb noTrailingSlash><BreadcrumbItem><Link to="/scholars">学者目录</Link></BreadcrumbItem><BreadcrumbItem isCurrentPage>加载失败</BreadcrumbItem></Breadcrumb><InlineNotification kind="error" title="学者详情暂不可用" subtitle={profile.error.message} actionButtonLabel="重试" onActionButtonClick={() => void profile.refetch()} /></div>;
  const data = profile.data;
  const visiblePublications = publicationRecords(data, evidence.data);
  const networkCounts = data.overview?.counts ?? {};

  return <div className="sg-scholars-page sg-scholar-detail-page">
    <button className="sg-back-link" onClick={() => void navigate(backTarget)}><ArrowLeft />返回学者目录</button>
    <section className="sg-profile-header">
      <div className="sg-avatar sg-avatar-large">{data.summary.initials}</div>
      <div className="sg-profile-title"><span>学者档案</span><h1>{data.summary.canonical_name}</h1><p>{missing(data.summary.title, '职称尚未收录')} · {missing(data.summary.department, '所属机构尚未收录')}</p><div><Tag type="blue">{data.summary.synthetic ? '演示数据' : '真实业务记录'}</Tag><code>{data.summary.scholar_id}</code></div></div>
      <dl><div><dt>数据更新</dt><dd>{formatDate(data.summary.updated_at)}</dd></div><div><dt>档案版本</dt><dd>{data.summary.object_version}</dd></div><div><dt>数据来源</dt><dd>{data.summary.dataset_version ?? '尚未标注'}</dd></div></dl>
      <Button kind="tertiary" onClick={() => setEvidenceOpen(true)}>查看数据来源</Button>
    </section>
    <Tabs selectedIndex={selectedIndex} onChange={({ selectedIndex: index }) => { const next = new URLSearchParams(params); if (index === 0) next.delete('view'); else next.set('view', views[index] ?? 'overview'); setParams(next, { replace: true }); }}>
      <TabList aria-label="学者详情视图"><Tab>学者概览</Tab><Tab>论文成果 <span className="sg-tab-count">{data.overview ? visiblePublications.length : '—'}</span></Tab><Tab>关系网络 <span className="sg-tab-count">{network.data?.edges.length ?? 0}{network.data?.truncated ? '+' : ''}</span></Tab></TabList>
      <TabPanels>
        <TabPanel><ProfileOverview profile={data} counts={networkCounts} networkPending={false} /></TabPanel>
        <TabPanel><PublicationPanel publications={visiblePublications} networkPending={false} networkError={!data.overview ? new Error('完整论文数据暂不可用') : null} evidencePending={evidence.isPending} onRetry={() => { void profile.refetch(); void evidence.refetch(); }} /></TabPanel>
        <TabPanel><NetworkPanel network={network.data} pending={network.isPending} error={network.isError ? network.error : null} onRetry={() => void network.refetch()} /></TabPanel>
      </TabPanels>
    </Tabs>
    {evidenceOpen && <EvidenceDrawer scholar={data.summary} evidence={evidence.data} pending={evidence.isPending} error={evidence.isError ? evidence.error : null} onRetry={() => void evidence.refetch()} onClose={() => setEvidenceOpen(false)} />}
  </div>;
}

function ProfileOverview({ profile, counts, networkPending }: { profile: ScholarProfile; counts: Record<string, number>; networkPending: boolean }) {
  const description = profile.description?.trim();
  const showDescription = description && description !== '论文署名经用户确认的独立作者；不代表本校人事归属。';
  return <div className="sg-detail-grid">
    <div className="sg-detail-main">
      <section className="sg-detail-section"><header><h2>学术身份</h2><p>业务记录按来源分类；成果署名不代表当前人事归属</p></header><dl className="sg-identity-grid"><div><dt>当前人事机构</dt><dd>{missing(profile.summary.department, '尚无当前有效的人事归属记录')}</dd></div><div><dt>职称</dt><dd>{missing(profile.summary.title)}</dd></div><div><dt>所属学科</dt><dd>{missing(profile.summary.discipline)}</dd></div><div><dt>主要研究方向</dt><dd>{missing(profile.summary.primary_direction)}</dd></div></dl>{showDescription && <p className="sg-profile-description">{description}</p>}</section>
      {(['authoritative', 'output'] as const).map((category) => <section className="sg-detail-section" key={category}>
        <header><h2>{category === 'authoritative' ? '人事登记机构' : '成果署名机构'}</h2><p>{category === 'authoritative' ? '保留来源有效期，不用论文署名补填人事信息。' : '逐篇保留机构快照；不推断当前、主要或兼职任职。'}</p></header>
        {category === 'output' ? <OutputAffiliations items={profile.affiliations ?? []} /> : (profile.affiliations ?? []).filter((item) => item.category === category).map((item) => <article className="sg-affiliation-record" key={item.relation_id}>
          <h3>{item.organization_name}</h3>
          {<p>{item.is_current ? '当前有效' : '非当前有效'} · 起始：{item.valid_from ?? '来源未提供'} · 截止：{item.valid_to ?? '来源未提供'}</p>}
          {item.context_object_id && <p>来源成果：<Link to={`/outputs/${item.context_object_id}`}>{item.context_title ?? item.context_object_id}</Link></p>}
          <p>机构原文：{item.raw_affiliation ?? '见下方来源证据'}</p>
          <details><summary>查看 {(item.evidence ?? []).length} 条来源依据</summary>{(item.evidence ?? []).map((evidence) => <div key={evidence.evidence_id}><p>{evidence.source_name ?? '来源未标注'} · {evidence.citation}</p><p>{evidence.excerpt ?? ''}</p>{evidence.page_number != null && <p>PDF 页码：{evidence.page_number}</p>}</div>)}</details>
        </article>)}
        {!(profile.affiliations ?? []).some((item) => item.category === category) && <EmptyInline text={category === 'authoritative' ? '尚未收录人事登记机构；论文机构不会自动填入此处。' : '尚未收录成果署名机构。'} />}
      </section>)}
      <section className="sg-detail-section"><header><h2>研究方向</h2><p>展示登记研究方向及其来源</p></header>{profile.research_directions.length ? <div className="sg-direction-list">{profile.research_directions.map((item) => <div key={item.relation_id}><strong>{item.canonical_name}</strong><small>{item.evidence_count} 条来源依据</small></div>)}</div> : <EmptyInline text="尚未形成可展示的研究方向关系。" />}</section>
      <ResearchProfilePanel objectId={profile.summary.object_id} title="成果研究方向" />
    </div>
    <aside>
      <section className="sg-detail-section"><header><h2>成果与关系概况</h2><p>按当前收录数据完整汇总</p></header>{networkPending ? <InlineLoading description="正在读取关系概况" /> : !profile.overview ? <p role="alert">统计暂不可用，请刷新重试。</p> : <div className="sg-profile-metrics"><Metric label="论文" value={counts.publication ?? 0} note="关联论文去重" /><Metric label="项目" value={counts.project ?? 0} note="主持、参与或获批项目去重" /><Metric label="合作学者" value={counts.person ?? 0} note="共同论文作者去重，不含本人" /><Metric label="研究主题" value={counts.concept ?? 0} note="关联论文的主题去重" /></div>}</section>
      <section className="sg-detail-section"><header><h2>可信说明</h2></header><div className="sg-trust-note"><Information /><p>本页展示来源和缺失信息。统计不代表评价、排名或影响力判断。</p></div></section>
    </aside>
  </div>;
}

interface PublicationRecord { node: Pick<GraphNode, 'object_id' | 'canonical_name' | 'description'>; edge?: { review_state: string } | undefined; evidenceCount: number; year?: number | null | undefined; doi?: string | undefined; pmid?: string | undefined; pmcid?: string | undefined; sources: string[] }

function publicationRecords(profile: ScholarProfile, evidence?: ScholarEvidenceBundle): PublicationRecord[] {
  return (profile.overview?.papers ?? []).map((node) => {
    const edge = { review_state: node.review_state };
    const items = (evidence?.items ?? []).filter((item) => item.object_id === node.object_id);
    const text = items.map((item) => `${item.citation} ${item.excerpt ?? ''}`).join(' ');
    const doi = /10\.\d{4,9}\/[-._;()/:A-Z0-9]+/i.exec(text)?.[0]?.replace(/[.,;)]$/, '');
    const pmid = /PMID\s*[: ]\s*(\d+)/i.exec(text)?.[1];
    const pmcid = /\bPMC\d+\b/i.exec(text)?.[0]?.toUpperCase();
    return { node, edge, evidenceCount: node.evidence_count, year: node.year, doi: node.doi ?? doi, pmid: node.pmid ?? pmid, pmcid: node.pmcid ?? pmcid, sources: Array.from(new Set(items.map((item) => item.source_name).filter(Boolean) as string[])) };
  }).sort((a, b) => a.node.canonical_name.localeCompare(b.node.canonical_name));
}

function PublicationPanel({ publications, networkPending, networkError, evidencePending, onRetry }: { publications: PublicationRecord[]; networkPending: boolean; networkError: Error | null; evidencePending: boolean; onRetry: () => void }) {
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('title');
  const rows = publications.filter((item) => `${item.node.canonical_name} ${item.doi ?? ''} ${item.pmid ?? ''} ${item.pmcid ?? ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())).sort((a, b) => sort === 'year' ? (b.year ?? -1) - (a.year ?? -1) : a.node.canonical_name.localeCompare(b.node.canonical_name));
  if (networkPending) return <section className="sg-tab-loading"><InlineLoading description="正在读取论文成果关系" /></section>;
  if (networkError) return <InlineNotification kind="error" title="论文关系暂不可用" subtitle={`${networkError.message}。学者基本档案仍可查看。`} actionButtonLabel="重试" onActionButtonClick={onRetry} />;
  return <section className="sg-publications-panel">
    <div className="sg-section-heading"><div><h2>论文成果</h2></div>{evidencePending && <InlineLoading description="正在补充标识符" />}</div>
    <div className="sg-publication-toolbar"><Search labelText="搜索该学者论文" placeholder="题名、DOI、PMID 或 PMCID" value={query} onChange={(event) => setQuery(event.target.value)} /><Dropdown id="publication-sort" label="排序" titleText="排序" items={[{ id: 'title', label: '题名' }, { id: 'year', label: '年份从新到旧' }]} itemToString={(item) => item?.label ?? ''} selectedItem={sort === 'title' ? { id: 'title', label: '题名' } : { id: 'year', label: '年份从新到旧' }} onChange={({ selectedItem }) => selectedItem && setSort(selectedItem.id)} /></div>
    {!publications.length && <EmptyState icon={<Document size={32} />} title="暂无可展示论文" text="当前没有从关系服务返回论文对象；这不等于该学者没有发表论文。" />}
    {publications.length > 0 && rows.length === 0 && <EmptyState icon={<SearchIcon size={28} />} title="没有匹配论文" text="请调整当前页的搜索关键词。" />}
    <div className="sg-publication-list">{rows.map((publication, index) => <article key={publication.node.object_id}>
      <div className="sg-publication-index">{String(index + 1).padStart(2, '0')}</div><div className="sg-publication-main"><div><span>{publication.evidenceCount} 条关系依据</span></div><h3><Link to={`/outputs/${publication.node.object_id}`}>{publication.node.canonical_name}</Link></h3><p>{publication.node.description ?? '论文摘要尚未进入当前学者视图。'}</p><div className="sg-identifiers"><Identifier label="DOI" value={publication.doi} href={publication.doi ? `https://doi.org/${publication.doi}` : undefined} /><Identifier label="PMID" value={publication.pmid} href={publication.pmid ? `https://pubmed.ncbi.nlm.nih.gov/${publication.pmid}/` : undefined} /><Identifier label="PMCID" value={publication.pmcid} href={publication.pmcid ? `https://pmc.ncbi.nlm.nih.gov/articles/${publication.pmcid}/` : undefined} /></div><footer><span>来源：{publication.sources.length ? publication.sources.join('、') : '关系记录，详细来源待载入'}</span><span>发表年份：{publication.year ?? '尚未收录'}</span></footer></div>
    </article>)}</div>
  </section>;
}

function Identifier({ label, value, href }: { label: string; value?: string | undefined; href?: string | undefined }) {
  const copy = () => { if (value) void navigator.clipboard.writeText(value); };
  return <div><span>{label}</span>{href && value ? <a href={href} target="_blank" rel="noreferrer"><code>{value}</code></a> : <code>尚未收录</code>}<button disabled={!value} aria-label={`复制 ${label}`} onClick={copy}><Copy size={14} /></button></div>;
}

function NetworkPanel({ network, pending, error, onRetry }: { network?: NeighborhoodResult | undefined; pending: boolean; error: Error | null; onRetry: () => void }) {
  if (pending) return <section className="sg-tab-loading"><InlineLoading description="正在读取关系网络" /></section>;
  if (error) return <InlineNotification kind="error" title="关系网络暂不可用" subtitle={`${error.message}。学者档案和已缓存成果仍可查看。`} actionButtonLabel="重试" onActionButtonClick={onRetry} />;
  if (!network || network.edges.length === 0) return <EmptyState icon={<ChartRelationship size={32} />} title="暂无关系数据" text="当前查询范围内没有可展示关系。" action={<Button kind="tertiary" onClick={onRetry}>重新查询</Button>} />;
  const root = network.nodes.find((node) => node.object_id === network.root_object_id);
  return <InteractiveRelationshipGraph
    key={`${network.root_object_id}-${network.projection_version}-${network.nodes.length}-${network.edges.length}`}
    initialNetwork={network} rootName={root?.canonical_name ?? '学者'} title="学术关系网络"
    description="从当前学者开始逐节点探索一度关系，不一次加载全库图谱。"
    sectionClassName="sg-network-panel" filterId="scholar-network-type" typeLabels={objectTypeLabels}
    relationLabel={graphRelationLabel} reviewLabel={statusLabel}
  />;
}

function EvidenceDrawer({ scholar, evidence, pending, error, onRetry, onClose }: { scholar: ScholarSummary; evidence?: ScholarEvidenceBundle | undefined; pending: boolean; error: Error | null; onRetry: () => void; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [onClose]);
  return <div className="sg-evidence-layer" role="dialog" aria-modal="true" aria-labelledby="evidence-title"><button className="sg-evidence-scrim" aria-label="关闭数据来源" onClick={onClose} /><aside className="sg-evidence-drawer"><header><div><span>数据来源与可信说明</span><h2 id="evidence-title">{scholar.canonical_name}</h2></div><Button kind="ghost" onClick={onClose}>关闭</Button></header>{pending && <InlineLoading description="正在读取来源证据" />}{error && <InlineNotification kind="error" title="来源记录暂不可用" subtitle={error.message} actionButtonLabel="重试" onActionButtonClick={onRetry} />}{evidence && <><div className="sg-evidence-summary"><strong>{evidence.items.length}</strong><span>条可追溯来源记录</span><code>对象版本 {evidence.object_version}</code></div>{evidence.items.length === 0 ? <EmptyInline text="该学者尚无可展示来源记录。" /> : <div className="sg-evidence-list">{evidence.items.map((item) => <EvidenceRecord key={`${item.evidence_id}-${item.relation_id ?? 'object'}`} item={item} />)}</div>}</>}<footer><Button onClick={onClose}>完成查看</Button></footer></aside></div>;
}

function EvidenceRecord({ item }: { item: ScholarEvidenceItem }) {
  return <article><div><span>{item.source_name ?? '来源未命名'}</span></div><h3>{item.citation}</h3>{item.excerpt && <p>{item.excerpt}</p>}<dl><div><dt>观察时间</dt><dd>{formatDate(item.observed_at)}</dd></div><div><dt>来源版本</dt><dd>{item.source_version ?? item.dataset_version ?? '尚未标注'}</dd></div><div><dt>关系类型</dt><dd>{item.predicate ? predicateLabels[item.predicate] ?? item.predicate : '对象本身'}</dd></div><div><dt>数据属性</dt><dd>{item.synthetic ? '演示数据' : '真实来源'}</dd></div></dl></article>;
}

function DirectoryLoading() { return <section className="sg-directory-loading" aria-label="正在加载学者目录">{Array.from({ length: 8 }, (_, index) => <div key={index}><SkeletonText heading width="18%" /><SkeletonText width="78%" /><SkeletonText width="52%" /></div>)}</section>; }
function DetailLoading() { return <div className="sg-scholars-page sg-detail-loading" aria-label="正在加载学者详情"><SkeletonText width="18%" /><SkeletonText heading width="35%" /><SkeletonText width="62%" /><div>{Array.from({ length: 4 }, (_, index) => <SkeletonText key={index} paragraph lineCount={4} />)}</div></div>; }
function EmptyInline({ text }: { text: string }) { return <div className="sg-empty-inline"><Information size={20} /><span>{text}</span></div>; }
function EmptyState({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode | undefined }) { return <section className="sg-page-empty">{icon}<h2>{title}</h2><p>{text}</p>{action}</section>; }
