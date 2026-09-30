import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Button, TextInput, TextArea, Select, SelectItem, Checkbox } from '@carbon/react';
import { getKnowledgeCatalog } from '../../shared/api/smartlib';
import { runtimeConfig } from '../../shared/config/runtime';
import type { KnowledgeHubOutletContext } from './KnowledgeHubShell';

interface Change { submission_id: string; context_name: string; source_label: string; status: string;
  proposals: { proposal_id: string; target_name?: string; field_path: string; current_value: unknown; proposed_value: unknown;
    application_state: string; decision_reason: string | null }[] };
interface IdentityDetail { version: number; profile: Record<string, unknown>;
  names: { name: string; name_kind: string }[];
  identifiers: { identifier_type: string; normalized_value: string }[] }
const identityLabels: Record<string, string> = {
  'profile.given_name': '名（有来源依据时填写）', 'profile.family_name': '姓（有来源依据时填写）',
  'profile.preferred_language': '姓名首选语言', 'profile.organization_type': '机构类别',
  'profile.country_code': '国家或地区代码', 'identifiers.orcid': 'ORCID', 'identifiers.ror': 'ROR',
  'identity.aliases': '其他姓名或机构名称',
};
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${runtimeConfig.apiBaseUrl.replace(/\/$/, '')}/api/v1/changes${path}`, {
    method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const result: unknown = await response.json();
  if (!response.ok) throw new Error(String(typeof result === 'object' && result !== null && 'detail' in result ? result.detail : '操作未完成'));
  return result as T;
}
const valueText = (value: unknown) => value == null ? '未填写' : typeof value === 'string' ? value : JSON.stringify(value);
export function ChangeWorkbench() {
  const { permissions } = useOutletContext<KnowledgeHubOutletContext>();
  const cache = useQueryClient();
  const [query, setQuery] = useState('');
  const [target, setTarget] = useState('');
  const [field, setField] = useState('description');
  const [value, setValue] = useState('');
  const [clearValue, setClearValue] = useState(false);
  const [source, setSource] = useState('');
  const [reason, setReason] = useState('');
  const [reviewReasons, setReviewReasons] = useState<Record<string, string>>({});
  const objects = useQuery({ queryKey: ['change-targets', query], queryFn: () => getKnowledgeCatalog({
    objectTypes: ['person', 'organization', 'department', 'project', 'funding_program', 'discipline', 'concept'],
    query, pageSize: 100, sort: 'name',
  }) });
  const list = useQuery({ queryKey: ['changes'], queryFn: () => request<Change[]>('') });
  const selected = objects.data?.items.find((item) => item.object_id === target);
  const hasIdentity = selected && ['person', 'organization', 'department'].includes(selected.object_type);
  const identity = useQuery({ queryKey: ['identity-profile', target], enabled: Boolean(hasIdentity), queryFn: async () => {
    const response = await fetch(`${runtimeConfig.apiBaseUrl.replace(/\/$/, '')}/api/v1/identities/${target}`);
    if (!response.ok) throw new Error('无法读取身份档案');
    return await response.json() as IdentityDetail;
  } });
  const identityFields = !hasIdentity ? [] : selected.object_type === 'person'
    ? ['profile.given_name', 'profile.family_name', 'profile.preferred_language', 'identifiers.orcid', 'identity.aliases']
    : ['profile.organization_type', 'profile.country_code', 'identifiers.ror', 'identity.aliases'];
  const currentValue = field.startsWith('profile.') ? identity.data?.profile[field.slice(8)]
    : field === 'identity.aliases' ? identity.data?.names.filter((n) => n.name_kind === 'alias').map((n) => n.name)
    : field.startsWith('identifiers.') ? identity.data?.identifiers.find((i) => i.identifier_type === field.slice(12))?.normalized_value
    : field === 'canonical_name' ? selected?.canonical_name : selected?.description;
  const submit = useMutation({ mutationFn: () => {
    if (!selected) throw new Error('请选择修改对象');
    return request('', {
    context_object_id: selected.object_id, source_label: source, reason,
    proposals: [{ target_kind: 'object', target_id: selected.object_id,
      field_path: field, proposed_value: clearValue ? (field === 'identity.aliases' ? [] : null) : field === 'identity.aliases' ? value.split(/\n/).filter((n) => n.trim()) : value, base_version: identity.data?.version ?? selected.version }],
  }); }, onSuccess: () => { setValue(''); setClearValue(false); void cache.invalidateQueries({ queryKey: ['changes'] }); } });
  const decide = useMutation({ mutationFn: ({ id, decision }: { id: string; decision: 'accept' | 'reject' }) =>
    request(`/${id}/decision`, { decision, reason: reviewReasons[id] }),
    onSuccess: () => { void cache.invalidateQueries({ queryKey: ['changes'] }); void cache.invalidateQueries({ queryKey: ['change-targets'] }); void cache.invalidateQueries({ queryKey: ['identity-profile'] }); } });
  const error = objects.error ?? identity.error ?? list.error ?? submit.error ?? decide.error;
  return <section className="kh-page">
    <header className="kh-page-header"><h1>数据变更</h1><p>提交有来源依据的修正，审核后写入。论文和期刊的专属信息通过对应业务流程处理。</p></header>
    {error && <p role="alert">{error.message}</p>}
    {permissions.includes('change.submit') && <section className="kh-supplement-card">
      <h2>提交修正</h2>
      <TextInput id="change-search" labelText="查找人物、机构或项目等对象" value={query} onChange={(e) => { setQuery(e.target.value); setTarget(''); }} />
      <Select id="change-target" labelText="修改对象（当前搜索结果前 100 条）" value={target} onChange={(e) => { setTarget(e.target.value); setField('description'); setValue(''); setClearValue(false); }}>
        <SelectItem value="" text="请选择对象" />
        {objects.data?.items.map((item) => <SelectItem key={item.object_id} value={item.object_id} text={item.canonical_name} />)}
      </Select>
      <Select id="change-field" labelText="修改内容" value={field} onChange={(e) => { setField(e.target.value); setValue(''); setClearValue(false); }}>
        <SelectItem value="description" text="说明" /><SelectItem value="canonical_name" text="规范名称" />
        {identityFields.map((f) => <SelectItem key={f} value={f} text={identityLabels[f] ?? f} />)}
      </Select>
      {selected && <p>当前内容：{valueText(currentValue)}</p>}
      {hasIdentity && <p>来源姓名或名称：{identity.data?.names.filter((n) => n.name_kind === 'source_name').map((n) => n.name).join('、') ?? '读取中'}</p>}
      {field === 'identity.aliases' && <p>每行填写一个名称。原始来源名称会保留。</p>}
      {field === 'profile.country_code' && <p>填写两位国家或地区代码，例如 CN。</p>}
      {field === 'profile.preferred_language' && <p>填写语言代码，例如 zh 或 en；不从姓名推断语言。</p>}
      {field === 'profile.organization_type' ? <Select id="organization-type" labelText="建议机构类别" value={value} onChange={(e) => setValue(e.target.value)} disabled={clearValue}>
        <SelectItem value="" text="请选择" />
        {Object.entries({ university: '大学', hospital: '医院', research_institute: '研究机构', company: '企业', government: '政府机构', nonprofit: '非营利机构', department: '部门', other: '其他' }).map(([key, label]) => <SelectItem key={key} value={key} text={label} />)}
      </Select> : <TextArea id="change-value" labelText="建议内容" value={value} disabled={clearValue} onChange={(e) => setValue(e.target.value)} />}
      {identityFields.includes(field) && <Checkbox id="identity-clear" labelText="清空该字段（需审核）" checked={clearValue} onChange={(_, { checked }) => setClearValue(checked)} />}
      <TextInput id="change-source" labelText="依据来源" value={source} onChange={(e) => setSource(e.target.value)} />
      <TextArea id="change-reason" labelText="修改原因与证据说明" value={reason} onChange={(e) => setReason(e.target.value)} />
      <Button disabled={!selected || (Boolean(hasIdentity) && !identity.data) || (!clearValue && !value.trim()) || !source.trim() || !reason.trim() || submit.isPending} onClick={() => submit.mutate()}>提交审核</Button>
      {submit.isSuccess && <p role="status">已提交，正式数据将在审核通过后更新。</p>}
    </section>}
    <h2>最近 100 次通用变更提交</h2>
    {list.isPending ? <p>正在读取…</p> : list.data?.length === 0 ? <p>暂无通用变更提交。</p> : list.data?.map((item) => <article className="kh-supplement-card" key={item.submission_id}>
      <h3>{item.context_name}</h3><p>{item.source_label} · {item.status === 'needs_review' ? '待审核' : item.status === 'accepted' ? '已应用' : '已拒绝'}</p>
      {item.proposals.map((p) => <div key={p.proposal_id}><strong>{p.target_name ?? item.context_name}</strong><p>{p.field_path === 'canonical_name' ? '规范名称' : p.field_path === 'description' ? '说明' : identityLabels[p.field_path] ?? '属性或关系调整'}</p>
        <p>当前：{valueText(p.current_value)}</p><p>建议：{valueText(p.proposed_value)}</p>
        {p.application_state === 'conflict' && <p role="alert">数据在提交后已变化，本次改动尚未应用。请拒绝此提交后，基于最新内容重新提交。</p>}
        {p.decision_reason && <p>{p.decision_reason}</p>}</div>)}
      {item.status === 'needs_review' && permissions.includes('change.decide') && <>
        <TextArea id={`reason-${item.submission_id}`} labelText="审核说明" value={reviewReasons[item.submission_id] ?? ''} onChange={(e) => setReviewReasons({ ...reviewReasons, [item.submission_id]: e.target.value })} />
        <Button disabled={!reviewReasons[item.submission_id]?.trim() || decide.isPending} onClick={() => decide.mutate({ id: item.submission_id, decision: 'accept' })}>接受并应用</Button>
        <Button kind="danger--tertiary" disabled={!reviewReasons[item.submission_id]?.trim() || decide.isPending} onClick={() => decide.mutate({ id: item.submission_id, decision: 'reject' })}>拒绝</Button>
      </>}
    </article>)}
  </section>;
}
