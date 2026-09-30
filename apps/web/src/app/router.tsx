import { ArrowLeft } from '@carbon/icons-react';
import { createBrowserRouter, Link, Navigate } from 'react-router-dom';
import { AppShell } from './AppShell';
import { KnowledgeHubShell } from '../features/knowledge-hub/KnowledgeHubShell';
import { LeadershipShell } from '../features/leadership/LeadershipShell';

const unavailableRoute = async () => ({
  Component: (await import('../routes/UnavailableRoute')).UnavailableRoute,
});

function RouteError() {
  return <main className="sg-public-content"><section className="sg-page-empty"><strong>页面不存在或暂时不可用</strong><p>请返回搜索与发现首页继续浏览。</p><Link className="cds--btn cds--btn--primary" to="/"><ArrowLeft size={17} /> 返回首页</Link></section></main>;
}

export const router = createBrowserRouter([
  {
    path: '/leadership', Component: LeadershipShell, ErrorBoundary: RouteError,
    children: [
      { index: true, lazy: async () => ({Component: (await import('../features/leadership/LeadershipPages')).LeadershipOverview}) },
      ...Object.entries({talent:'LeadershipTalent',disciplines:'LeadershipDisciplines',research:'LeadershipResearch',resources:'LeadershipResources',recruitment:'LeadershipRecruitment',cultivation:'LeadershipCultivation',teams:'LeadershipTeams',transfer:'LeadershipTransfer'} as const).map(([path,component]) => ({path,lazy:async()=>({Component:(await import('../features/leadership/LeadershipPages'))[component]})})),
      {path:'reports',lazy:async()=>({Component:(await import('../features/leadership/LeadershipReports')).LeadershipReports})},
    ],
  },
  {
    path: '/',
    Component: AppShell,
    ErrorBoundary: RouteError,
    children: [
      { index: true, lazy: async () => ({ Component: (await import('../routes/SearchRoute')).SearchRoute }) },
      { path: 'scholars', lazy: async () => ({ Component: (await import('../routes/ScholarRoute')).ScholarRoute }) },
      { path: 'scholars/:scholarId', lazy: async () => ({ Component: (await import('../routes/ScholarRoute')).ScholarRoute }) },
      { path: 'search', lazy: async () => ({ Component: (await import('../routes/SearchRoute')).SearchRoute }) },
      { path: 'graph-analytics', lazy: async () => ({ Component: (await import('../routes/GraphAnalyticsRoute')).GraphAnalyticsRoute }) },
      { path: 'research-directions', element: <Navigate to="/graph-analytics?tab=disciplines" replace /> },
      { path: 'outputs', lazy: async () => ({ Component: (await import('../routes/ResearchOutputsRoute')).ResearchOutputsRoute }) },
      { path: 'outputs/:objectId', lazy: async () => ({ Component: (await import('../routes/ResearchOutputsRoute')).ResearchOutputsRoute }) },
      { path: 'institutions', lazy: async () => ({ Component: (await import('../routes/InstitutionsRoute')).InstitutionsRoute }) },
      { path: 'institutions/:objectId', lazy: async () => ({ Component: (await import('../routes/InstitutionsRoute')).InstitutionsRoute }) },
      { path: '*', lazy: unavailableRoute },
    ],
  },
  {
    path: '/knowledge-hub',
    Component: KnowledgeHubShell,
    ErrorBoundary: RouteError,
    children: [
      { index: true, lazy: async () => ({ Component: (await import('../features/knowledge-hub/KnowledgeHubOverview')).KnowledgeHubOverview }) },
      { path: 'library', lazy: async () => ({ Component: (await import('../features/knowledge-hub/LibraryWork')).LibraryWork }) },
      { path: 'analysis', lazy: async () => ({ Component: (await import('../features/knowledge-hub/HubAnalysis')).HubAnalysis }) },
      ...['graph','search-index'].map(path => ({ path, lazy: async () => ({ Component: (await import('../features/knowledge-hub/HubOperations')).HubOperations }) })),
      { path: 'changes', lazy: async () => ({ Component: (await import('../features/knowledge-hub/ChangeWorkbench')).ChangeWorkbench }) },
      { path: 'research', lazy: async () => ({ Component: (await import('../features/catalog/ResearchWorkbench')).ResearchWorkbench }) },
      { path: 'history', lazy: async () => ({ Component: (await import('../features/knowledge-hub/HistoryWorkbench')).HistoryWorkbench }) },
      { path: 'imports', lazy: async () => ({ Component: (await import('../features/knowledge-hub/PublicationImportWorkbench')).PublicationImportWorkbench }) },
      { path: 'verifications/publications', lazy: async () => ({ Component: (await import('../features/knowledge-hub/PublicationVerificationWorkbench')).PublicationVerificationWorkbench }) },
      ...['domains','sources','resources','licenses','rules','governance','metadata','library-metrics','applications','settings','jobs','audit','access','journals'].map((path) => ({
        path,
        lazy: async () => ({ Component: (await import('../features/knowledge-hub/HubWorkspace')).HubWorkspace }),
      })),
    ],
  },
]);
