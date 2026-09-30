import { useQuery } from '@tanstack/react-query';
import { type SyntheticEvent, useState } from 'react';
import { searchVisibleKnowledge } from '../../shared/api/smartlib';

const typeLabels: Record<string, string> = {
  person: '学者',
  organization: '机构',
  department: '院系',
  discipline: '学科',
  project: '项目',
  funding_program: '资助计划',
  journal: '期刊',
  publication: '成果',
  dataset: '数据集',
  patent: '专利',
  resource: '资源',
  event: '事件',
  concept: '概念',
  requirement: '需求',
};

export function SearchLivePanel() {
  const [input, setInput] = useState('SmartLib');
  const [submittedQuery, setSubmittedQuery] = useState('SmartLib');
  const query = useQuery({
    queryKey: ['search-knowledge', submittedQuery],
    queryFn: () => searchVisibleKnowledge(submittedQuery),
    staleTime: 15_000,
    retry: 1,
  });

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = input.trim();
    if (normalized) setSubmittedQuery(normalized);
  }

  return <section className="panel live-search-panel" aria-labelledby="live-search-title">
    <div className="live-search-header">
      <div>
        <span className="eyebrow">D-04 · 真实检索能力</span>
        <h2 id="live-search-title">跨入口共享的权限感知搜索</h2>
        <p>当前 Web 调用与 Public API、后续 MCP、Skill、Agent 相同的 <code>search_knowledge</code> 契约。</p>
      </div>
      {query.data && <div className="search-runtime-badge">
        <span>{query.data.backend === 'postgres' ? 'PostgreSQL 基线' : 'OpenSearch POC'}</span>
        <strong>{query.data.took_ms.toFixed(1)} ms</strong>
      </div>}
    </div>
    <form className="live-search-form" onSubmit={submit}>
      <label htmlFor="live-search-input" className="sr-only">搜索学校知识对象</label>
      <input
        id="live-search-input"
        value={input}
        onChange={(event) => setInput(event.target.value)}
        placeholder="输入学者、成果、项目、资源或专业术语"
        maxLength={500}
      />
      <button className="primary-button" type="submit" disabled={!input.trim() || query.isFetching}>
        {query.isFetching ? '检索中…' : '检索知识'}
      </button>
    </form>
    <div className="live-search-results" aria-live="polite">
      {query.isPending ? <p className="live-search-state">正在读取权限过滤后的检索投影…</p>
        : query.isError ? <p className="live-search-state error">检索暂不可用：{query.error.message}</p>
          : query.data.hits.length === 0 ? <p className="live-search-state">当前身份下没有匹配结果，也不会显示受限对象计数。</p>
            : query.data.hits.map((hit) => <article key={hit.object_id} className="live-search-hit">
              <div>
                <span>{typeLabels[hit.object_type] ?? hit.object_type}</span>
                <small>{hit.recall_channels.join(' + ')} · score {hit.score.toFixed(2)}</small>
              </div>
              <strong>{hit.canonical_name}</strong>
              <p>{hit.description ?? '暂无可展示摘要'}</p>
              <footer>对象 v{hit.object_version} · 投影 {hit.projection_version}</footer>
            </article>)}
    </div>
    {query.data?.warnings?.map((warning) => <p className="live-search-warning" key={warning}>
      评测边界：{warning}
    </p>)}
  </section>;
}
