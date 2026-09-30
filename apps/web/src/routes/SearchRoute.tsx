import { Notice as InlineNotification } from '../shared/components/Notice';
import { useState, type SyntheticEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, ChartRelationship, Document, Education, Information, Search as SearchIcon, UserMultiple } from '@carbon/icons-react';
import { Button, Dropdown, InlineLoading,  Search, Tag } from '@carbon/react';
import { Link, useSearchParams } from 'react-router-dom';
import { searchVisibleKnowledge } from '../shared/api/smartlib';

const typeOptions = [
  { id: 'all', label: '全部类型' }, { id: 'person', label: '学者' },
  { id: 'publication', label: '论文' }, { id: 'organization', label: '机构' },
  { id: 'project', label: '项目' }, { id: 'concept', label: '研究主题' },
];
const typeLabels = Object.fromEntries(typeOptions.map((item) => [item.id, item.label]));

function hitTarget(objectType: string, objectId: string, canonicalName: string) {
  if (objectType === 'person') return `/scholars/${encodeURIComponent(objectId)}`;
  if (['publication', 'project', 'patent', 'dataset'].includes(objectType)) return `/outputs?q=${encodeURIComponent(canonicalName)}&type=${objectType}`;
  if (['organization', 'department'].includes(objectType)) return `/institutions/${encodeURIComponent(objectId)}`;
  return null;
}

export function SearchRoute() {
  const [params, setParams] = useSearchParams();
  const [draft, setDraft] = useState(params.get('q') ?? '');
  const query = params.get('q')?.trim() ?? '';
  const type = params.get('type') ?? 'all';
  const result = useQuery({
    queryKey: ['discovery-search', query],
    queryFn: ({ signal }) => searchVisibleKnowledge(query, signal),
    enabled: query.length >= 2,
  });

  const hits = (result.data?.hits ?? []).filter((hit) => type === 'all' || hit.object_type === type);
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = new URLSearchParams(params);
    if (draft.trim()) next.set('q', draft.trim()); else next.delete('q');
    setParams(next);
  };

  return <div className="sg-discovery-page">
    <header className="sg-home-heading"><p>SmartLib 学者星图</p><h1>从一个学者、成果或学术主题开始</h1><span>统一检索学校学术知识，进入学者档案、科研成果目录以及机构关联脉络。</span></header>
    <form className="sg-discovery-toolbar" onSubmit={submit}>
      <Search size="lg" labelText="搜索学术知识" placeholder="输入学者姓名、论文题名、机构或主题" value={draft} onChange={(event) => setDraft(event.target.value)} />
      <Dropdown id="discovery-type" label="结果类型" titleText="分类" items={typeOptions} itemToString={(item) => item?.label ?? ''} selectedItem={typeOptions.find((item) => item.id === type) ?? typeOptions[0]} onChange={({ selectedItem }) => {
        const next = new URLSearchParams(params);
        if (!selectedItem || selectedItem.id === 'all') next.delete('type'); else next.set('type', selectedItem.id);
        setParams(next);
      }} />
      <Button type="submit" renderIcon={SearchIcon}>搜索</Button>
    </form>
    {!query && <nav className="sg-home-entry-grid" aria-label="学者星图主要功能">
      <Link to="/graph-analytics"><ChartRelationship /><span><strong>图谱分析</strong><small>观察基金、人员、机构合作与学科方向</small></span><ArrowRight /></Link>
      <Link to="/scholars"><UserMultiple /><span><strong>学者目录</strong><small>按姓名、机构、学科和方向发现学者</small></span><ArrowRight /></Link>
      <Link to="/outputs"><Document /><span><strong>科研成果</strong><small>查找和浏览论文、项目、专利与数据集</small></span><ArrowRight /></Link>
      <Link to="/institutions"><Education /><span><strong>机构字典</strong><small>查询学校、学院、附属机构和部门</small></span><ArrowRight /></Link>
    </nav>}
    <section className="sg-search-page-results" aria-live="polite">
      {query.length === 1 && <InlineNotification lowContrast kind="info" title="关键词过短" subtitle="请输入至少两个字符。" />}
      {result.isFetching && <InlineLoading description="正在检索" />}
      {result.isError && <InlineNotification lowContrast kind="error" title="搜索服务暂不可用" subtitle={result.error.message} actionButtonLabel="重试" onActionButtonClick={() => void result.refetch()} />}
      {result.isSuccess && <div className="sg-results-summary"><strong>{hits.length}</strong><span>条{typeLabels[type] ?? type}结果</span><small>{result.data.took_ms.toFixed(1)} ms</small></div>}
      {result.isSuccess && hits.length === 0 && <div className="sg-page-empty"><Information size={28} /><h2>没有找到匹配结果</h2><p>尝试缩短关键词、切换结果类型，或进入学者目录浏览。</p><Link to="/scholars">浏览学者目录</Link></div>}
      {hits.map((hit) => { const target = hitTarget(hit.object_type, hit.object_id, hit.canonical_name); return <article className="sg-discovery-result" key={hit.object_id}>
        <div><Tag type="cool-gray">{typeLabels[hit.object_type] ?? hit.object_type}</Tag><small>对象版本 {hit.object_version}</small></div>
        <h2>{hit.canonical_name}</h2>
        <p>{hit.description ?? '该记录尚未提供摘要。'}</p>
        <footer><span>更新于 {new Date(hit.source_updated_at).toLocaleDateString('zh-CN')}</span>{target ? <Link to={target}>{['organization', 'department'].includes(hit.object_type) ? '查看详情' : '进入对应目录'} <ArrowRight /></Link> : <span>该类型的独立目录尚未开放</span>}</footer>
      </article>; })}
    </section>
  </div>;
}
