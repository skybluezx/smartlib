import { analysisPosition, analysisTabs, analysisSections } from './analysisNavigation';
import { useSessionState } from './useSessionState';
import { WorkbenchSettingsProvider, useWorkbenchPreference } from './workbenchSettings';
import { InstitutionGranularityControls, InstitutionName, defaultInstitutionSettings, type InstitutionSettings, type InstitutionContext } from './InstitutionGranularityControls';
import { CooperationAssessmentPanel } from './CooperationAssessmentPanel';
import './fundingCategoryChart.css';
import { DisciplinePanel } from './DisciplinePanel';
import { AnalysisLibrary } from './AnalysisLibrary';
import { ResearchStrategyPanel } from './ResearchStrategyPanel';
import { defaultStrategy } from './strategyAnalysis';
import {
  Fragment, useCallback, useEffect, useMemo, useRef, useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Add, Analytics, Building, CenterToFit, ChartDonut, CheckmarkFilled,
  Information, Maximize, Minimize, Renew, TrashCan, Undo,
  UserMultiple, WarningAlt, ZoomIn, ZoomOut,
} from '@carbon/icons-react';
import {
  Button, Dropdown, InlineLoading, InlineNotification, Modal, Tag,
  Checkbox, FilterableMultiSelect, NumberInput, Tab, TabList, TabPanel, TabPanels, Tabs,
  TextArea, TextInput, Pagination, ComboBox,
} from '@carbon/react';
import { Link, useSearchParams } from 'react-router-dom';
import type {
  AnalysisScopeOption,
  CollaborationEdge, CollaborationNetwork, CollaborationNode,
  FundingCandidateShare, FundingShare, InCitesJournalAnalysis, JournalAnalysis,
  PublicationMetricAggregate,
  QuartileShare,
  CustomGraphScopePreview,
} from '../../generated/smartlib-api';
import {
  getGraphAnalysisScopeOptionsView,
  getScholarGraphAnalyticsView,
  deleteCustomGraphScopeView,
  listCustomGraphScopesView,
  previewCustomGraphScopeView,
  saveCustomGraphScopeView,
  type GraphAnalysisQuery,
} from '../../shared/api/smartlib';
import { clusteredGraphLayout, clusterEnvelopes } from '../graph/clusteredGraphLayout';
import { clientToGraph, type GraphPointer } from '../graph/graphInteraction';

const ANALYSIS_GRAPH_WIDTH = 1240;
const ANALYSIS_GRAPH_HEIGHT = 720;

const minimumOptions = [
  { id: 2, label: '至少 2 篇共同论文' },
  { id: 3, label: '至少 3 篇共同论文' },
  { id: 5, label: '至少 5 篇共同论文' },
  { id: 1, label: '至少 1 篇共同论文' },
];

export function ScholarGraphAnalyticsPage() { return <WorkbenchSettingsProvider><ScholarGraphAnalyticsWorkbench /></WorkbenchSettingsProvider>; }

function ScholarGraphAnalyticsWorkbench() {
  const queryClient = useQueryClient();
  const [institutionSettings,setInstitutionSettings] = useSessionState<InstitutionSettings>('institutionSettings',defaultInstitutionSettings);
  const [minimum, setMinimum] = useSessionState('minimum',2);
  const [peopleView, setPeopleView] = useSessionState<GraphAnalysisQuery>('peopleView',{ edgeLimit: 120 });
  const [strategy, setStrategy] = useSessionState('strategy',defaultStrategy);
  const [searchParams, setSearchParams] = useSearchParams();
  const {tab: analysisTab, section: analysisSection} = analysisPosition(searchParams);
  const setAnalysisTab = (index: number) => setSearchParams(previous => { const next=new URLSearchParams(previous); next.set('tab',analysisTabs[index] ?? 'journals'); return next; });
  const setAnalysisSection = (index: number) => setSearchParams(previous => { const next=new URLSearchParams(previous); next.set('section',analysisSections[index] ?? 'basic'); return next; });
  const selectedModule = analysisSection === 1 ? 'collaboration_outcomes' : analysisTabs[analysisTab] ?? 'journals';
  const [draft, setDraft] = useSessionState<AnalysisScopeDraft>('scopeDraft',emptyScopeDraft);
  const [appliedScope, setAppliedScope] = useSessionState<GraphAnalysisQuery>('appliedScope',{});
  const scopeOptions = useQuery({
    queryKey: ['scholar-graph-analysis-scope-options'],
    queryFn: ({ signal }) => getGraphAnalysisScopeOptionsView(signal),
    staleTime: 5 * 60_000,
  });
  const result = useQuery({
    queryKey: ['scholar-graph-analytics', minimum, appliedScope, selectedModule, selectedModule === 'people_collaboration' ? peopleView : null, selectedModule === 'institution_collaboration' ? institutionSettings : null],
    queryFn: ({ signal }) => getScholarGraphAnalyticsView({ ...appliedScope, ...peopleView, selectedModule, minimumPublicationCount: minimum, institutionSettings: JSON.stringify(institutionSettings) }, signal),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const analysisStatus = <>
    {result.isPending && <AnalyticsLoading />}
    {result.isError && <section className="sg-state-section"><InlineNotification kind="error" title="图谱分析暂不可用" subtitle={`${result.error.message}。学者目录、科研成果和机构页面仍可使用。`} /><Button kind="ghost" onClick={() => void result.refetch()}>重试</Button></section>}
    {result.data && <>
      {result.data.coverage.publications === 0 && <section className="sg-state-section"><InlineNotification kind="info" title="当前范围没有可分析的论文" subtitle="请放宽年份，或减少项目种类、机构和学者条件后重新应用。" hideCloseButton /></section>}
      <section className="sg-analytics-coverage" aria-label="分析数据覆盖">
        <CoverageMetric label="正式论文" value={result.data.coverage.publications} note="当前权威论文对象" />
        <CoverageMetric label="作者关系覆盖" value={result.data.coverage.publications_with_authors} denominator={result.data.coverage.publications} />
        <CoverageMetric label="机构关系覆盖" value={result.data.coverage.publications_with_affiliations} denominator={result.data.coverage.publications} />
        <CoverageMetric label="学科分类覆盖" value={result.data.coverage.publications_with_disciplines} denominator={result.data.coverage.publications} />
        <div className="sg-analytics-source">{result.data.coverage.graph_backend === 'hugegraph' ? <CheckmarkFilled /> : <WarningAlt />}<span><strong>{result.data.coverage.graph_backend === 'hugegraph' ? 'PostgreSQL 权威聚合 · HugeGraph 图投影已启用' : 'PostgreSQL 权威聚合 · 图关系处于降级读取'}</strong><small>统一分析准入规则 · {formatTime(result.data.coverage.generated_at)}</small></span></div>
      </section>
    </>}
  </>;

  return <div className="sg-analytics-page">
    <header className="sg-analytics-heading">
      <div><h1>图谱分析</h1><span>从论文、作者、机构、项目与学科关系中观察科研协作和方向分布。</span></div>
      <Button kind="secondary" renderIcon={Renew} disabled={result.isFetching} onClick={() => { void queryClient.invalidateQueries({queryKey: ['scoped-direction-extensions']}); void queryClient.invalidateQueries({queryKey: ['scholar-graph-analytics']}); }}>刷新分析</Button>
    </header>
    <AnalysisScopePanel
      draft={draft}
      options={scopeOptions.data}
      optionsPending={scopeOptions.isPending}
      optionsError={scopeOptions.isError}
      applying={result.isFetching}
      activeCustomScopeName={result.data?.scope.custom_scope_name ?? undefined}
      onChange={setDraft}
      onApply={(nextScope) => setAppliedScope(nextScope)}
      appliedCustomScopeId={appliedScope.customScopeId}
      onApplyCustomQuery={(graphQuery) => setAppliedScope((current) => ({
        ...current, customScopeId: undefined, customGraphQuery: graphQuery,
      }))}
      onApplySavedScope={(scopeId) => setAppliedScope((current) => ({
        ...current, customGraphQuery: undefined, customScopeId: scopeId,
      }))}
      onReset={() => { setDraft(emptyScopeDraft); setAppliedScope({}); }}
    />
    <div className="sg-analysis-sections"><Tabs selectedIndex={analysisSection} onChange={({ selectedIndex }) => setAnalysisSection(selectedIndex)}>
      <TabList aria-label="分析工作区"><Tab>基础分析</Tab><Tab>专题分析</Tab><Tab>分析记录</Tab></TabList>
      <TabPanels>
        <TabPanel>
          <header className="sg-analysis-section-heading"><h2>基础分析</h2><p>在同一论文范围内，查看资助、期刊、合作网络与学科分布。</p></header>
          {analysisSection === 0 && analysisStatus}
          {<>      <div className="sg-analytics-tabs"><Tabs selectedIndex={analysisTab} onChange={({ selectedIndex }) => setAnalysisTab(selectedIndex)}>
        <TabList aria-label="图谱分析内容"><Tab>论文与期刊</Tab><Tab>基金项目分布</Tab><Tab>学科方向</Tab><Tab>学者合作</Tab><Tab>机构合作</Tab></TabList>
        <TabPanels>
          <TabPanel>{analysisSection === 0 && analysisTab === 0 && result.data?.journals && <JournalPanel analysis={result.data.journals} publications={result.data.coverage.publications} />}</TabPanel>
        <TabPanel>{analysisSection === 0 && analysisTab === 1 && result.data?.funding && <FundingPanel categories={result.data.funding.category_shares} publicationCount={result.data.coverage.publications} programs={result.data.funding.verified_programs} candidatePrograms={result.data.funding.candidate_programs} pendingRelations={result.data.funding.pending_relation_count} pendingProgramRelations={result.data.funding.pending_program_relation_count} pendingGrantRelations={result.data.funding.pending_grant_relation_count} pendingProgramCandidates={result.data.funding.pending_program_candidate_count} pendingGrantCandidates={result.data.funding.pending_grant_candidate_count} includedProjectKinds={result.data.funding.included_project_kind_count ?? 0} pendingCandidates={result.data.funding.pending_candidate_count} />}</TabPanel>
          <TabPanel>{analysisSection === 0 && analysisTab === 2 && result.data?.disciplines && <DisciplinePanel key={JSON.stringify(appliedScope)} workspace={result.data.disciplines.workspace} dataVersion={result.data.data_version} />}</TabPanel>
          <TabPanel>{analysisSection === 0 && analysisTab === 3 && result.data?.people_collaboration && <CollaborationPanel title="学者合作关系" description="节点仅显示人员。共同署名同一篇论文形成一条合作边，边上数字是共同论文数量。" icon="people" network={result.data.people_collaboration} minimum={minimum} onMinimumChange={setMinimum} view={peopleView} onViewChange={setPeopleView} />}</TabPanel>
          <TabPanel>{analysisSection === 0 && analysisTab === 4 && result.data?.institution_collaboration && <InstitutionCollaborationPanel network={result.data.institution_collaboration} settings={institutionSettings} onApply={setInstitutionSettings} />}</TabPanel>
        </TabPanels>
      </Tabs></div></>}
        </TabPanel>
        <TabPanel>
          <header className="sg-analysis-section-heading"><h2>专题分析</h2><p>组合多类学术对象，围绕具体问题比较成果表现。支持合作交叉比较、伙伴与方向观察，并记录申请、支持措施和复盘。</p></header>
          {analysisSection === 1 && analysisStatus}
          {result.data && <>{result.data.collaboration_outcomes
            ? <ResearchStrategyPanel data={result.data.collaboration_outcomes} settings={strategy} onSettings={setStrategy} />
            : <InlineNotification kind="info" title="专题分析暂不可用" subtitle="当前接口尚未返回专题结果，其他分析仍可使用。" hideCloseButton />}
</>}
        </TabPanel>
        <TabPanel>
    <AnalysisLibrary comparison={strategy} onComparison={setStrategy} active={analysisSection === 2} query={{ ...appliedScope, ...peopleView, institutionSettings: JSON.stringify(institutionSettings), minimumPublicationCount: minimum }} onApply={(query) => {
      const { institutionSettings: restoredInstitution, edgeLimit, peopleFocusId, peopleOrganizationId, peopleIncludeExternal, ...scope } = query;
      setInstitutionSettings(restoredInstitution ? JSON.parse(restoredInstitution) as InstitutionSettings : defaultInstitutionSettings);
      setPeopleView({edgeLimit: edgeLimit ?? 120, peopleFocusId, peopleOrganizationId, peopleIncludeExternal});
      setAppliedScope(scope); setMinimum(query.minimumPublicationCount ?? 2); setAnalysisSection(1);
      setDraft({ ...emptyScopeDraft, startYear: query.startYear, endYear: query.endYear,
        projectKindsEnabled: Boolean(query.projectKindIds?.length),
        organizationsEnabled: Boolean(query.organizationIds?.length),
        scholarsEnabled: Boolean(query.scholarIds?.length),
        projectKindIds: query.projectKindIds ?? [], organizationIds: query.organizationIds ?? [],
        scholarIds: query.scholarIds ?? [] });
    }} />
        </TabPanel>
      </TabPanels>
    </Tabs></div>
  </div>;
}

interface AnalysisScopeDraft {
  startYear?: number | undefined;
  endYear?: number | undefined;
  projectKindsEnabled: boolean;
  organizationsEnabled: boolean;
  scholarsEnabled: boolean;
  projectKindIds: string[];
  organizationIds: string[];
  scholarIds: string[];
}

const emptyScopeDraft: AnalysisScopeDraft = {
  projectKindsEnabled: false,
  organizationsEnabled: false,
  scholarsEnabled: false,
  projectKindIds: [],
  organizationIds: [],
  scholarIds: [],
};

function AnalysisScopePanel({ draft, options, optionsPending, optionsError, applying, activeCustomScopeName, appliedCustomScopeId, onChange, onApply, onApplyCustomQuery, onApplySavedScope, onReset }: {
  draft: AnalysisScopeDraft;
  options?: { minimum_year?: number | null | undefined; maximum_year?: number | null | undefined; project_kinds?: AnalysisScopeOption[] | undefined; organizations?: AnalysisScopeOption[] | undefined; scholars?: AnalysisScopeOption[] | undefined } | undefined;
  optionsPending: boolean;
  optionsError: boolean;
  applying: boolean;
  activeCustomScopeName?: string | undefined;
  appliedCustomScopeId?: string | undefined;
  onChange: (scope: AnalysisScopeDraft) => void;
  onApply: (scope: GraphAnalysisQuery) => void;
  onApplyCustomQuery: (graphQuery: string) => void;
  onApplySavedScope: (scopeId: string) => void;
  onReset: () => void;
}) {
  const [customScopeOpen, setCustomScopeOpen] = useState(false);
  const minimumYear = options?.minimum_year ?? 1500;
  const maximumYear = options?.maximum_year ?? 2200;
  const startYear = draft.startYear ?? minimumYear;
  const endYear = draft.endYear ?? maximumYear;
  const invalidRange = startYear > endYear;
  const missingSelection = (draft.projectKindsEnabled && draft.projectKindIds.length === 0)
    || (draft.organizationsEnabled && draft.organizationIds.length === 0)
    || (draft.scholarsEnabled && draft.scholarIds.length === 0);
  const optionLabel = (item: AnalysisScopeOption | null | undefined) => item ? `${item.name}（${item.publication_count} 篇）` : '';
  const selected = (items: AnalysisScopeOption[] | undefined, ids: string[]) => (items ?? []).filter((item) => ids.includes(item.object_id));
  const updateIds = (key: 'projectKindIds' | 'organizationIds' | 'scholarIds', selectedItems: AnalysisScopeOption[]) => onChange({ ...draft, [key]: selectedItems.map((item) => item.object_id) });
  const apply = () => onApply({
    startYear,
    endYear,
    projectKindIds: draft.projectKindsEnabled ? draft.projectKindIds : undefined,
    organizationIds: draft.organizationsEnabled ? draft.organizationIds : undefined,
    scholarIds: draft.scholarsEnabled ? draft.scholarIds : undefined,
  });

  return <section className="sg-analysis-scope" aria-labelledby="analysis-scope-title">
    <header><div><h2 id="analysis-scope-title">分析范围</h2><p>同一范围应用于基金、期刊、项目、合作关系和学科分析。每类条件内取并集，不同条件之间取交集。</p></div><div className="sg-scope-header-actions">{applying && <InlineLoading description="正在更新分析" />}<Button kind="tertiary" size="sm" renderIcon={Add} onClick={() => setCustomScopeOpen(true)}>添加自定义范围</Button></div></header>
    <div className="sg-analysis-scope-grid">
      <div className="sg-scope-time"><strong>时间范围</strong><div><NumberInput id="analysis-start-year" label="开始年份" min={minimumYear} max={maximumYear} value={startYear} invalid={invalidRange} onChange={(_event, state) => onChange({ ...draft, startYear: Number(state.value) })} /><span>至</span><NumberInput id="analysis-end-year" label="结束年份" min={minimumYear} max={maximumYear} value={endYear} invalid={invalidRange} invalidText={invalidRange ? '结束年份应不早于开始年份' : undefined} onChange={(_event, state) => onChange({ ...draft, endYear: Number(state.value) })} /></div></div>
      <ScopeDimension title="项目种类" checked={draft.projectKindsEnabled} onChecked={(checked) => onChange({ ...draft, projectKindsEnabled: checked })}>
        <FilterableMultiSelect<AnalysisScopeOption> id="analysis-project-kinds" titleText="选择项目种类" placeholder={optionsPending ? '正在载入项目种类' : '可搜索并多选'} items={options?.project_kinds ?? []} itemToString={(item) => optionLabel(item)} selectedItems={selected(options?.project_kinds, draft.projectKindIds)} disabled={!draft.projectKindsEnabled || optionsPending || optionsError} onChange={({ selectedItems }) => updateIds('projectKindIds', selectedItems)} />
      </ScopeDimension>
      <ScopeDimension title="机构" checked={draft.organizationsEnabled} onChecked={(checked) => onChange({ ...draft, organizationsEnabled: checked })}>
        <FilterableMultiSelect<AnalysisScopeOption> id="analysis-organizations" titleText="选择机构" placeholder={optionsPending ? '正在载入机构' : '包含所选机构的下级机构'} items={options?.organizations ?? []} itemToString={(item) => optionLabel(item)} selectedItems={selected(options?.organizations, draft.organizationIds)} disabled={!draft.organizationsEnabled || optionsPending || optionsError} onChange={({ selectedItems }) => updateIds('organizationIds', selectedItems)} />
      </ScopeDimension>
      <ScopeDimension title="学者" checked={draft.scholarsEnabled} onChecked={(checked) => onChange({ ...draft, scholarsEnabled: checked })}>
        <FilterableMultiSelect<AnalysisScopeOption> id="analysis-scholars" titleText="选择学者" placeholder={optionsPending ? '正在载入学者' : '可搜索并多选'} items={options?.scholars ?? []} itemToString={(item) => optionLabel(item)} selectedItems={selected(options?.scholars, draft.scholarIds)} disabled={!draft.scholarsEnabled || optionsPending || optionsError} onChange={({ selectedItems }) => updateIds('scholarIds', selectedItems)} />
      </ScopeDimension>
    </div>
    <SavedCustomScopes activeScopeName={activeCustomScopeName} appliedScopeId={appliedCustomScopeId} onOpen={() => setCustomScopeOpen(true)} onApply={onApplySavedScope} />
    {optionsError && <InlineNotification kind="warning" title="部分范围选项暂不可用" subtitle="时间范围仍可设置；项目种类、机构和学者选项可稍后重试。" hideCloseButton />}
    {missingSelection && <p className="sg-scope-validation">已启用的条件至少选择一项。</p>}
    <footer><div><Button kind="ghost" size="sm" onClick={onReset}>重置</Button><Button size="sm" disabled={invalidRange || missingSelection || applying} onClick={apply}>应用范围</Button></div></footer>
    <CustomScopeModal open={customScopeOpen} onClose={() => setCustomScopeOpen(false)} onApply={(query) => { onApplyCustomQuery(query); setCustomScopeOpen(false); }} />
  </section>;
}

const customScopeExample = `MATCH (publication:knowledge_object)-[funding:relates]->(project:knowledge_object)
WHERE publication.object_type = "publication"
  AND funding.predicate = "publication.supported_by_project"
  AND project.object_type = "project"
RETURN DISTINCT publication.object_id AS publication_id`;

function SavedCustomScopes({ activeScopeName, appliedScopeId, onOpen, onApply }: {
  activeScopeName?: string | undefined;
  appliedScopeId?: string | undefined;
  onOpen: () => void;
  onApply: (scopeId: string) => void;
}) {
  const queryClient = useQueryClient();
  const scopes = useQuery({ queryKey: ['custom-graph-analysis-scopes'], queryFn: listCustomGraphScopesView });
  const remove = useMutation({
    mutationFn: deleteCustomGraphScopeView,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['custom-graph-analysis-scopes'] }),
  });
  return <div className="sg-saved-scopes">
    <div><strong>已保存的自定义范围</strong><span>点击即可按最新图数据重新执行</span>{activeScopeName && <Tag type="teal">当前：{activeScopeName}</Tag>}</div>
    <div className="sg-saved-scope-list">
      {scopes.isPending && <InlineLoading description="正在读取" />}
      {scopes.isError && <span className="sg-saved-scope-empty">读取失败，可稍后重试</span>}
      {scopes.data?.map((scope) => <div className="sg-saved-scope-item" key={scope.scope_id}>
        <Button kind={scope.scope_id === appliedScopeId ? 'tertiary' : 'ghost'} size="sm" onClick={() => onApply(scope.scope_id)}>{scope.name}<small>{scope.last_result_count ?? '未执行'} 篇</small></Button>
        <Button kind="ghost" size="sm" hasIconOnly renderIcon={TrashCan} iconDescription={`删除${scope.name}`} disabled={remove.isPending} onClick={() => remove.mutate(scope.scope_id)} />
      </div>)}
      {!scopes.isPending && !scopes.isError && !scopes.data.length && <button type="button" className="sg-saved-scope-empty" onClick={onOpen}>尚未保存范围，创建后可在这里直接选择</button>}
    </div>
  </div>;
}

function CustomScopeModal({ open, onClose, onApply }: {
  open: boolean;
  onClose: () => void;
  onApply: (query: string) => void;
}) {
  const queryClient = useQueryClient();
  const [graphQuery, setGraphQuery] = useState(customScopeExample);
  const [preview, setPreview] = useState<CustomGraphScopePreview>();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const execute = useMutation({
    mutationFn: () => previewCustomGraphScopeView(graphQuery),
    onSuccess: setPreview,
  });
  const save = useMutation({
    mutationFn: () => saveCustomGraphScopeView(name, description, graphQuery),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['custom-graph-analysis-scopes'] });
      setName('');
    },
  });
  const close = () => { execute.reset(); save.reset(); setPreview(undefined); onClose(); };
  return <Modal open={open} size="lg" modalHeading="自定义分析范围" modalLabel="HugeGraph · 只读 Cypher" primaryButtonText={preview ? '应用此范围' : '执行并预览'} secondaryButtonText="取消" primaryButtonDisabled={execute.isPending || !graphQuery.trim()} onRequestClose={close} onSecondarySubmit={close} onRequestSubmit={() => preview ? onApply(graphQuery) : execute.mutate()}>
    <div className="sg-custom-scope-modal">
      <p>查询应圈定论文节点。系统只允许固定路径的只读 MATCH，并在 PostgreSQL 中再次应用统一分析准入规则。</p>
      <TextArea id="custom-graph-query" labelText="Cypher 查询语句" rows={9} value={graphQuery} invalid={execute.isError} invalidText={execute.error?.message} onChange={(event) => { setGraphQuery(event.target.value); setPreview(undefined); execute.reset(); }} />
      <div className="sg-query-contract"><strong>返回约定</strong><code>RETURN DISTINCT publication.object_id AS publication_id</code><span>最多返回 5,000 篇；执行超时为 5 秒。</span></div>
      {execute.isPending && <InlineLoading description="正在 HugeGraph 中执行并生成范围简报" />}
      {preview && <CustomScopeBrief preview={preview} />}
      {preview && <section className="sg-custom-scope-save"><header><strong>保存供下次使用</strong><span>保存的是查询定义，每次使用都会基于最新图数据重新执行。</span></header><div><TextInput id="custom-scope-name" labelText="范围名称" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} /><TextInput id="custom-scope-description" labelText="说明（可选）" value={description} maxLength={300} onChange={(event) => setDescription(event.target.value)} /></div>{save.isError && <InlineNotification kind="error" title="保存失败" subtitle={save.error.message} hideCloseButton />}{save.isSuccess && <InlineNotification kind="success" title="范围已保存" subtitle="已加入分析范围的快捷选择。" hideCloseButton />}<Button kind="secondary" size="sm" disabled={!name.trim() || save.isPending || save.isSuccess} onClick={() => save.mutate()}>{save.isPending ? '正在保存' : '保存范围'}</Button></section>}
    </div>
  </Modal>;
}

function CustomScopeBrief({ preview }: { preview: CustomGraphScopePreview }) {
  const yearRange = preview.minimum_year && preview.maximum_year
    ? preview.minimum_year === preview.maximum_year ? String(preview.minimum_year) : `${preview.minimum_year} 至 ${preview.maximum_year}`
    : '年份尚未收录';
  return <section className="sg-custom-scope-brief" aria-label="自定义范围简报">
    <header><div><strong>范围简报</strong><span>查询耗时 {Math.round(preview.took_ms)} 毫秒</span></div>{preview.truncated && <Tag type="warm-gray">结果已截断</Tag>}</header>
    <div><CoverageMetric label="圈定论文" value={preview.publication_count} note={yearRange} /><CoverageMetric label="作者覆盖" value={preview.publications_with_authors} denominator={preview.publication_count} /><CoverageMetric label="机构覆盖" value={preview.publications_with_affiliations} denominator={preview.publication_count} /></div>
    {!!preview.top_journals?.length && <div className="sg-custom-scope-journals"><strong>主要期刊</strong><span>{preview.top_journals.map((journal) => `${journal.name} ${journal.publication_count} 篇`).join(' · ')}</span></div>}
    <div className="sg-custom-scope-samples"><strong>样例论文</strong>{preview.sample_publications?.length ? <ol>{preview.sample_publications.map((paper) => <li key={paper.object_id}><span>{paper.title}</span><small>{[paper.publication_year, paper.journal_name].filter(Boolean).join(' · ') || '出版信息尚未收录'}</small></li>)}</ol> : <p>当前查询没有得到符合准入规则的论文。</p>}</div>
  </section>;
}

function ScopeDimension({ title, checked, onChecked, children }: { title: string; checked: boolean; onChecked: (checked: boolean) => void; children: ReactNode }) {
  const id = `analysis-scope-${title}`;
  return <div className="sg-scope-dimension"><Checkbox id={id} labelText={`限定${title}`} checked={checked} onChange={(_event, state) => onChecked(state.checked)} />{children}</div>;
}

function JournalPanel({ analysis, publications }: { analysis: JournalAnalysis; publications: number }) {
  const quartilePublications = Math.round(analysis.jcr_quartiles.reduce((total, item) => total + item.paper_equivalents, 0));
  const missingQuartilePublications = Math.max(0, publications - quartilePublications);
  return <section className="sg-analysis-panel">
    <header className="sg-analysis-panel-heading"><div><Analytics size={24} /><span><h2>论文与期刊分析</h2><p>统计论文的发表期刊分布，期刊指标按论文的发表年份进行匹配。</p></span></div></header>
    <div className="sg-journal-ledger sg-journal-jcr-ledger">
      <MetricCell label="期刊数量" value={analysis.journal_count} note="当前范围涉及的期刊" />
      <MetricCell label="期刊关系覆盖" value={analysis.linked_publications} note={`共 ${publications} 篇正式论文`} />
      <MetricCell label="同年 JCR 指标" value={analysis.jcr_matched_publications} note="已发布版本" />
      <MetricCell label="影响因子中位数" value={formatMetric(analysis.impact_factor.median)} note={`${analysis.impact_factor.matched_publications} 篇可计算`} />
    </div>
    <div className="sg-journal-grid">
      <section><header><h3>发表期刊分布</h3><p className="sg-analysis-inline-note"><Information size={16} aria-hidden="true" /><span>展示全部 {analysis.journal_count} 种期刊，按论文数排序；占比按当前范围 {publications} 篇论文计算。JCR 指标按论文发表年份匹配；多来源指标参与分析，数据更新后结果可能调整。缺少同年数据时保持缺失，不用其他年份替代。</span></p></header>{analysis.top_journals.length ? <div className="sg-journal-distribution-scroll" role="region" tabIndex={0} aria-label="发表期刊分布列表，可上下滚动"><FundingCoverageList publicationCount={publications} items={analysis.top_journals.map((journal) => ({ id: journal.object_id, name: journal.name, count: journal.publication_count, source: '' }))} /></div> : <AnalysisEmpty text="当前范围暂无可统计的发表期刊。" />}</section>
      <section><header><h3>论文发表当年的 JCR 分区分布</h3><p className="sg-analysis-inline-note"><Information size={16} aria-hidden="true" /><span>共 {quartilePublications} 篇论文具有有效分区，{missingQuartilePublications} 篇缺少分区信息，未计入占比。多学科期刊按类别等权分摊，每篇论文合计计为 1 篇。</span></p></header><div className="sg-quartile-comparison"><QuartileBars title="JCR 分区" items={analysis.jcr_quartiles} /></div></section>
    </div>
    <InCitesImpactPanel analysis={analysis.incites} publications={publications} />
  </section>;
}

const incitesPerformanceCodes = [
  'incites.times_cited', 'incites.cnci', 'incites.jnci',
  'incites.collab_cnci', 'incites.subject_percentile',
];

function InCitesImpactPanel({ analysis, publications }: {
  analysis: InCitesJournalAnalysis | null | undefined;
  publications: number;
}) {
  if (!analysis) return <section className="sg-incites-section"><AnalysisEmpty text="当前范围没有可用的 InCites 论文指标快照。" /></section>;
  const metrics = analysis.metrics ?? [];
  const metric = (code: string) => metrics.find((item) => item.code === code);
  const citations = metric('incites.times_cited');
  const cnci = metric('incites.cnci');
  const percentile = metric('incites.subject_percentile');
  return <section className="sg-incites-section" aria-labelledby="incites-impact-title">
    <header className="sg-incites-heading"><div><h3 id="incites-impact-title">InCites 论文影响指标</h3><p>固定使用同一份来源快照，展示当前论文范围内的引用表现、规范化指标和来源上下文。</p></div><span><strong>索引截至 {formatDate(analysis.indexed_through)}</strong><small>数据更新 {formatDate(analysis.dataset_updated_on)} · 导出 {formatDate(analysis.exported_on)}</small></span></header>
    <div className="sg-journal-ledger sg-incites-ledger">
      <MetricCell label="InCites 快照覆盖" value={analysis.snapshot_publications} note={`${coveragePercent(analysis.snapshot_publications, publications)} · 当前范围 ${publications} 篇`} />
      <MetricCell label="累计被引频次" value={formatMetric(citations?.total)} note={`${citations?.covered_publications ?? 0} 篇有值 · 截至索引日期`} />
      <MetricCell label="CNCI 中位数" value={formatMetric(cnci?.median)} note={`均值 ${formatMetric(cnci?.mean)} · 基准 1`} />
      <MetricCell label="学科领域百分位中位数" value={formatMetric(percentile?.median)} note={`${percentile?.covered_publications ?? 0} 篇有值 · 数值越高位置越前`} />
    </div>
    <div className="sg-incites-metric-groups">
      <InCitesMetricGroup title="论文引用表现" description="集合先按论文对象去重；缺失值不按零填充。" metrics={incitesPerformanceCodes.map(metric).filter((item): item is PublicationMetricAggregate => Boolean(item))} />
      <InCitesMetricGroup title="规范化基准与期刊上下文" description="这些值用于解释来源口径，不累加成论文或项目得分。" metrics={metrics.filter((item) => !incitesPerformanceCodes.includes(item.code))} contextual />
    </div>
    <div className="sg-analysis-caveat"><Information size={20} /><div><strong>统计口径</strong><p>{analysis.scope_note}</p></div></div>
  </section>;
}

function InCitesMetricGroup({ title, description, metrics, contextual = false }: {
  title: string;
  description: string;
  metrics: PublicationMetricAggregate[];
  contextual?: boolean;
}) {
  return <section><header><h3>{title}</h3><p>{description}</p></header><div className="sg-incites-metric-list">{metrics.map((item) => {
    const benchmark = item.reference == null ? null : `${item.above_reference_count ?? 0} 篇高于基准 ${formatMetric(item.reference)}`;
    const primary = item.code === 'incites.times_cited' ? `合计 ${formatMetric(item.total)}` : `中位数 ${formatMetric(item.median)}`;
    return <article key={item.code}><div><strong>{item.label}</strong><p>{item.definition}</p></div><dl><div><dt>{contextual ? '样本描述' : '当前结果'}</dt><dd>{primary}</dd></div><div><dt>均值 / 范围</dt><dd>{formatMetric(item.mean)} / {formatMetric(item.minimum)}–{formatMetric(item.maximum)}</dd></div><div><dt>覆盖</dt><dd>{item.covered_publications} 篇 · 缺失 {item.missing_publications} 篇</dd></div>{benchmark && <div><dt>基准比较</dt><dd>{benchmark}</dd></div>}</dl></article>;
  })}</div></section>;
}

function MetricCell({ label, value, note }: { label: string; value: number | string; note: string }) { return <span><small>{label}</small><strong>{typeof value === 'number' ? value.toLocaleString('zh-CN') : value}</strong><em>{note}</em></span>; }

function QuartileBars({ title, items, cas = false }: { title: string; items: QuartileShare[]; cas?: boolean }) {
  const hasData = items.some((item) => item.paper_equivalents > 0);
  return <section><h4>{title}</h4>{hasData ? items.map((item) => <div key={item.quartile}><span>{cas ? `${item.quartile.slice(1)}区` : item.quartile}</span><i><b style={{ width: `${item.share * 100}%` }} /></i><em>{formatPercent(item.share)}</em></div>) : <p>暂无已发布的同年指标</p>}</section>;
}

function CoverageMetric({ label, value, denominator, note }: { label: string; value: number; denominator?: number; note?: string }) {
  const percent = denominator ? Math.round(value / denominator * 100) : null;
  return <article><span>{label}</span><strong>{value}</strong><small>{note ?? (percent === null ? '当前关系记录' : `覆盖 ${percent}%`)}</small></article>;
}

const fundingColors = ['#0f62fe', '#007d79', '#6929c4', '#1192e8', '#9f1853', '#fa4d56', '#005d5d', '#002d9c', '#a56eff', '#b28600', '#009d9a', '#8a3800'];
function fundingColor(index: number, id: string) {
  return id.endsWith(':other') ? '#8d8d8d' : fundingColors[index % fundingColors.length];
}

function FundingPanel({ categories, publicationCount, programs, candidatePrograms, pendingRelations, pendingProgramRelations, pendingGrantRelations, pendingProgramCandidates, pendingGrantCandidates, includedProjectKinds, pendingCandidates }: { categories?: FundingShare[] | undefined; publicationCount: number; programs: FundingShare[]; candidatePrograms: FundingCandidateShare[]; pendingRelations: number; pendingProgramRelations: number; pendingGrantRelations: number; pendingProgramCandidates: number; pendingGrantCandidates: number; includedProjectKinds: number; pendingCandidates: number }) {
  const individualKinds = candidatePrograms.filter((item) => item.object_id !== 'candidate:other');
  const other = candidatePrograms.find((item) => item.object_id === 'candidate:other');
  return <section className="sg-analysis-panel">
    <header className="sg-analysis-panel-heading"><div><ChartDonut size={24} /><span><h2>基金与项目资助构成</h2><p className="sg-analysis-inline-note"><Information size={16} aria-hidden="true" /><span>基金与项目资助信息汇集自论文全文提取、InCites 等多来源导入，并进行交叉核验。</span></p></span></div></header>
    <div className="sg-funding-status" aria-label="基金关系数据范围"><article><span>全文提取项目关系</span><strong>{pendingRelations.toLocaleString('zh-CN')}</strong><small>{pendingCandidates.toLocaleString('zh-CN')} 个项目对象</small></article><article><span>有项目编号</span><strong>{pendingGrantRelations.toLocaleString('zh-CN')}</strong><small>{pendingGrantCandidates.toLocaleString('zh-CN')} 个项目对象</small></article><article><span>无项目编号</span><strong>{pendingProgramRelations.toLocaleString('zh-CN')}</strong><small>{pendingProgramCandidates.toLocaleString('zh-CN')} 个占位项目</small></article></div>
    <p className="sg-funding-note sg-analysis-inline-note"><Information size={16} aria-hidden="true" /><span>占比 = 该项关联的去重论文数 ÷ 当前范围 {publicationCount} 篇论文。同一论文可关联多个种类，各项占比之和可超过 100%。</span></p>
    <div className="sg-funding-layout"><section aria-label="粗分类论文覆盖">
      <h3 className="sg-funding-list-title">粗分类论文覆盖 <small>按项目种类分类聚合 · 类内去重</small></h3>
      {categories === undefined ? <AnalysisEmpty text="分类聚合数据暂不可用，请刷新分析。" /> : categories.length === 0 ? <AnalysisEmpty text="当前范围没有项目分类覆盖。" /> : <FundingCoverageList publicationCount={publicationCount} items={categories.map(item => ({ id: item.object_id, name: item.name, count: item.linked_project_count, source: item.funding_agency ?? '', kinds: item.kinds ?? [] }))} />}
    </section><div>
    {programs.length > 0 && <section aria-label="InCites 资助机构论文覆盖"><h3 className="sg-funding-list-title">InCites 资助机构论文覆盖</h3><FundingCoverageList publicationCount={publicationCount} items={programs.map((item) => ({ id: item.object_id, name: item.name, count: item.linked_project_count, source: item.funding_agency ?? 'InCites 资助机构' }))} /></section>}
    {candidatePrograms.length === 0 ? <AnalysisEmpty text="当前范围没有从全文提取的项目资助关系。" /> : <section aria-label="项目种类论文覆盖">
      <h3 className="sg-funding-list-title">项目种类论文覆盖 <small>共 {includedProjectKinds} 类，{individualKinds.length === includedProjectKinds ? '全部展示' : `当前展示 ${individualKinds.length} 类`}</small></h3>
      <FundingCoverageList publicationCount={publicationCount} items={individualKinds.map((item) => ({ id: item.object_id, name: item.name, count: item.linked_item_count, projects: item.projects ?? [], source: '全文提取' }))} />
      {other && <p className="sg-funding-note sg-funding-other">其余 {Math.max(0, includedProjectKinds - individualKinds.length)} 个种类未逐项展示。“其他”的跨种类去重论文数尚未提供，因此不绘制合并覆盖率，避免将累计篇次误作论文数。</p>}
    </section>}
    </div></div>
  </section>;
}

export function FundingCoverageList({ items, publicationCount }: { items: { id: string; name: string; count: number; source: string; projects?: FundingShare['projects']; kinds?: FundingShare['kinds'] }[]; publicationCount: number }) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  return <div className="sg-distribution-list sg-funding-coverage-list">{items.map((item, index) => {
    const share = publicationCount > 0 ? item.count / publicationCount : null;
    const open = expanded.has(item.id);
    const children = item.kinds ?? item.projects;
    const unit = item.kinds ? '项目种类' : '项目';
    const detailId = `funding-projects-${encodeURIComponent(item.id)}`;
    return <Fragment key={item.id}><article tabIndex={children ? undefined : 0} aria-label={`${item.name}，${item.count} 篇论文，占当前范围 ${share === null ? '无法计算' : formatPercent(share)}`} style={{ '--funding-color': fundingColor(index, item.id), '--coverage-width': `${share === null ? 0 : Math.min(share * 100, 100)}%` } as React.CSSProperties}>
      <span><b>{index + 1}</b><strong>{children ? <button className="sg-funding-expand" aria-expanded={open} aria-controls={detailId} onClick={() => setExpanded(current => { const next = new Set(current); if (next.has(item.id)) next.delete(item.id); else next.add(item.id); return next; })}><span aria-hidden="true">{open ? '▾' : '▸'}</span> {item.name}（{children.length} 个{unit}）</button> : item.name}</strong>{item.source && <small>{item.source}</small>}</span><em>{item.count} 篇论文</em><code>{share === null ? '—' : formatPercent(share)}</code>
    </article>{item.kinds && <section id={detailId} hidden={!open} className="sg-funding-project-details" aria-label={`${item.name}项目种类明细`}>
      <p>当前分析范围内全部 {item.kinds.length} 个项目种类</p>
      <ul>{item.kinds.map(kind => <li key={kind.object_id}><Link to={`/outputs/${kind.object_id}`}>{kind.name}</Link><small>{kind.project_count} 个具体项目 · {kind.publication_count} 篇论文</small></li>)}</ul>
    </section>}{!item.kinds && item.projects && <section id={detailId} hidden={!open} className="sg-funding-project-details" aria-label={`${item.name}项目明细`}>
      <p>当前分析范围内全部 {item.projects.length} 个具体项目（按项目去重）</p>
      {item.projects.length === 0 ? <p>当前分类暂无项目。</p> : <ul>{item.projects.map(project => <li key={project.object_id}><Link to={`/outputs/${project.object_id}`}>{project.name}</Link><small>项目种类：{project.kind_name}</small><small>编号：{project.grant_number?.trim() ? project.grant_number : '未记录（无编号项目）'}</small></li>)}</ul>}
    </section>}</Fragment>;
  })}</div>;
}

function InstitutionCollaborationPanel({ network, settings, onApply }: { network: CollaborationNetwork; settings:InstitutionSettings; onApply:(value:InstitutionSettings)=>void }) {
  const [minimum, setMinimum] = useWorkbenchPreference('institution.minimum', 2);
  const [view, setView] = useWorkbenchPreference<GraphAnalysisQuery>('institution.view', {edgeLimit:120});
  const eligible = (network.exploration_edges ?? network.edges).filter(e => e.publication_count >= minimum);
  const matched = eligible.filter(e => !view.peopleFocusId || e.source_id === view.peopleFocusId || e.target_id === view.peopleFocusId);
  const edges = matched.slice(0, view.edgeLimit ?? 120);
  const ids = new Set(edges.flatMap(e => [e.source_id,e.target_id]));
  const communities = new Map(network.assessment?.communities.flatMap(c => c.member_ids.map(id => [id, c.community_id] as const)) ?? []);
  const display: CollaborationNetwork = {...network, edges,
    nodes: [...new Map([...network.nodes, ...(network.directory ?? [])].map(n => [n.object_id, n])).values()].filter(n => ids.has(n.object_id)).map(n => ({...n, community_id:communities.get(n.object_id) ?? null})),
    total_node_count:new Set(eligible.flatMap(e => [e.source_id,e.target_id])).size,
    total_edge_count:eligible.length, matched_node_count:new Set(matched.flatMap(e => [e.source_id,e.target_id])).size,
    matched_edge_count:matched.length, displayed_edge_count:edges.length, truncated:matched.length>edges.length};
  return <><InstitutionGranularityControls options={(network.institution_options ?? []).flatMap(o => typeof o.id === 'string' && typeof o.name === 'string' && typeof o.root_id === 'string' && typeof o.level === 'number' ? [{ id: o.id, name: o.name, root_id: o.root_id, level: o.level }] : [])} applied={settings} onApply={onApply} context={network.aggregation_context ?? {}}/><CollaborationPanel title="机构合作关系" description="按已应用的分析粒度归并署名机构，同篇去重后建立合作网络；层级关系不计入合作。" icon="institution" network={display} minimum={minimum} onMinimumChange={setMinimum} view={view} onViewChange={setView} /></>;
}

function CollaborationPanel({ title, description, icon, network, minimum, onMinimumChange, view, onViewChange }: { title: string; description: string; icon: 'people' | 'institution'; network: CollaborationNetwork; minimum: number; onMinimumChange: (value: number) => void; view?: GraphAnalysisQuery; onViewChange?: (value: GraphAnalysisQuery) => void }) {
  const [search, setSearch] = useSessionState(`collaboration.${network.assessment?.entity_type ?? 'person'}.search`,'');
  const [edgeDraft, setEdgeDraft] = useState<number | string>(view?.edgeLimit ?? 120);
  const validEdgeLimit = String(edgeDraft).trim() !== '' && Number.isSafeInteger(Number(edgeDraft)) && Number(edgeDraft) >= 1;
  const [page, setPage] = useSessionState(`collaboration.${network.assessment?.entity_type ?? 'person'}.page`,1);
  const [pageSize, setPageSize] = useSessionState(`collaboration.${network.assessment?.entity_type ?? 'person'}.pageSize`,20);
  const directory = network.directory ?? [];
  const institutions = [...new Map(directory.flatMap((person) => Object.entries(person.organizations ?? {}))).entries()].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
  const filtered = directory.filter((person) => `${person.name} ${Object.values(person.organizations ?? {}).join(' ')}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()) && (!view?.peopleOrganizationId || view.peopleOrganizationId in (person.organizations ?? {})));
  const safePage = Math.min(page, Math.max(1, Math.ceil(filtered.length / pageSize)));
  const graphKey = `${icon}-${minimum}-${view?.edgeLimit}-${view?.peopleFocusId}-${view?.peopleOrganizationId}-${view?.peopleIncludeExternal}-${network.nodes.map((node) => node.object_id).join(',')}`;
  const explorationControls = onViewChange && <div className="sg-people-controls">
      {icon === 'people' && <ComboBox id="people-organization" titleText="探索署名机构" placeholder="全部机构，可输入检索" items={institutions} shouldFilterItem={({ item, inputValue }) => item.name.toLocaleLowerCase().includes((inputValue ?? "").toLocaleLowerCase())} itemToString={(item) => item?.name ?? ''} selectedItem={institutions.find((item) => item.id === view?.peopleOrganizationId) ?? null} onChange={({ selectedItem }) => { setPage(1); onViewChange({ ...view, peopleOrganizationId: selectedItem?.id }); }} />}
      <ComboBox id={`${icon}-people-focus`} titleText={icon === 'people' ? "探索学者的一度合作" : "探索机构的一度合作"} placeholder={icon === 'people' ? "全部人员，可输入姓名" : "全部机构，可输入名称"} items={directory.filter((person) => !view?.peopleOrganizationId || view.peopleIncludeExternal === true || view.peopleOrganizationId in (person.organizations ?? {}))} shouldFilterItem={({ item, inputValue }) => item.name.toLocaleLowerCase().includes((inputValue ?? "").toLocaleLowerCase())} itemToString={(item) => item?.name ?? ''} selectedItem={directory.find((item) => item.object_id === view?.peopleFocusId) ?? null} onChange={({ selectedItem }) => onViewChange({ ...view, peopleFocusId: selectedItem?.object_id })} />
      <form className="sg-people-limit" onSubmit={(event) => { event.preventDefault(); if (validEdgeLimit) onViewChange({ ...view, edgeLimit: Number(edgeDraft) }); }}>
        <NumberInput id={`${icon}-people-edge-limit`} label="最多显示连线" min={1} step={1} allowEmpty value={edgeDraft} invalid={!validEdgeLimit} invalidText="请输入大于或等于 1 的整数" onChange={(_, { value }) => setEdgeDraft(value)} />
        <Button type="submit" size="sm" kind="tertiary" disabled={!validEdgeLimit}>应用连线数量</Button>
      </form>
      <Button className="sg-people-reset" kind="ghost" size="sm" onClick={() => { setEdgeDraft(120); onViewChange({ edgeLimit: 120 }); }}>重置图谱探索</Button>
      {icon === 'people' && <div className="sg-people-external"><Checkbox id="people-include-external" labelText="包含外部合作者" disabled={!view?.peopleOrganizationId} checked={Boolean(view?.peopleIncludeExternal)} onChange={(_, { checked }) => onViewChange({ ...view, peopleIncludeExternal: checked })} /></div>}
      <p className="sg-people-limit-hint"><Information size={16} aria-hidden="true" />{Number(edgeDraft) > 1000 ? '大量连线可能导致加载较慢、图谱拥挤；实际按可用关系数展示。' : '连线数量可输入任意正整数，填写后点击“应用连线数量”。'}</p>
    </div>;
  const networkSummary = icon === 'people' ? <div className="sg-network-summary"><span>范围内关联人员 <strong>{network.scope_node_count ?? directory.length}</strong></span><span>达到合作阈值 <strong>{network.total_node_count}</strong> 人</span><span>探索结果 <strong>{network.matched_node_count ?? network.total_node_count}</strong> 人 / <strong>{network.matched_edge_count ?? network.total_edge_count}</strong> 组合作</span><span>图中载入 <strong>{network.nodes.length}</strong> 人 / <strong>{network.displayed_edge_count}</strong> 条连线{network.truncated ? '（按共同论文数截取，非全部人员）' : ''}</span></div> : <div className="sg-network-summary"><span>范围内关联机构 <strong>{network.scope_node_count ?? directory.length}</strong> 个；达到合作阈值 <strong>{network.total_node_count}</strong> 个</span><span><strong>{network.matched_node_count}</strong> 个探索机构 / <strong>{network.matched_edge_count}</strong> 组合作</span><span>图中载入 <strong>{network.nodes.length}</strong> 个机构 / 当前显示 <strong>{network.displayed_edge_count}</strong> 条边{network.truncated ? '（按强度截取）' : ''}</span></div>;
  return <section className="sg-analysis-panel">
    <header className="sg-analysis-panel-heading"><div>{icon === 'people' ? <UserMultiple size={24} /> : <Building size={24} />}<span><h2>{title}</h2><p>{description}</p></span></div><div className="sg-collaboration-filter"><Dropdown id={`${icon}-minimum`} label="合作强度范围" titleText="显示范围" items={minimumOptions} itemToString={(item) => item?.label ?? ''} selectedItem={minimumOptions.find((item) => item.id === minimum) ?? minimumOptions[0]} onChange={({ selectedItem }) => { if (selectedItem) onMinimumChange(selectedItem.id); }} /></div></header>


    {network.edges.length === 0 ? <>{explorationControls}{networkSummary}<AnalysisEmpty text={icon === 'people' && (view?.peopleOrganizationId || view?.peopleFocusId) ? '当前机构、学者及合作条件下暂无合作关系。已保留所选条件，可调整机构、学者、外部合作者开关或共同论文阈值。' : `当前范围内没有${title}数据，可降低共同论文阈值。`} /></> : <CollaborationGraph key={graphKey} network={network} explorationControls={explorationControls} networkSummary={networkSummary} />}
    <p className="sg-metric-note"><Information size={16} />{network.metric_note}{icon === 'people' && ' 人数按已关联的人员对象去重，并非本校教职工总数；机构来自当前范围论文的署名记录；默认仅显示机构内合作，开启“包含外部合作者”后扩展到对外合作。图谱探索不改变上方论文分析范围。'}</p>
    {network.assessment && <CooperationAssessmentPanel assessment={network.assessment} directory={directory} />}
    {onViewChange && <section className="sg-people-directory">
      <h3>{icon === 'people' ? '关联人员目录' : '关联机构目录'}</h3><p>包含未达到合作阈值或未进入图谱的节点。选择“查看合作”可探索其直接合作关系。</p>
      <TextInput id={`${icon}-people-directory-search`} labelText={icon === 'people' ? "搜索人员或署名机构" : "搜索机构"} placeholder="输入名称" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} />
      <div className="sg-people-table-wrap"><table className="sg-people-table"><thead><tr><th>{icon === 'people' ? '学者' : '机构'}</th>{icon === 'people' && <th>论文署名机构</th>}<th>范围内论文数</th><th>操作</th></tr></thead><tbody>{filtered.slice((safePage - 1) * pageSize, safePage * pageSize).map((person) => <tr key={person.object_id}><td><>{icon === 'people' ? <Link to={`/scholars/${person.object_id}`}>{person.name}</Link> : <InstitutionName id={person.object_id} name={person.name} context={network.aggregation_context as InstitutionContext}/>}</></td>{icon === 'people' && <td>{Object.values(person.organizations ?? {}).length > 2 ? <><span>{Object.values(person.organizations ?? {}).slice(0, 2).join('；')}</span><details><summary>查看全部 {Object.keys(person.organizations ?? {}).length} 个署名机构</summary>{Object.values(person.organizations ?? {}).join('；')}</details></> : Object.values(person.organizations ?? {}).join('；') || '尚未关联署名机构'}</td>}<td>{person.publication_count}</td><td><Button kind="ghost" size="sm" onClick={() => onViewChange({ ...view, peopleFocusId: person.object_id })}>查看合作</Button></td></tr>)}</tbody></table></div>
      {filtered.length === 0 && <AnalysisEmpty text="没有匹配的人员，请调整搜索词或机构。" />}
      <Pagination page={safePage} pageSize={pageSize} pageSizes={[20, 50, 100]} totalItems={filtered.length} itemsPerPageText={icon === 'people' ? "每页人数" : "每页机构数"} onChange={({ page: nextPage, pageSize: nextSize }) => { setPage(nextPage); setPageSize(nextSize); }} />
    </section>}
  </section>;
}

function CollaborationGraph({ network, explorationControls, networkSummary }: { network: CollaborationNetwork; explorationControls: ReactNode; networkSummary: ReactNode }) {
  const initialHighlightedEdgeId = network.edges.find((edge) => edge.highlighted)?.edge_id ?? null;
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(initialHighlightedEdgeId ? null : network.nodes[0]?.object_id ?? null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(initialHighlightedEdgeId);
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(() => new Set());
  const [membersClusterId, setMembersClusterId] = useState<number | null>(null);
  const [clusterMinimum, setClusterMinimum] = useWorkbenchPreference(network.assessment?.entity_type === 'organization' || network.nodes[0]?.node_type === 'organization' ? 'institution.clusterMinimum' : 'people.clusterMinimum', 1);
  const [clusterDraft, setClusterDraft] = useState<number | string>(clusterMinimum);
  const validClusterMinimum = String(clusterDraft).trim() !== '' && Number.isSafeInteger(Number(clusterDraft)) && Number(clusterDraft) >= 1;
  const isPeopleNetwork = network.assessment?.entity_type !== 'organization' && network.nodes.some((node) => node.node_type === 'person');
  const unit = isPeopleNetwork ? '人' : '个机构';
  const [positionOverrides, setPositionOverrides] = useState<Map<string, AnalysisPoint>>(() => new Map());
  const [zoom, setZoom] = useState(1);
  const [expandedView, setExpandedView] = useState(false);
  const [draggingCanvas, setDraggingCanvas] = useState(false);
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [draggingClusterId, setDraggingClusterId] = useState<number | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [deleteCandidate, setDeleteCandidate] = useState<CollaborationNode | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const viewRef = useRef<AnalysisViewState>({ x: 0, y: 0, zoom: 1 });
  const canvasDragRef = useRef<{ pointerId: number; x: number; y: number; originX: number; originY: number } | null>(null);
  const nodeDragRef = useRef<{ pointerId: number; objectId: string; start: GraphPointer; origin: AnalysisPoint; element: SVGGElement } | null>(null);
  const clusterDragRef = useRef<{ pointerId: number; cluster: number; start: GraphPointer; origins: Map<string, AnalysisPoint>; element: SVGGraphicsElement } | null>(null);
  const basePositions = useMemo(() => graphPositions(network.nodes, network.edges), [network.nodes, network.edges]);
  const graphExtent = useMemo(() => {
    const bounds = clusterEnvelopes(basePositions);
    return { width: Math.max(ANALYSIS_GRAPH_WIDTH, ...bounds.map((item) => item.cx + item.rx + 64)), height: Math.max(ANALYSIS_GRAPH_HEIGHT, ...bounds.map((item) => item.cy + item.ry + 64)) };
  }, [basePositions]);
  const clusterSizes = useMemo(() => {
    if (network.assessment) return new Map(network.assessment.communities.map((c) => [c.community_id, c.member_ids.length]));
    const sizes = new Map<number, number>();
    basePositions.forEach((point) => sizes.set(point.cluster, (sizes.get(point.cluster) ?? 0) + 1));
    return sizes;
  }, [basePositions, network.assessment]);
  const filteredClusterIds = useMemo(() => new Set([...clusterSizes].filter(([, size]) => size < clusterMinimum).map(([id]) => id)), [clusterSizes, clusterMinimum]);
  const visibleNodes = useMemo(() => network.nodes.filter((node) => !hiddenIds.has(node.object_id) && !filteredClusterIds.has(basePositions.get(node.object_id)?.cluster ?? -1)), [hiddenIds, network.nodes, filteredClusterIds, basePositions]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.object_id)), [visibleNodes]);
  const visibleEdges = useMemo(() => network.edges.filter((edge) => visibleIds.has(edge.source_id) && visibleIds.has(edge.target_id)), [network.edges, visibleIds]);
  const positions = useMemo(() => {
    const result = new Map([...basePositions].filter(([id]) => visibleIds.has(id)));
    positionOverrides.forEach((point, objectId) => { if (result.has(objectId)) result.set(objectId, point); });
    return result;
  }, [positionOverrides, basePositions, visibleIds]);
  const envelopes = useMemo(() => clusterEnvelopes(positions), [positions]);
  const selectedNode = visibleNodes.find((node) => node.object_id === selectedNodeId);
  const selectedEdge = visibleEdges.find((edge) => edge.edge_id === selectedEdgeId);
  const incidentEdges = selectedNodeId ? visibleEdges.filter((edge) => edge.source_id === selectedNodeId || edge.target_id === selectedNodeId) : [];
  const incident = new Set(incidentEdges.map((edge) => edge.edge_id));
  const visibleClusterCounts = new Map<number, number>();
  visibleNodes.forEach((node) => {
    const cluster = basePositions.get(node.object_id)?.cluster;
    if (cluster != null) visibleClusterCounts.set(cluster, (visibleClusterCounts.get(cluster) ?? 0) + 1);
  });
  const membersCommunity = network.assessment?.communities.find((c) => c.community_id === membersClusterId);
  const directoryById = new Map((network.directory ?? []).map((node) => [node.object_id, node]));
  const nodesById = new Map(network.nodes.map((node) => [node.object_id, node]));
  const renderedEdges = [...visibleEdges].reverse();
  const sourceEdges = selectedNode ? incidentEdges : selectedEdge ? [selectedEdge] : [];

  const applyView = useCallback(() => {
    const view = viewRef.current;
    const svg = svgRef.current;
    if (!svg) return;
    const bounds = svg.getBoundingClientRect();
    const baseScale = Math.min(bounds.width / graphExtent.width, bounds.height / graphExtent.height) || 1;
    const width = graphExtent.width / view.zoom;
    const height = graphExtent.height / view.zoom;
    const x = (graphExtent.width - width) / 2 - view.x / (baseScale * view.zoom);
    const y = (graphExtent.height - height) / 2 - view.y / (baseScale * view.zoom);
    svg.setAttribute('viewBox', `${x} ${y} ${width} ${height}`);
  }, [graphExtent]);

  useEffect(() => {
    applyView();
    if (typeof ResizeObserver === 'undefined' || !svgRef.current) return;
    const observer = new ResizeObserver(applyView);
    observer.observe(svgRef.current);
    return () => observer.disconnect();
  }, [applyView]);

  useEffect(() => {
    if (!expandedView) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpandedView(false); };
    document.addEventListener('keydown', close);
    return () => { document.body.style.overflow = previousOverflow; document.removeEventListener('keydown', close); };
  }, [expandedView]);

  const updateZoom = (next: number) => {
    const normalized = Math.min(6, Math.max(.3, Number(next.toFixed(2))));
    viewRef.current.zoom = normalized;
    setZoom(normalized);
    applyView();
  };
  const resetView = () => {
    viewRef.current = { x: 0, y: 0, zoom: 1 };
    setZoom(1);
    setPositionOverrides(new Map());
    applyView();
  };
  const startPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const clusterElement = (event.target as Element).closest<SVGGraphicsElement>('[data-cluster-envelope="true"], [data-cluster-handle="true"]');
    if (clusterElement) {
      const cluster = Number(clusterElement.dataset.clusterId);
      const start = clientToGraph(svgRef.current, event.clientX, event.clientY);
      if (!Number.isFinite(cluster) || !start) return;
      event.preventDefault(); event.stopPropagation();
      const origins = new Map(Array.from(positions.entries()).filter(([, point]) => point.cluster === cluster));
      clusterElement.setPointerCapture(event.pointerId);
      clusterDragRef.current = { pointerId: event.pointerId, cluster, start, origins, element: clusterElement };
      setDraggingClusterId(cluster);
      return;
    }
    const node = (event.target as Element).closest<SVGGElement>('[data-analysis-node="true"]');
    if (node) {
      const objectId = node.dataset.objectId;
      const origin = objectId ? positions.get(objectId) : undefined;
      const start = clientToGraph(svgRef.current, event.clientX, event.clientY);
      if (!objectId || !origin || !start) return;
      event.preventDefault();
      node.setPointerCapture(event.pointerId);
      nodeDragRef.current = { pointerId: event.pointerId, objectId, start, origin, element: node };
      setSelectedNodeId(objectId); setSelectedEdgeId(null); setDraggingNodeId(objectId);
      return;
    }
    canvasDragRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, originX: viewRef.current.x, originY: viewRef.current.y };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDraggingCanvas(true);
  };
  const movePointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const clusterDrag = clusterDragRef.current;
    if (clusterDrag?.pointerId === event.pointerId) {
      const current = clientToGraph(svgRef.current, event.clientX, event.clientY);
      if (!current) return;
      const delta = { x: current.x - clusterDrag.start.x, y: current.y - clusterDrag.start.y };
      setPositionOverrides((overrides) => {
        const next = new Map(overrides);
        clusterDrag.origins.forEach((point, objectId) => next.set(objectId, { ...point, x: point.x + delta.x, y: point.y + delta.y }));
        return next;
      });
      return;
    }
    const nodeDrag = nodeDragRef.current;
    if (nodeDrag?.pointerId === event.pointerId) {
      const current = clientToGraph(svgRef.current, event.clientX, event.clientY);
      if (!current) return;
      const point = { ...nodeDrag.origin, x: nodeDrag.origin.x + current.x - nodeDrag.start.x, y: nodeDrag.origin.y + current.y - nodeDrag.start.y };
      setPositionOverrides((current) => new Map(current).set(nodeDrag.objectId, point));
      return;
    }
    const canvasDrag = canvasDragRef.current;
    if (canvasDrag?.pointerId !== event.pointerId) return;
    viewRef.current.x = canvasDrag.originX + event.clientX - canvasDrag.x;
    viewRef.current.y = canvasDrag.originY + event.clientY - canvasDrag.y;
    applyView();
  };
  const endPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const clusterDrag = clusterDragRef.current;
    if (clusterDrag?.pointerId === event.pointerId) {
      if (clusterDrag.element.hasPointerCapture(event.pointerId)) clusterDrag.element.releasePointerCapture(event.pointerId);
      clusterDragRef.current = null; setDraggingClusterId(null); return;
    }
    const nodeDrag = nodeDragRef.current;
    if (nodeDrag?.pointerId === event.pointerId) {
      if (typeof nodeDrag.element.hasPointerCapture === 'function' && nodeDrag.element.hasPointerCapture(event.pointerId)) nodeDrag.element.releasePointerCapture(event.pointerId);
      nodeDragRef.current = null; setDraggingNodeId(null); return;
    }
    if (canvasDragRef.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    canvasDragRef.current = null; setDraggingCanvas(false);
  };
  const removeNode = () => {
    if (!deleteCandidate) return;
    const objectId = deleteCandidate.object_id;
    setHiddenIds((current) => new Set(current).add(objectId));
    setPositionOverrides((current) => { const next = new Map(current); next.delete(objectId); return next; });
    setSelectedNodeId(visibleNodes.find((node) => node.object_id !== objectId)?.object_id ?? null);
    setSelectedEdgeId(null); setDeleteCandidate(null); setEvidenceOpen(false);
  };
  const workspaceClass = `sg-collaboration-shell ${expandedView ? 'is-expanded' : ''}`;

  return <>
  <div className={workspaceClass} role={expandedView ? 'dialog' : undefined} aria-modal={expandedView || undefined} aria-label={expandedView ? '合作关系图放大视图' : undefined}>
    <div className="sg-combined-controls">
    {explorationControls}
    {<div className="sg-cluster-filter">
      <form onSubmit={(event) => { event.preventDefault(); if (validClusterMinimum) { setClusterMinimum(Number(clusterDraft)); setSelectedNodeId(null); setSelectedEdgeId(null); setEvidenceOpen(false); } }}>
        <NumberInput id={`${isPeopleNetwork ? 'people' : 'institution'}-cluster-minimum`} label={isPeopleNetwork ? "合作簇最少人数" : "合作簇最少机构数"} min={1} step={1} allowEmpty value={clusterDraft} invalid={!validClusterMinimum} invalidText="请输入大于或等于 1 的整数" onChange={(_, { value }) => setClusterDraft(value)} />
        <Button type="submit" kind="tertiary" size="sm" disabled={!validClusterMinimum}>应用簇过滤</Button>
        <Button kind="ghost" size="sm" onClick={() => { setClusterDraft(1); setClusterMinimum(1); }}>显示全部合作簇</Button>
      </form>
      <p className="sg-metric-note"><Information size={16} />按完整分析范围的合作簇总成员数过滤；1 表示不过滤。图中可能仅显示簇的部分成员，调整显示连线数与探索条件不会重新分簇。</p>
      {visibleNodes.length === 0 && <AnalysisEmpty text="没有符合条件的合作簇，请降低最少成员数或显示全部合作簇。" />}
    </div>}
    </div>
    <div className="sg-combined-status">{networkSummary}{<p className="sg-cluster-filter-summary" role="status">共 {clusterSizes.size} 个合作簇，已过滤 {filteredClusterIds.size} 个；当前可见 {visibleNodes.length} {unit} / {visibleEdges.length} 条连线。</p>}</div>
    <div className="sg-collaboration-toolbar"><div><Button kind="ghost" hasIconOnly renderIcon={ZoomOut} iconDescription="缩小合作图谱" disabled={zoom <= .3} onClick={() => updateZoom(zoom - .1)} /><span className="sg-collaboration-zoom-value">{Math.round(zoom * 100)}%</span><Button kind="ghost" hasIconOnly renderIcon={ZoomIn} iconDescription="放大合作图谱" disabled={zoom >= 6} onClick={() => updateZoom(zoom + .1)} /><Button kind="ghost" hasIconOnly renderIcon={CenterToFit} iconDescription="重置合作图谱位置" onClick={resetView} />{hiddenIds.size > 0 && <Button kind="ghost" size="sm" renderIcon={Undo} onClick={() => setHiddenIds(new Set())}>恢复已移除节点（{hiddenIds.size}）</Button>}</div><Button kind="ghost" size="sm" renderIcon={expandedView ? Minimize : Maximize} onClick={() => setExpandedView((value) => !value)}>{expandedView ? '退出放大' : '放大图谱区域'}</Button></div>
    <div className="sg-network-help"><span>拖拽空白区域移动画布</span><span>节点可自由调整，包围圈随之变化</span><span>拖拽虚线区域或移动把手移动整个簇</span><span>重置可恢复初始布局</span><span>点击节点或连线查看依据</span></div>
    <div className="sg-collaboration-legend">{collaborationLegend(visibleNodes).map((item) => <span key={item.key} className={item.className}><i />{item.label}</span>)}</div>
    <div className="sg-collaboration-workspace">
    <div className={`sg-collaboration-canvas ${draggingCanvas ? 'is-dragging' : ''}`} aria-label="可拖拽的合作关系图" onPointerDown={startPointer} onPointerMove={movePointer} onPointerUp={endPointer} onPointerCancel={endPointer} onDoubleClick={(event) => { if (!(event.target as Element).closest('[data-analysis-node="true"], .sg-collaboration-edge, [data-cluster-envelope="true"]')) setExpandedView(true); }}><div className="sg-collaboration-surface"><svg ref={svgRef} viewBox={`0 0 ${graphExtent.width} ${graphExtent.height}`} role="img" aria-label="合作关系图">
      {envelopes.map((envelope) => <ellipse key={envelope.cluster} data-cluster-envelope="true" data-cluster-id={envelope.cluster} className={`sg-cluster-envelope ${draggingClusterId === envelope.cluster ? 'is-dragging' : ''}`} cx={envelope.cx} cy={envelope.cy} rx={envelope.rx} ry={envelope.ry} />)}
      {network.assessment && envelopes.map((e) => <g key={`label-${e.cluster}`} className="sg-cluster-members-link" role="button" tabIndex={0} aria-label={`查看簇 ${e.cluster + 1} 全部成员`} onPointerDown={(event) => event.stopPropagation()} onClick={() => setMembersClusterId(e.cluster)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setMembersClusterId(e.cluster); } }}><text x={e.cx} y={e.cy - e.ry + 16} textAnchor="middle" fontSize={12} fill="#005d5d">簇 {e.cluster + 1} · 当前显示 {visibleClusterCounts.get(e.cluster) ?? 0} {unit} / 全部 {clusterSizes.get(e.cluster)} {unit}</text><text x={e.cx} y={e.cy - e.ry + 32} textAnchor="middle" fontSize={11} fill="#005d5d">查看全部成员</text></g>)}
      {renderedEdges.map((edge) => { const left = positions.get(edge.source_id); const right = positions.get(edge.target_id); if (!left || !right) return null; const active = edge.edge_id === selectedEdgeId || incident.has(edge.edge_id); const midpoint = { x: (left.x + right.x) / 2, y: (left.y + right.y) / 2 }; return <g key={edge.edge_id} className={`sg-collaboration-edge ${left.cluster === right.cluster ? 'intra-cluster' : 'inter-cluster'} ${edge.highlighted ? 'highlighted' : ''} ${active ? 'active' : ''}`} role="button" tabIndex={0} aria-label={`${nodesById.get(edge.source_id)?.name}与${nodesById.get(edge.target_id)?.name}共同发表${edge.publication_count}篇论文`} onClick={() => { setSelectedEdgeId(edge.edge_id); setSelectedNodeId(null); }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedEdgeId(edge.edge_id); setSelectedNodeId(null); } }}><line x1={left.x} y1={left.y} x2={right.x} y2={right.y} /><line className="hit" x1={left.x} y1={left.y} x2={right.x} y2={right.y} /><rect x={midpoint.x - 12} y={midpoint.y - 10} width="24" height="18" rx="2" /><text x={midpoint.x} y={midpoint.y + 3}>{edge.publication_count}</text></g>; })}
      {envelopes.map((envelope) => <g key={`handle-${envelope.cluster}`} data-cluster-handle="true" data-cluster-id={envelope.cluster} className={`sg-cluster-drag-handle ${draggingClusterId === envelope.cluster ? 'is-dragging' : ''}`} transform={`translate(${envelope.cx - envelope.rx} ${envelope.cy})`} role="button" aria-label={`移动第 ${envelope.cluster + 1} 个关系簇`}><title>拖动整个关系簇</title><circle r="10" /><path d="M-6 0H6M0-6V6M-6 0l2-2M-6 0l2 2M6 0L4-2M6 0L4 2M0-6l-2 2M0-6l2 2M0 6l-2-2M0 6l2-2" /></g>)}
      {visibleNodes.map((node) => { const point = positions.get(node.object_id); if (!point) return null; const selected = node.object_id === selectedNodeId; const radius = point.role === 'core' ? (node.node_type === 'organization' ? 29 : 25) : (node.node_type === 'organization' ? 22 : 19); return <g key={node.object_id} data-analysis-node="true" data-object-id={node.object_id} transform={`translate(${point.x} ${point.y})`} className={`sg-collaboration-node type-${node.node_type} role-${point.role} cluster-${point.cluster} ${selected ? 'selected' : ''} ${draggingNodeId === node.object_id ? 'is-node-dragging' : ''} group-${node.group_key ?? 'default'}`} role="button" tabIndex={0} aria-label={`${node.name}，关联${node.publication_count}篇论文`} onClick={() => { setSelectedNodeId(node.object_id); setSelectedEdgeId(null); }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedNodeId(node.object_id); setSelectedEdgeId(null); } }}><circle r={radius} /><text y={radius + 16}>{truncate(node.name, point.role === 'core' ? 14 : 10)}</text></g>; })}
    </svg></div></div>
    <aside className="sg-collaboration-detail">
      {selectedNode && <><span>{selectedNode.node_type === 'person' ? '人员节点' : '机构节点'}</span><h3>{selectedNode.name}</h3><dl><div><dt>参与论文</dt><dd>{selectedNode.publication_count} 篇</dd></div><div><dt>当前可见合作</dt><dd>{incident.size} 组</dd></div><div><dt>当前合作的去重论文依据</dt><dd>{new Set(incidentEdges.flatMap((edge) => edge.evidence_publications.map((p) => p.object_id))).size} 篇</dd></div></dl>{selectedNode.node_type === 'person' ? <Link to={`/scholars/${selectedNode.object_id}`}>进入学者详情</Link> : <InstitutionName id={selectedNode.object_id} name={selectedNode.name} context={network.aggregation_context as InstitutionContext}/>}</>}
      {selectedEdge && <><span>{selectedEdge.collaboration_kind ?? '论文合作关系'}</span><h3>{nodesById.get(selectedEdge.source_id)?.name}<i>与</i>{nodesById.get(selectedEdge.target_id)?.name}</h3><strong className="sg-edge-strength">{selectedEdge.publication_count}<small>篇共同论文</small></strong><div className="sg-edge-evidence"><h4>关系依据（全部共同论文）</h4>{selectedEdge.evidence_publications.map((publication) => <Link key={publication.object_id} to={`/outputs/${publication.object_id}`}>{publication.title}</Link>)}</div></>}
      {!selectedNode && !selectedEdge && <p>选择节点或连线查看详情。</p>}
      {Boolean(selectedNode ?? selectedEdge) && <Button kind="tertiary" size="sm" onClick={() => setEvidenceOpen(true)}>查看关系来源</Button>}
      <Button kind="danger--tertiary" size="sm" renderIcon={TrashCan} disabled={!selectedNode} onClick={() => selectedNode && setDeleteCandidate(selectedNode)}>从当前图中移除</Button>
      <small className="sg-node-remove-note">移除仅影响当前分析视图，不删除系统数据。</small>
    </aside>
    </div>
  </div>
  {evidenceOpen && Boolean(selectedNode ?? selectedEdge) && <CollaborationEvidenceDrawer selectedNode={selectedNode} selectedEdge={selectedEdge} edges={sourceEdges} nodesById={nodesById} onClose={() => setEvidenceOpen(false)} />}
  <Modal open={Boolean(membersCommunity)} passiveModal modalHeading={`簇 ${(membersClusterId ?? 0) + 1} · 全部成员`} onRequestClose={() => setMembersClusterId(null)}>
    {membersCommunity && <><p>当前显示 {visibleClusterCounts.get(membersCommunity.community_id) ?? 0} {unit} / 全部 {membersCommunity.member_ids.length} {unit}。以下包含未进入当前图谱的成员；查看名单不会改变筛选或分簇。</p><ul className="sg-cluster-members-list">{membersCommunity.member_ids.map((id) => <li key={id}>{isPeopleNetwork ? <Link to={`/scholars/${id}`}>{directoryById.get(id)?.name??id}</Link> : <InstitutionName id={id} name={directoryById.get(id)?.name??id} context={network.aggregation_context as InstitutionContext}/>}<span>{visibleIds.has(id) ? '当前图中已显示' : '当前图中未显示'}</span></li>)}</ul></>}
  </Modal>
  <Modal open={Boolean(deleteCandidate)} danger modalHeading="从当前分析图移除节点" primaryButtonText="从当前视图移除" secondaryButtonText="取消" onRequestClose={() => setDeleteCandidate(null)} onRequestSubmit={removeNode}><p>将“{deleteCandidate?.name}”及其当前可见合作边从本次分析视图中隐藏，不会删除 PostgreSQL、HugeGraph 或检索索引中的记录。</p></Modal>
  </>;
}

function CollaborationEvidenceDrawer({ selectedNode, selectedEdge, edges, nodesById, onClose }: { selectedNode?: CollaborationNode | undefined; selectedEdge?: CollaborationEdge | undefined; edges: CollaborationEdge[]; nodesById: Map<string, CollaborationNode>; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [onClose]);
  const title = selectedNode?.name ?? `${nodesById.get(selectedEdge?.source_id ?? '')?.name ?? ''}与${nodesById.get(selectedEdge?.target_id ?? '')?.name ?? ''}`;
  const evidenceCount = new Set(edges.flatMap((edge) => edge.evidence_publications.map((p) => p.object_id))).size;
  return <div className="sg-evidence-layer" role="dialog" aria-modal="true" aria-labelledby="collaboration-evidence-title"><button className="sg-evidence-scrim" aria-label="关闭关系来源" onClick={onClose} /><aside className="sg-evidence-drawer sg-relation-evidence-drawer"><header><div><span>当前选中{selectedNode ? '节点' : '合作关系'}</span><h2 id="collaboration-evidence-title">{title}的关系来源</h2></div><Button kind="ghost" onClick={onClose}>关闭</Button></header><div className="sg-evidence-summary"><strong>{edges.length}</strong><span>组合作关系</span><code>{evidenceCount} 篇论文依据</code></div><div className="sg-evidence-list">{edges.map((edge) => <article key={edge.edge_id}><div><Tag type={edge.highlighted ? 'teal' : 'blue'}>{edge.collaboration_kind ?? '论文合作'}</Tag><span>{edge.publication_count} 篇共同论文</span></div><h3>{nodesById.get(edge.source_id)?.name} <strong>合作</strong> {nodesById.get(edge.target_id)?.name}</h3><p>共同署名同一篇论文形成合作关系，以下为当前接口返回的论文依据。</p><div className="sg-edge-evidence">{edge.evidence_publications.map((publication) => <Link key={publication.object_id} to={`/outputs/${publication.object_id}`}>{publication.title}</Link>)}</div></article>)}</div><footer><Button onClick={onClose}>完成查看</Button></footer></aside></div>;
}

function collaborationLegend(nodes: CollaborationNode[]) {
  if (nodes.some((node) => node.node_type === 'person')) return [{ key: 'person', className: 'type-person', label: '学者' }];
  const items = [{ key: 'default', className: 'group-default', label: '其他机构' }];
  if (nodes.some((node) => ['campus', 'first_hospital', 'second_hospital'].includes(node.group_key ?? ''))) items.unshift({ key: 'medical', className: 'group-campus', label: '校本部与附属医院' });
  if (nodes.some((node) => ['engineering_university', 'research_institute'].includes(node.group_key ?? ''))) items.unshift({ key: 'research', className: 'group-engineering_university', label: '工科高校与研究机构' });
  return items;
}

interface AnalysisPoint { x: number; y: number; cluster: number; role: 'core' | 'peripheral' }
interface AnalysisViewState { x: number; y: number; zoom: number }

function AnalysisEmpty({ text }: { text: string }) { return <div className="sg-analysis-empty"><Information size={24} /><p>{text}</p></div>; }
function AnalyticsLoading() { return <section className="sg-analytics-loading"><InlineLoading description="正在聚合论文、人员、机构、基金与学科关系" /><div>{Array.from({ length: 8 }, (_, index) => <span key={index} />)}</div></section>; }
function formatPercent(value: number) { return `${(value * 100).toFixed(value < .01 ? 1 : 0)}%`; }
function formatMetric(value: number | null | undefined) { return value == null ? '—' : value.toLocaleString('zh-CN', { maximumFractionDigits: 3 }); }
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(`${value}T00:00:00`)); }
function coveragePercent(value: number, total: number) { return total ? `${Math.round(value / total * 100)}%` : '0%'; }
function formatTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)); }
function truncate(value: string, length: number) { return value.length > length ? `${value.slice(0, length - 1)}…` : value; }

function graphPositions(nodes: CollaborationNode[], edges: CollaborationEdge[]) {
  const clustered = clusteredGraphLayout(
    nodes.map((node) => ({ id: node.object_id, label: node.name, communityId: node.community_id ?? null })),
    edges.map((edge) => ({ source: edge.source_id, target: edge.target_id, weight: edge.publication_count })),
    { width: ANALYSIS_GRAPH_WIDTH, height: ANALYSIS_GRAPH_HEIGHT, padding: 64, clusterGap: 120, expandable: true },
  );
  return new Map<string, AnalysisPoint>(clustered);
}
