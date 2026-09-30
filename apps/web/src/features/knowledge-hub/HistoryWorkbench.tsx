import { useState } from 'react';
import { Link, useOutletContext, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { getKnowledgeCatalog } from '../../shared/api/smartlib';
import { runtimeConfig } from '../../shared/config/runtime';
import type { KnowledgeHubOutletContext } from './KnowledgeHubShell';
import { historyDiff } from './historyDiff';

interface Revision {
  revision_id: string; entity_table: string; entity_id: string; operation: string;
  before_value: Record<string, unknown> | null; after_value: Record<string, unknown> | null;
  actor_id: string | null; recorded_at: string; change_id: string | null; submission_id: string | null;
  current_version: number | null;
  change_context: { reason: string | null; source_label: string | null; trace_id: string | null } | null;
}
interface Review { submission_id: string; source_label: string; status: string; created_at: string;
  created_by: string; decided_at: string | null; decided_by: string | null; decision_reason: string | null; source_uri: string | null }
const text = (v: unknown) => v === undefined ? '字段不存在' : v === null ? '空值' : typeof v === 'string' ? v : JSON.stringify(v, null, 2);
const labels: Record<string, string> = {
  knowledge_object: '知识对象', relation_assertion: '对象关系', evidence_record: '证据', relation_evidence: '证据挂接',
  publication_authorship: '作者署名', publication_metadata: '论文信息', publication_fulltext_resource: '全文资源',
  publication_relation_provenance: '署名溯源', organization_name_variant: '机构名称与别名', person_name_variant: '学者名称',
  organization_profile: '机构扩展信息', person_profile: '学者扩展信息', source_reference: '来源引用',
  canonical_name: '规范名称', description: '说明', confidence: '置信度', version: '版本号',
  'profile.given_name': '名', 'profile.family_name': '姓', 'profile.preferred_language': '首选语言',
  'profile.organization_type': '机构类别', 'profile.country_code': '国家或地区代码',
};
async function request<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${runtimeConfig.apiBaseUrl.replace(/\/$/, '')}/api/v1/history/${path}`, {
    method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await r.json() as T & { detail?: string };
  if (!r.ok) throw new Error(data.detail ?? '读取历史失败');
  return data;
}
function fields(r: Revision) {
  const s = r.after_value ?? r.before_value ?? {};
  if (r.entity_table === 'knowledge_object' && !['publication', 'journal'].includes(String(s.object_type))) return ['canonical_name', 'description'];
  if (r.entity_table === 'relation_assertion') return ['confidence'];
  if (r.entity_table === 'person_profile') return ['profile.given_name', 'profile.family_name', 'profile.preferred_language'];
  if (r.entity_table === 'organization_profile') return ['profile.organization_type', 'profile.country_code'];
  return [];
}
export function HistoryWorkbench() {
  const { permissions } = useOutletContext<KnowledgeHubOutletContext>();
  const [params, setParams] = useSearchParams();
  const target = params.get('object') ?? '';
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [scope, setScope] = useState('object');
  const [selected, setSelected] = useState<Revision[]>([]);
  const [restore, setRestore] = useState<Revision | null>(null);
  const [field, setField] = useState('');
  const [reason, setReason] = useState('');
  const allowed = permissions.includes('change.decide');
  const catalog = useQuery({ queryKey: ['history-catalog', query], enabled: allowed,
    queryFn: () => getKnowledgeCatalog({ query, page: 1, pageSize: 100, objectTypes: [], sort: 'name' }) });
  const history = useQuery({ queryKey: ['history', target, offset, scope], enabled: allowed && Boolean(target),
    queryFn: () => request<{ items: Revision[]; reviews: Review[]; object_name: string }>(`${target}?limit=50&offset=${offset}&scope=${scope}`) });
  const mutation = useMutation({ mutationFn: () => request(`${target}/restore-proposal`, {
    revision_id: restore?.revision_id, side: restore?.after_value ? 'after_value' : 'before_value',
    field_path: field, base_version: restore?.current_version, reason,
  }) });
  const comparison = selected.length === 2 ? historyDiff(selected[0]?.after_value ?? selected[0]?.before_value ?? {}, selected[1]?.after_value ?? selected[1]?.before_value ?? {}) : [];
  return <section className="kh-workbench"><h1>版本与追溯</h1>
    <p>查看对象及关联记录的修改前后内容、执行身份、变更批次与审核依据。技术版本不等同于业务发布版本。</p>
    {!allowed ? <p role="alert">历史内容仅向具有变更审核权限的用户开放。</p> : <>
      <label>查找论文、学者或机构 <input value={query} onChange={(e) => setQuery(e.target.value)} /></label>
      <label>选择对象 <select value={target} onChange={(e) => { setParams({ object: e.target.value }); setOffset(0); setSelected([]); setRestore(null); mutation.reset(); }}>
        <option value="">请选择</option>{target && !catalog.data?.items.some((o) => o.object_id === target) && <option value={target}>{history.data?.object_name ?? target}</option>}
        {catalog.data?.items.map((o) => <option key={o.object_id} value={o.object_id}>{o.canonical_name}</option>)}
      </select></label>
      <label>查看范围 <select value={scope} onChange={(e) => { setScope(e.target.value); setOffset(0); setSelected([]); }}><option value="object">对象本身的版本</option><option value="all">包含关系、别名、证据等关联记录</option></select></label>
      <p>旧记录未补写修改原因。新增覆盖的来源、证据挂接与全文资源历史仅从机制启用后记录；不代表过去从未发生修改。</p>
      {catalog.error && <p role="alert">{catalog.error.message}</p>}
      {history.isFetching && <p>正在读取历史…</p>}{history.error && <p role="alert">{history.error.message}</p>}
      {target && history.data?.items.length === 0 && <p>此范围暂无历史记录。</p>}
      {Boolean(history.data?.reviews.length) && <details><summary>关联的最近 20 条变更申请与审核</summary>{history.data?.reviews.map((r) => <article key={r.submission_id}>
        <h3>{r.source_label} · {r.status}</h3><p>申请编号：{r.submission_id}；提交人：{r.created_by}；时间：{r.created_at}</p>
        <p>审核人：{r.decided_by ?? '未审核'}；审核时间：{r.decided_at ?? '未审核'}；意见：{r.decision_reason ?? '未记录'}</p>
        <p>来源引用：{r.source_uri ?? '未填写'}</p>
      </article>)}</details>}
      {selected.length === 2 && <section className="kh-supplement-card"><h2>两个历史状态的差异</h2><p>左侧：{selected[0]?.recorded_at}；右侧：{selected[1]?.recorded_at}。同页或跨页选择均可。</p>
        {comparison.length === 0 ? <p>内容相同</p> : comparison.map((d) => <div key={d.field}><strong>{d.field}</strong><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{text(d.before)}{'\n→\n'}{text(d.after)}</pre></div>)}
      </section>}
      {history.data?.items.map((r) => <article className="kh-supplement-card" key={r.revision_id}>
        <h2>{new Date(r.recorded_at).toLocaleString('zh-CN')} · {labels[r.entity_table] ?? r.entity_table} · {{ INSERT: '新增', UPDATE: '修改', DELETE: '删除' }[r.operation]}</h2>
        <p>执行身份：{r.actor_id ?? '未记录'}；批次：{r.change_id ?? '旧记录未关联批次'}；{r.before_value?.version !== undefined || r.after_value?.version !== undefined ? <>版本：{r.before_value?.version === undefined ? '创建前' : text(r.before_value.version)} → {r.after_value?.version === undefined ? '删除后' : text(r.after_value.version)}</> : '该类记录按快照追溯，无独立版本号'}</p>
        <p>原因：{r.change_context?.reason ?? '未记录'}；来源：{r.change_context?.source_label ?? '未记录'}</p>
        <p>审核申请：{r.submission_id ?? '未直接关联'}；历史记录：{r.revision_id}</p>
        <button onClick={() => setSelected((old) => {
          if (old.some((v) => v.revision_id === r.revision_id)) return old.filter((v) => v.revision_id !== r.revision_id);
          const same = old.filter((v) => v.entity_id === r.entity_id && v.entity_table === r.entity_table && (r.entity_table !== 'relation_evidence' || (v.after_value ?? v.before_value)?.evidence_id === (r.after_value ?? r.before_value)?.evidence_id));
          return [...same.slice(-1), r];
        })}>{selected.some((v) => v.revision_id === r.revision_id) ? '取消对比' : '选择此状态对比'}</button>
        <details><summary>查看本次修改内容</summary>{historyDiff(r.before_value ?? {}, r.after_value ?? {}).map((d) => <div key={d.field}><strong>{d.field}</strong><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{text(d.before)}{'\n→\n'}{text(d.after)}</pre></div>)}</details>
        {fields(r).length > 0 && r.current_version && permissions.includes('change.submit') && <button onClick={() => { setRestore(r); setField(fields(r)[0] ?? ''); setReason(''); mutation.reset(); }}>以此历史内容发起恢复申请</button>}
      </article>)}
      {target && <p><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>较新的记录</button> 第 {offset + 1} 条起 <button disabled={(history.data?.items.length ?? 0) < 50} onClick={() => setOffset(offset + 50)}>更早的记录</button></p>}
      {restore && <section className="kh-supplement-card"><h2>恢复为新版本：先提交审核</h2><p>不会直接回滚数据库，也不会删除中间历史。当前支持规范名称、说明、置信度及人物／机构扩展字段；其他内容使用专属治理流程。</p>
        <label>恢复字段 <select value={field} onChange={(e) => setField(e.target.value)}>{fields(restore).map((f) => <option key={f} value={f}>{labels[f] ?? f}</option>)}</select></label>
        <label>恢复原因 <textarea value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <button disabled={!reason.trim() || mutation.isPending || mutation.isSuccess} onClick={() => mutation.mutate()}>提交恢复申请</button>
        {mutation.error && <p role="alert">{mutation.error.message}</p>}{mutation.isSuccess && <p>已提交，正式内容尚未改变。<Link to="/knowledge-hub/changes">前往数据变更审核</Link></p>}
      </section>}
    </>}
  </section>;
}
