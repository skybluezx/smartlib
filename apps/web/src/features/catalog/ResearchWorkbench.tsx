import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import './ResearchAnalysis.css';
import { api } from '../../shared/api/research';
import './ResearchWorkbench.css';

interface ObjectItem { id: string; name: string; version: number; attributes: Record<string, unknown> }
interface Standard { id: string; name: string; scheme: string; code: string; version: string; parent_code?: string | undefined }
interface Selection { standard_id: string; name: string; role: 'primary' | 'secondary' | 'topic'; scheme?: string | undefined }
interface Suggestion { text?: string | undefined; basis?: string | undefined; gaps?: string[] | undefined; evidence?: string | undefined; source?: string | undefined; summary?: string | undefined; method?: string | undefined;
  labels?: Selection[] | undefined; candidates?: (Selection & { code: string; matched_phrase: string })[] | undefined; current_labels?: Selection[] | undefined }
interface Task { id: string; object_id: string; name: string; state: string; issue_type: string; updated_at: string; machine_suggestion: Suggestion; decision: { reason?: string | undefined } }
interface Project extends ObjectItem { directions: { code: string; name: string; paper_count: number }[]; missing: string[]; comparison: string; representative_papers: number }
interface Workspace { papers: ObjectItem[]; entities: { id: string; name: string; kind: string }[]; projects: Project[]; standards: { scheme: string; version: string; count: number }[]; tasks: Task[]; gaps: string[]; scope: string }

export function ResearchWorkbench() {
  const client = useQueryClient();
  const q = useQuery({ queryKey: ['research-workspace'], queryFn: () => api<Workspace>('/workspace') });
  const [tab, setTab] = useState('queue'); const [selected, setSelected] = useState<string[]>([]); const [reason, setReason] = useState('');
  const [kind, setKind] = useState<'classification' | 'project'>('classification'); const [oid, setOid] = useState('');
  const [source, setSource] = useState(''); const [evidence, setEvidence] = useState(''); const [summary, setSummary] = useState('');
  const [labels, setLabels] = useState<Selection[]>([]); const [scheme, setScheme] = useState('NSFC_APPLICATION_CODE'); const [search, setSearch] = useState(''); const [version, setVersion] = useState(''); const [parent, setParent] = useState('');
  const [file, setFile] = useState<File>(); const [message, setMessage] = useState(''); const [activeTask, setActiveTask] = useState<Task>();
  const terms = useQuery({ queryKey: ['research-terms', scheme, search, version, parent], queryFn: () => api<Standard[]>('/standards?' + new URLSearchParams({ scheme, q: search, ...(version ? { version } : {}), ...(parent ? { parent } : {}) }).toString()) });
  const mutation = useMutation({ mutationFn: async ({ path, body, upload }: { path: string; body?: unknown; upload?: File | undefined }) => api<unknown>(path, body, upload),
    onSuccess: () => { setMessage('操作成功，分类与画像按审核结果更新。'); setSelected([]); void client.invalidateQueries({ queryKey: ['research-workspace'] }); void client.invalidateQueries({ queryKey: ['research-terms'] }); void client.invalidateQueries({ queryKey: ['research-profile'] }); }, onError: (e) => setMessage(e.message) });
  const d = q.data; const options = kind === 'project' ? d?.projects : d?.papers; const current = options?.find((x) => x.id === oid);
  function edit(t: Task) {
    const s = t.machine_suggestion; setActiveTask(t); setOid(t.object_id); setKind(t.issue_type === 'RESEARCH_PROJECT' ? 'project' : 'classification');
    setLabels(s.labels ?? (s.current_labels ?? []).map((x) => ({ standard_id: x.standard_id, name: x.name, role: x.role, scheme: x.scheme })));
    setSource(s.source ?? s.basis ?? ''); setEvidence(s.evidence ?? ''); setSummary(s.summary ?? ''); setTab('editor');
  }
  return <main className="sg-research-governance" style={{ padding: '2rem', maxWidth: '1200px' }}><h1>研究方向治理</h1><p>分类细化、项目权威资料、标准版本和日常审核。建议不会自动成为正式分类。</p>
    <nav aria-label="研究方向治理模块">{[['queue', '审核队列'], ['editor', '分类与资料录入'], ['projects', '项目方向对照'], ['standards', '标准与缺项']].map(([key, label]) => <button type="button" key={key} onClick={() => setTab(key ?? '')} aria-pressed={tab === key} style={{ margin: '0.5rem' }}>{label}</button>)}</nav>
    <p role="status">{message}</p>{mutation.isPending && <p>正在处理，请勿重复提交…</p>}
    {q.isPending ? <p>正在读取…</p> : q.isError ? <p role="alert">{q.error.message}</p> : d && <>
      <p>{d.scope}</p>{d.gaps.map((g) => <p key={g} role="note">{g}</p>)}
      {tab === 'queue' && <section><h2>审核队列</h2><p>新论文自动排队并生成词面候选；需要人工判断语义。现有分类仅在确认修改后替换。</p>
        <button disabled={mutation.isPending} onClick={() => mutation.mutate({ path: '/generate', body: {} })}>重新检查全部论文并生成待审建议</button>
        <p>当前任务 {d.tasks.length} 项；未完成 {d.tasks.filter((t) => ['open', 'in_review'].includes(t.state)).length} 项。批量上限100项。</p>
        <label>批量处理理由 <input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
        <button disabled={mutation.isPending || !selected.length || reason.trim().length < 2} onClick={() => mutation.mutate({ path: '/decisions', body: { task_ids: selected, action: 'approve', reason, expected_updated_at: Object.fromEntries(d.tasks.filter((t) => selected.includes(t.id)).map((t) => [t.id, t.updated_at])) } })}>批准选中项</button>
        <button disabled={mutation.isPending || !selected.length || reason.trim().length < 2} onClick={() => mutation.mutate({ path: '/decisions', body: { task_ids: selected, action: 'reject', reason, expected_updated_at: Object.fromEntries(d.tasks.filter((t) => selected.includes(t.id)).map((t) => [t.id, t.updated_at])) } })}>驳回选中项</button>
        <div className="sg-governance-queue" role="region" aria-label="审核任务列表" tabIndex={0}>{d.tasks.map((t) => <article key={t.id} style={{ borderBottom: '1px solid #ddd', padding: '1rem 0' }}>
          <label><input type="checkbox" aria-label={`选择${t.name}`} disabled={!['open', 'in_review'].includes(t.state)} checked={selected.includes(t.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, t.id] : selected.filter((id) => id !== t.id))} /> {t.name}</label>
          <p>状态：{({ open: '待核对', in_review: '待批准', resolved: '已确认', rejected: '已驳回', cancelled: '已取消' } as Record<string, string>)[t.state]}；候选 {(t.machine_suggestion.candidates ?? []).length} 项；{t.machine_suggestion.basis}</p>
          {t.machine_suggestion.gaps?.map((g) => <p key={g}>{g}</p>)}<p>{t.decision.reason}</p><Link to={`/outputs/${t.object_id}`}>查看原对象与全文</Link>{['open', 'in_review'].includes(t.state) && <button onClick={() => edit(t)}>核对并编辑</button>}</article>)}</div></section>}
      {tab === 'editor' && <section><h2>分类与资料录入</h2><label>类型 <select value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setOid(''); setLabels([]); setActiveTask(undefined); }}><option value="classification">论文分类</option><option value="project">项目权威资料</option></select></label>
        <label>对象 <select value={oid} onChange={(e) => { setOid(e.target.value); setLabels([]); setActiveTask(undefined); }}><option value="">请选择</option>{options?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
        <p>同一体系的提交内容将整体替换该对象原有的该体系分类，请保留仍适用的主、辅分类。未提交的体系和 InCites 原始分类不动。</p>
        {activeTask && <details open><summary>原文证据与自动候选</summary><p style={{ whiteSpace: 'pre-wrap', maxHeight: '18rem', overflow: 'auto' }}>{activeTask.machine_suggestion.text}</p>{activeTask.machine_suggestion.candidates?.map((x) => <p key={x.standard_id}>{x.name}（{x.code}）词面命中：{x.matched_phrase} <button onClick={() => setLabels((ls) => ls.some((l) => l.standard_id === x.standard_id) ? ls : [...ls, x])}>作为待核对标签加入</button></p>)}</details>}
        <label>分类体系 <select value={scheme} onChange={(e) => setScheme(e.target.value)}><option value="NSFC_APPLICATION_CODE">国自然申请代码</option><option value="MESH">MeSH主题</option><option value="MOE_GRADUATE_DISCIPLINE">教育部目录</option></select></label>
        <label>版本 <input placeholder="例如2026" value={version} onChange={(e) => setVersion(e.target.value)} /></label><label>代码前缀 <input placeholder="例如H19，查细分代码" value={parent} onChange={(e) => setParent(e.target.value)} /></label>
        <label>代码或名称 <input value={search} onChange={(e) => setSearch(e.target.value)} /></label>
        {terms.isError && <p role="alert">{terms.error.message}</p>}
        <div style={{ maxHeight: '14rem', overflow: 'auto' }}>{terms.data?.map((x) => <div key={x.id}>{x.code} · {x.name} · {x.version} <button onClick={() => setLabels((ls) => ls.some((l) => l.standard_id === x.id) ? ls : [...ls, { standard_id: x.id, name: x.name, scheme: x.scheme, role: x.scheme === 'MESH' ? 'topic' : 'secondary' }])}>加入</button></div>)}{terms.data?.length === 0 && <p>未找到词条。请检查版本、名称，或先导入标准。</p>}</div>
        <h3>本次提交的分类</h3>{labels.map((x) => <p key={x.standard_id}>{x.name} <select aria-label={`${x.name}角色`} value={x.role} onChange={(e) => setLabels(labels.map((l) => l.standard_id === x.standard_id ? { ...l, role: e.target.value as Selection['role'] } : l))}><option value="primary">主方向</option><option value="secondary">辅方向</option><option value="topic">主题</option></select><button onClick={() => setLabels(labels.filter((l) => l.standard_id !== x.standard_id))}>移除</button></p>)}
        <p>每套学科分类需有且仅有一个主方向；MeSH用“主题”。证据不足可保留原粗分类，不必强行细分。</p>
        <label>来源名称或链接<input style={{ width: '100%' }} value={source} onChange={(e) => setSource(e.target.value)} /></label>
        <label>判断依据／来源原文<textarea style={{ width: '100%', minHeight: '6rem' }} value={evidence} onChange={(e) => setEvidence(e.target.value)} /></label>
        {kind === 'project' && <label>权威项目摘要／研究内容（不可用代表作摘要代替）<textarea style={{ width: '100%', minHeight: '6rem' }} value={summary} onChange={(e) => setSummary(e.target.value)} /></label>}
        <button disabled={mutation.isPending || !current || !labels.length} onClick={() => mutation.mutate({ path: '/proposals', body: { object_id: oid, kind, labels: labels.map(({ standard_id, role }) => ({ standard_id, role })), source, evidence, summary, expected_object_version: current?.version } })}>保存为待审核，不立即入正式分类</button>
      </section>}
      {tab === 'projects' && <section><h2>项目实际方向与代表作对照</h2><p>缺少权威项目资料时仅展示代表作方向；代码比较只在同版本下按层级相容判断，不作质量评价。</p>
        {d.projects.map((p) => <article key={p.id} style={{ padding: '1rem 0', borderBottom: '1px solid #ddd' }}><h3><Link to={`/outputs/${p.id}`}>{p.name}</Link></h3><p>代表作 {p.representative_papers} 篇；{p.directions.map((r) => `${r.code} ${r.name} ${r.paper_count}篇`).join('；')}</p><p>实际申请代码：{Array.isArray(p.attributes.official_nsfc_codes) ? p.attributes.official_nsfc_codes.join('、') : '缺失'}；{p.comparison}</p>{p.missing.length > 0 && <p>需要补充：{p.missing.join('、')}。可提供立项通知、申请书或权威项目数据库记录。</p>}<button onClick={() => { setKind('project'); setOid(p.id); setLabels([]); setSource(''); setEvidence(''); setSummary(''); setActiveTask(undefined); setTab('editor'); }}>补充项目权威资料</button></article>)}</section>}
      {tab === 'standards' && <section><h2>版本化分类标准</h2>{d.standards.map((s) => <p key={s.scheme + s.version}>{s.scheme} · {s.version} · {s.count} 个词条（含根节点等）</p>)}
        <h3>导入教育部目录</h3><p>上传已按教育部官方原文核对的JSON目录，包含版本、来源URL、代码、名称和上级代码。系统检查重复、缺失上级和层级循环；同版本不同内容拒绝覆盖。原文件存MinIO，旧版本保留。</p>
        <p><a href="/research-moe-template.json" download>下载格式模板（仅结构示例，不是正式目录）</a></p><input aria-label="教育部目录JSON文件" type="file" accept=".json" onChange={(e) => setFile(e.target.files?.[0])} /><button disabled={!file || mutation.isPending} onClick={() => mutation.mutate({ path: '/standards/moe', upload: file })}>核验并导入目录</button>
        <p>暂不自动把国自然代码等同于教育部学科；导入后可在论文分类中选择教育部口径，并记录人工依据。</p></section>}
    </>}</main>;
}
