import './knowledgeHub.css';
import { useQuery } from '@tanstack/react-query';
import {
  Apps,
  Catalog,
  ChartRelationship,
  CheckmarkOutline,
  CloudMonitoring,
  DataBase,
  DocumentImport,
  IbmKnowledgeCatalog,
  ListChecked,
  Security,
  Settings,
  UserRole,
  type CarbonIconType,
} from '@carbon/icons-react';
import {
  Content,
  Header,
  HeaderGlobalAction,
  HeaderGlobalBar,
  HeaderMenuButton,
  HeaderName,
  SideNav,
  SideNavItems,
  SideNavLink,
  SkipToContent,
  Theme,
} from '@carbon/react';
import { useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { getKnowledgeHubSessionView } from '../../shared/api/smartlib';
import { HubSettingsBanner } from './HubSettingsBanner';

const navGroups: { label:string; items:{path:string;label:string;icon:CarbonIconType}[] }[] = [
  {label:'工作台',items:[{path:'',label:'工作总览',icon:CloudMonitoring},{path:'jobs',label:'批次与任务',icon:ListChecked}]},
  {label:'数据接入与治理',items:[{path:'sources',label:'数据来源与接入',icon:DataBase},{path:'imports',label:'论文导入',icon:DocumentImport},{path:'verifications/publications',label:'论文核验',icon:CheckmarkOutline},{path:'changes',label:'清洗与变更',icon:ListChecked},{path:'governance',label:'数据质量',icon:IbmKnowledgeCatalog},{path:'rules',label:'质量规则',icon:ListChecked},{path:'research',label:'研究方向治理',icon:ChartRelationship}]},
  {label:'资源与元数据',items:[{path:'domains',label:'治理域',icon:IbmKnowledgeCatalog},{path:'resources',label:'资源资产',icon:Catalog},{path:'licenses',label:'资源许可',icon:Security},{path:'metadata',label:'元数据定义',icon:IbmKnowledgeCatalog},{path:'journals',label:'期刊指标',icon:Catalog},{path:'library',label:'馆务数据',icon:DataBase}]},
  {label:'分析与应用服务',items:[{path:'analysis',label:'数据分析',icon:ChartRelationship},{path:'graph',label:'知识图谱运行',icon:ChartRelationship},{path:'search-index',label:'搜索索引运行',icon:Catalog},{path:'applications',label:'应用服务',icon:Apps}]},
  {label:'平台管理',items:[{path:'history',label:'版本与追溯',icon:ListChecked},{path:'audit',label:'操作审计',icon:ListChecked},{path:'access',label:'当前身份与权限',icon:UserRole},{path:'settings',label:'工作台设置',icon:Settings}]},
];

export interface KnowledgeHubOutletContext {
  permissions: string[];
}

function AccessBoundary({ permissions }: { permissions: string[] }) {
  if (!permissions.includes('knowledge_hub.read')) {
    return <section className="kh-boundary" role="alert">
      <Security size={32} />
      <h1>没有知识中台访问权限</h1>
      <p>当前身份已经通过后端鉴权，但未分配知识中台角色。请联系系统管理员授予相应角色。</p>
      <code>knowledge_hub.read</code>
    </section>;
  }
  return <><HubSettingsBanner /><Outlet context={{ permissions } satisfies KnowledgeHubOutletContext} /></>;
}

export function KnowledgeHubShell() {
  const [navOpen, setNavOpen] = useState(() => window.innerWidth >= 1056);
  const location = useLocation();
  const session = useQuery({ queryKey: ['knowledge-hub-session'], queryFn: getKnowledgeHubSessionView });
  useEffect(() => {
    const previous = document.title;
    const current = navGroups.flatMap(group => group.items).find(item =>
      '/knowledge-hub' + (item.path ? '/' + item.path : '') === location.pathname);
    document.title = `${current?.label ?? '馆员工作台'} · 图书馆知识中台`;
    return () => { document.title = previous; };
  }, [location.pathname]);

  return <div className={`kh-root ${navOpen ? 'kh-nav-open' : ''}`}>
    <Theme theme="g100">
      <Header aria-label="图书馆知识中台">
        <SkipToContent />
        <HeaderMenuButton aria-label={navOpen ? '关闭导航' : '打开导航'} isActive={navOpen} onClick={() => setNavOpen((value) => !value)} />
        <HeaderName href="/knowledge-hub" prefix="SmartLib">图书馆知识中台</HeaderName>
        <HeaderGlobalBar>
          <HeaderGlobalAction aria-label="返回学者星图" tooltipAlignment="end" onClick={() => { window.location.href = '/'; }}>
            <DataBase size={20} />
          </HeaderGlobalAction>
        </HeaderGlobalBar>
      </Header>
    </Theme>
    <Theme theme="white">
      <SideNav aria-label="知识中台导航" expanded={navOpen} isPersistent={false} onOverlayClick={() => setNavOpen(false)}>
        <SideNavItems>
          {navGroups.map(group => <li key={group.label} className="kh-nav-group"><h2>{group.label}</h2><ul>{group.items.map(item => {
            const path='/knowledge-hub'+(item.path?'/'+item.path:'');
            return <SideNavLink key={path} href={path} renderIcon={item.icon} isActive={location.pathname===path}>{item.label}</SideNavLink>;
          })}</ul></li>)}
        </SideNavItems>
      </SideNav>
    </Theme>
    <Content id="main-content" className="kh-content">
      {session.isPending ? <div className="kh-shell-loading" aria-label="正在核验访问权限"><span /><span /><span /></div>
        : session.isError ? <section className="kh-boundary" role="alert"><Security size={32} /><h1>无法核验访问权限</h1><p>{session.error.message}</p><button className="cds--btn cds--btn--secondary" onClick={() => void session.refetch()}>重试</button></section>
          : <AccessBoundary permissions={session.data.permissions} />}
    </Content>
  </div>;
}
