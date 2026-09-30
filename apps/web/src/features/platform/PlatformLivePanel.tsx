import { useQuery } from '@tanstack/react-query';
import { getVisibleKnowledgeObjects } from '../../shared/api/smartlib';

export function PlatformLivePanel() {
  const query = useQuery({
    queryKey: ['knowledge-objects', { limit: 8 }],
    queryFn: () => getVisibleKnowledgeObjects(8),
    staleTime: 30_000,
    retry: 1,
  });

  return <section className="panel live-platform-panel">
    <div><span className={`live-dot ${query.isError ? 'error' : ''}`} /> <strong>真实平台链路</strong><p>Web → FastAPI → PostgreSQL 18 → RLS；这里不读取页面内置数组。</p></div>
    <div className="live-object-summary">
      {query.isPending ? <span>正在读取权威库…</span> : query.isError ? <span>API 暂不可用：{query.error.message}</span> : <><strong>{query.data.length}</strong><span>当前身份可见对象</span>{query.data.slice(0, 3).map((item) => <em key={item.object_id}>{item.canonical_name}</em>)}</>}
    </div>
  </section>;
}
