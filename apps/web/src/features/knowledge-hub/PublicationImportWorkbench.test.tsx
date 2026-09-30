import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { PublicationImportWorkbench } from './PublicationImportWorkbench';

function renderPage(permissions: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([
    {
      path: '/',
      element: <Outlet context={{ permissions }} />,
      children: [{ index: true, element: <PublicationImportWorkbench /> }],
    },
  ]);
  return render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
}

describe('PublicationImportWorkbench', () => {
  it('explains the intake contract before offering single and batch entry', () => {
    renderPage(['publication_intake.submit']);
    expect(screen.getByRole('heading', { name: '最低接收标准' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '自动核验资格' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '单篇录入' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '批量导入' })).toBeInTheDocument();
  });

  it('keeps the contract visible but disables submission without permission', () => {
    renderPage([]);
    expect(screen.getByText('当前角色只有查看权限')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '提交并进入核验流程' })).toBeDisabled();
  });
});
