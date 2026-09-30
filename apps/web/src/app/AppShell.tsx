import { Notice as InlineNotification } from '../shared/components/Notice';
import { useDeferredValue, useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Analytics, ChartRelationship, Close, Document, Education, Home, Information, Search as SearchIcon, UserAvatar, UserMultiple } from '@carbon/icons-react';
import { Button, Header, HeaderGlobalAction, HeaderGlobalBar, HeaderMenuButton, HeaderMenuItem, HeaderName, HeaderNavigation, InlineLoading,  Search, SideNav, SideNavItems, SideNavLink, SkipToContent, Tag, Theme } from '@carbon/react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import type { SearchHit } from '../generated/smartlib-api';
import { searchVisibleKnowledge } from '../shared/api/smartlib';

const objectTypeLabels: Record<string, string> = {
  person: '学者', publication: '论文', organization: '机构', department: '院系',
  discipline: '学科', funding_program: '资助计划', project: '项目', journal: '期刊', concept: '研究主题', dataset: '数据集',
};

const navigation = [
  { href: '/', label: '搜索与发现', icon: Home },
  { href: '/graph-analytics', label: '图谱分析', icon: ChartRelationship },
  { href: '/scholars', label: '学者目录', icon: UserMultiple },
  { href: '/outputs', label: '科研成果', icon: Document },
  { href: '/institutions', label: '机构字典', icon: Education },
  { href: '/leadership', label: '领导工作台', icon: Analytics },
];

function navigationActive(pathname: string, href: string) {
  if (href === '/') return pathname === '/' || pathname === '/search';
  return pathname === href || pathname.startsWith(`${href}/`);
}

function resultTarget(hit: SearchHit) {
  if (hit.object_type === 'person') return `/scholars/${encodeURIComponent(hit.object_id)}`;
  return `/?q=${encodeURIComponent(hit.canonical_name)}&type=${hit.object_type}`;
}

function GlobalSearch({ onClose }: { onClose: () => void }) {
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query.trim());
  const navigate = useNavigate();
  const result = useQuery({
    queryKey: ['global-search', deferredQuery],
    queryFn: ({ signal }) => searchVisibleKnowledge(deferredQuery, signal),
    enabled: deferredQuery.length >= 2,
  });

  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [onClose]);

  const openResult = (hit: SearchHit) => {
    void navigate(resultTarget(hit));
    onClose();
  };

  return <div className="sg-search-layer" role="dialog" aria-modal="true" aria-labelledby="sg-search-title">
    <button className="sg-search-scrim" aria-label="关闭全局搜索" onClick={onClose} />
    <section className="sg-global-search">
      <header><div><span>跨知识对象检索</span><h2 id="sg-search-title">搜索学者、论文、机构和研究主题</h2></div><Button kind="ghost" hasIconOnly renderIcon={Close} iconDescription="关闭" onClick={onClose} /></header>
      <Search autoFocus size="lg" labelText="全局搜索" placeholder="输入姓名、论文题名、机构或研究主题" value={query} onChange={(event) => setQuery(event.target.value)} />
      <div className="sg-search-body">
        {deferredQuery.length < 2 && <div className="sg-search-prompt"><SearchIcon size={24} /><p>输入至少两个字符开始检索。结果来自当前业务检索服务。</p></div>}
        {result.isFetching && <InlineLoading description="正在检索知识对象" />}
        {result.isError && <InlineNotification lowContrast kind="error" title="搜索服务暂不可用" subtitle={`${result.error.message}。学者目录仍可单独使用。`} actionButtonLabel="重试" onActionButtonClick={() => void result.refetch()} />}
        {result.isSuccess && result.data.hits.length === 0 && <div className="sg-search-prompt"><Information size={24} /><p>没有找到匹配结果。可缩短关键词或改用学者目录筛选。</p></div>}
        {result.data?.hits.map((hit) => <button className="sg-search-result" key={hit.object_id} onClick={() => openResult(hit)}>
          <Tag type="cool-gray">{objectTypeLabels[hit.object_type] ?? hit.object_type}</Tag>
          <span><strong>{hit.canonical_name}</strong><small>{hit.description ?? '暂无摘要'}</small></span>
          <span className="sg-search-score">{hit.recall_channels.includes('semantic') ? '语义匹配' : '文本匹配'}</span>
        </button>)}
        {result.data && <footer>共返回 {result.data.hits.length} 条 · {result.data.took_ms.toFixed(1)} ms{result.data.warnings?.length ? ' · 当前检索能力存在限制' : ''}</footer>}
      </div>
    </section>
  </div>;
}

export function AppShell() {
  const location = useLocation();
  const [navOpen, setNavOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);

  return <div className="sg-public-shell">
    <Theme theme="g100">
      <Header aria-label="学者星图">
        <SkipToContent />
        <HeaderMenuButton aria-label={navOpen ? '关闭导航' : '打开导航'} isActive={navOpen} onClick={() => setNavOpen((value) => !value)} />
        <HeaderName href="/" prefix="SmartLib">学者星图</HeaderName>
        <span className="sg-header-context">高校学术知识发现</span>
        <HeaderNavigation aria-label="学者星图主导航">{navigation.map((item) => <HeaderMenuItem key={item.href} href={item.href} isActive={navigationActive(location.pathname, item.href)}>{item.label}</HeaderMenuItem>)}</HeaderNavigation>
        <HeaderGlobalBar>
          <HeaderGlobalAction aria-label="学校领导工作台" tooltipAlignment="end" onClick={() => { window.location.href = '/leadership'; }}><Analytics size={20} /></HeaderGlobalAction>
          <HeaderGlobalAction aria-label="全局搜索" tooltipAlignment="end" onClick={() => setSearchOpen(true)}><SearchIcon size={20} /></HeaderGlobalAction>
          <HeaderGlobalAction aria-label="馆员工作台" tooltipAlignment="end" onClick={() => { window.location.href = '/knowledge-hub'; }}><UserAvatar size={20} /></HeaderGlobalAction>
        </HeaderGlobalBar>
      </Header>
      <SideNav aria-label="学者星图导航" expanded={navOpen} isPersistent={false} onOverlayClick={() => setNavOpen(false)}>
        <SideNavItems>
          {navigation.map((item) => <SideNavLink key={item.href} href={item.href} renderIcon={item.icon} isActive={navigationActive(location.pathname, item.href)}>{item.label}</SideNavLink>)}
          <SideNavLink href="/knowledge-hub" renderIcon={Information}>图书馆知识中台</SideNavLink>
        </SideNavItems>
      </SideNav>
    </Theme>
    <main id="main-content" className="sg-public-content"><Outlet /></main>
    {searchOpen && <GlobalSearch onClose={() => setSearchOpen(false)} />}
  </div>;
}

export function ScholarHomeLink() {
  return <Link to="/scholars">返回学者目录</Link>;
}
