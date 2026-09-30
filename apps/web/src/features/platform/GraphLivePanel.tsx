import { useQuery } from '@tanstack/react-query';
import { getVisibleKnowledgeNetwork } from '../../shared/api/smartlib';

const typeLabels: Record<string, string> = {
  person: '学者', organization: '机构', department: '院系', discipline: '学科',
  funding_program: '资助计划', project: '项目', publication: '成果', journal: '期刊', dataset: '数据集', patent: '专利',
  resource: '资源', event: '事件', concept: '概念', requirement: '需求',
};

const predicateLabels: Record<string, string> = {
  'platform.exposes_capability': '开放统一能力',
  'capability.projects_to': '形成可重建投影',
  'discipline.supported_by': '获得资源支撑',
  'person.collaborates_with': '合作',
  'result.matches_requirement': '匹配需求',
};

export function GraphLivePanel() {
  const query = useQuery({
    queryKey: ['knowledge-network', 'SmartLib 学校知识基础设施'],
    queryFn: () => getVisibleKnowledgeNetwork(),
    staleTime: 15_000,
    retry: 1,
  });

  return <section className="panel live-graph-panel" aria-labelledby="live-graph-title">
    <div className="live-search-header">
      <div>
        <span className="eyebrow">D-05 · 真实知识网络</span>
        <h2 id="live-graph-title">每条关系都能回到规范事实与证据</h2>
        <p>Web 与后续 MCP、Skill、Agent 共用受限的 <code>get_knowledge_neighborhood</code>，不提交 Cypher。</p>
      </div>
      {query.data && <div className="search-runtime-badge">
        <span>{query.data.result.backend === 'postgres' ? 'PostgreSQL 基线' : 'HugeGraph 图投影'}</span>
        <strong>{query.data.result.took_ms.toFixed(1)} ms</strong>
      </div>}
    </div>
    {query.isPending ? <p className="live-search-state">正在读取权限过滤后的知识网络…</p>
      : query.isError ? <p className="live-search-state error">知识网络暂不可用：{query.error.message}</p>
        : <div className="live-graph-content">
          <div className="live-graph-nodes" aria-label="可见知识对象">
            {query.data.result.nodes.map((node) => <article
              className={node.canonical_name === query.data.rootName ? 'graph-node root' : 'graph-node'}
              key={node.object_id}
            >
              <span>{typeLabels[node.object_type] ?? node.object_type}</span>
              <strong>{node.canonical_name}</strong>
              <small>对象 v{node.object_version}</small>
            </article>)}
          </div>
          <div className="live-graph-edges" aria-label="可见知识关系">
            {query.data.result.edges.length === 0
              ? <p className="live-search-state">当前身份下没有可展示关系，也不会返回隐藏路径是否存在。</p>
              : query.data.result.edges.map((edge) => {
                const subject = query.data.result.nodes.find((node) => node.object_id === edge.subject_id);
                const object = query.data.result.nodes.find((node) => node.object_id === edge.object_id);
                return <article key={edge.relation_id}>
                  <span>{subject?.canonical_name ?? '受限对象'}</span>
                  <strong>{predicateLabels[edge.predicate] ?? edge.predicate}</strong>
                  <span>{object?.canonical_name ?? '受限对象'}</span>
                  <small>{edge.fact_class} · {edge.evidence_ids.length} 条可见证据 · 关系 v{edge.relation_version}</small>
                </article>;
              })}
          </div>
          <footer>投影 {query.data.result.projection_version} · 节点与边均在遍历前过滤并在返回后复核</footer>
        </div>}
  </section>;
}
