import { analysisReports } from './analysisReports';
import { FrozenAnalysisSummary } from './FrozenAnalysisSummary';
import { useWorkbenchSettings } from './workbenchSettings';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, InlineLoading, InlineNotification, Modal, TextInput } from '@carbon/react';
import { Save } from '@carbon/icons-react';
import type { AnalysisDefinition, SavedAnalysisDetail } from '../../generated/smartlib-api';
import { createSavedAnalysis, getSavedAnalysis, listSavedAnalyses } from '../../generated/smartlib-api';
import type { GraphAnalysisQuery } from '../../shared/api/smartlib';
import { ResearchStrategyPanel } from './ResearchStrategyPanel';
import { defaultStrategy, dimensions, type StrategySettings } from './strategyAnalysis';

function restoreComparison(raw: Record<string, string> = {}): StrategySettings {
 return { focal: raw.focal ?? '', scheme: raw.scheme ?? defaultStrategy.scheme, primary: dimensions.includes(raw.primary as StrategySettings['primary']) ? raw.primary as StrategySettings['primary'] : defaultStrategy.primary, secondary: dimensions.includes(raw.secondary as StrategySettings['primary']) ? raw.secondary as StrategySettings['primary'] : '不交叉', metric: ['CNCI', '被引次数', '同年 JIF'].includes(raw.metric ?? '') ? raw.metric as StrategySettings['metric'] : 'CNCI' };
}

export function AnalysisLibrary({ query, onApply, comparison, onComparison, active = true }: { comparison: StrategySettings; onComparison: (s: StrategySettings) => void; active?: boolean | undefined; query: GraphAnalysisQuery; onApply: (query: GraphAnalysisQuery) => void }) {
  const client = useQueryClient();
  const workspace = useWorkbenchSettings();
  const [saving, setSaving] = useState<'template' | 'snapshot' | null>(null);
  const [name, setName] = useState('');
  const [snapshotSettings, setSnapshotSettings] = useState(defaultStrategy);
  const [selected, setSelected] = useState<SavedAnalysisDetail | null>(null);
  const library = useQuery({ queryKey: ['saved-analyses'], enabled: active, queryFn: async ({ signal }) => {
    const response = await listSavedAnalyses({ signal });
    if (response.error) throw new Error('保存的分析暂时无法读取，请重试。');
    return response.data;
  } });
  const save = useMutation({ mutationFn: async () => {
    if (!saving) throw new Error('请选择保存类型');
    const response = await createSavedAnalysis({ body: { name: name.trim(), kind: saving, definition: {
      workspace_settings: workspace.values,
      institution_settings: query.institutionSettings ? JSON.parse(query.institutionSettings) as NonNullable<AnalysisDefinition['institution_settings']> : { mode: 'root', root_ids: [], groups: [] },
      edge_limit: query.edgeLimit ?? 120, people_focus_id: query.peopleFocusId ?? null,
      people_organization_id: query.peopleOrganizationId ?? null, people_include_external: query.peopleIncludeExternal ?? false,
      comparison: { ...comparison }, start_year: query.startYear ?? null, end_year: query.endYear ?? null,
      project_kind_ids: query.projectKindIds ?? [], organization_ids: query.organizationIds ?? [],
      scholar_ids: query.scholarIds ?? [], graph_query: query.customGraphQuery ?? null,
      custom_scope_id: query.customScopeId ?? null, minimum_publication_count: query.minimumPublicationCount ?? 2,
    } } });
    if (response.error) throw new Error('保存失败，请检查权限、范围及服务状态后重试。');
    return response.data;
  }, onSuccess: () => { setSaving(null); setName(''); void client.invalidateQueries({ queryKey: ['saved-analyses'] }); } });
  const inspect = useMutation({ mutationFn: async (id: string) => {
    const response = await getSavedAnalysis({ path: { analysis_id: id } });
    if (response.error) throw new Error('记录不存在或当前已无权读取其中的数据。');
    return response.data;
  }, onSuccess: (record) => { setSelected(record); setSnapshotSettings(restoreComparison(record.definition.comparison)); } });
  const apply = (d: AnalysisDefinition) => {
    workspace.replace(d.workspace_settings ?? {});
    onComparison(restoreComparison(d.comparison));
    onApply({ institutionSettings: JSON.stringify(d.institution_settings ?? {mode:'root',root_ids:[],groups:[]}),
      edgeLimit: d.edge_limit ?? 120, peopleFocusId: d.people_focus_id ?? undefined,
      peopleOrganizationId: d.people_organization_id ?? undefined, peopleIncludeExternal: d.people_include_external ?? false,
      startYear: d.start_year ?? undefined, endYear: d.end_year ?? undefined,
      projectKindIds: d.project_kind_ids, organizationIds: d.organization_ids, scholarIds: d.scholar_ids,
      customScopeId: d.custom_scope_id ?? undefined, customGraphQuery: d.graph_query ?? undefined,
      minimumPublicationCount: d.minimum_publication_count ?? 2 });
    setSelected(null);
  };
  return <section className="sg-analysis-records">
    <header className="sg-analysis-section-heading"><h2>分析记录</h2><p>分析模板保留条件，方便按最新数据重跑；历史报告与数据快照保留保存时的结果。</p></header>
    <div className="sg-analysis-library">
      <Button kind="ghost" renderIcon={Save} onClick={() => { save.reset(); setSaving('template'); }}>保存分析条件</Button>
      <Button kind="ghost" renderIcon={Save} onClick={() => { save.reset(); setSaving('snapshot'); }}>保存结果快照</Button>
    </div>
    {save.isSuccess && <InlineNotification kind="success" title="已保存到我的分析" subtitle="条件可重新运行；历史快照保留保存时的结果。" onClose={() => { save.reset(); return true; }} />}
    <Modal open={saving !== null} modalHeading={saving === 'template' ? '保存分析条件' : '保存结果快照'} primaryButtonText={save.isPending ? '保存中…' : '保存'} secondaryButtonText="取消" primaryButtonDisabled={!name.trim() || save.isPending} onRequestSubmit={() => save.mutate()} onRequestClose={() => { if (!save.isPending) setSaving(null); }}>
      <p>{saving === 'template' ? '保存当前已应用的筛选、图查询及合作网络阈值；下次运行使用最新可访问数据。' : '服务器将按当前已应用条件重新计算并冻结全部分析结果，不随后续数据变化。保存结果可能与刚才页面稍有差异。'}</p>
      <TextInput id="analysis-save-name" labelText="名称" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
      {save.isError && <InlineNotification kind="error" title={save.error.message} hideCloseButton />}
    </Modal>
    <div className="sg-analysis-record-list">
      {library.isPending && <InlineLoading description="读取中…" />}
      {library.isError && <><InlineNotification kind="error" title={library.error.message} /><Button kind="ghost" onClick={() => void library.refetch()}>重试</Button></>}
      {library.data?.length === 0 && <p>尚无已保存分析。先应用分析范围，再保存条件或结果快照。</p>}
      <p>仅显示当前身份可读取的最近 100 条记录；数据访问权限变化后，部分历史记录可能不再可见。</p>
      {(['template', 'snapshot'] as const).map((kind) => <section className="sg-analysis-record-group" key={kind}>
        <h3>{kind === 'template' ? '分析模板' : '历史报告与数据快照'}</h3>
        {library.data && !library.data.some((item) => item.kind === kind) && <p>{kind === 'template' ? '尚无保存的分析模板。' : '尚无历史报告或数据快照。'}</p>}
        {library.data?.filter((item) => item.kind === kind).map((item) => <div className="sg-analysis-library-row" key={item.analysis_id}>
          <div><strong>{item.name}</strong><p>{item.kind === 'template' ? '按最新数据重跑' : `${item.publication_count} 篇论文 · 保存时的结果`} · {new Date(item.created_at).toLocaleString('zh-CN')}</p></div>
          {analysisReports[item.analysis_id] && <Button as="a" size="sm" kind="primary" href={analysisReports[item.analysis_id]?.href} target="_blank" rel="noopener noreferrer">{analysisReports[item.analysis_id]?.label}</Button>}
          <Button size="sm" kind="ghost" onClick={() => apply(item.definition)}>应用条件</Button>
          {item.kind === 'snapshot' && <Button size="sm" kind="tertiary" disabled={inspect.isPending} onClick={() => inspect.mutate(item.analysis_id)}>查看快照</Button>}
        </div>)}
      </section>)}
      {inspect.isPending && <InlineLoading description="读取历史结果…" />}
      {inspect.isError && <InlineNotification kind="error" title={inspect.error.message} />}
    </div>
    <Modal open={selected !== null} passiveModal size="lg" modalHeading="历史结果快照" onRequestClose={() => setSelected(null)}>
      {selected?.result && <section><h2>{selected.name}</h2><p>历史结果：{new Date(selected.created_at).toLocaleString('zh-CN')} · {selected.publication_count} 篇论文</p>{selected.result.collaboration_outcomes && <ResearchStrategyPanel key={selected.analysis_id} data={selected.result.collaboration_outcomes} settings={snapshotSettings} onSettings={setSnapshotSettings} historical />}<FrozenAnalysisSummary result={selected.result} /></section>}
    </Modal>
  </section>;
}
