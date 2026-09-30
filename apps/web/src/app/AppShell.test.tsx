import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AppShell } from './AppShell';

describe('AppShell routing', () => {
  function renderRouter(router: ReturnType<typeof createMemoryRouter>) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  }

  it('provides public academic navigation around the active route', async () => {
    const router = createMemoryRouter([{ path: '/', Component: AppShell, children: [{ path: 'scholars', element: <h1>学者目录内容</h1> }] }], { initialEntries: ['/scholars'] });
    renderRouter(router);
    expect(await screen.findByRole('heading', { level: 1, name: '学者目录内容' })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: '学者目录' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: '搜索与发现' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: '科研成果' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: '机构字典' }).length).toBeGreaterThan(0);
    expect(screen.getByText('高校学术知识发现')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '打开智能分析助手' })).not.toBeInTheDocument();
  });

  it('opens the global search surface without static results', async () => {
    const router = createMemoryRouter([{ path: '/', Component: AppShell, children: [{ index: true, element: <div>内容</div> }] }]);
    renderRouter(router);
    fireEvent.click(screen.getByRole('button', { name: '全局搜索' }));
    expect(await screen.findByRole('dialog', { name: '搜索学者、论文、机构和研究主题' })).toBeInTheDocument();
    expect(screen.getByText('输入至少两个字符开始检索。结果来自当前业务检索服务。')).toBeInTheDocument();
  });
});
