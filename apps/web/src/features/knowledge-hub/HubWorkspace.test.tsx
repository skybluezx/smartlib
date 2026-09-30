import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HubWorkspace } from './HubWorkspace';
import { HubSettingsBanner } from './HubSettingsBanner';
import { hubRequest } from './hubApi';
import type * as HubApiModule from './hubApi';

vi.mock('./hubApi', async importOriginal => ({
  ...await importOriginal<typeof HubApiModule>(), hubRequest: vi.fn(),
}));
const request = vi.mocked(hubRequest);
const libraryRecord = {
  id: 'record-1', name: '到馆人次', metric_code: 'visits', period: '2026-09-01',
  organization: '图书馆', value: 12, unit: '人次', source_reference: '月报', note: '', version: 2,
};
function renderWorkspace(section: string, permissions = ['knowledge_hub.manage']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{
    path: '/knowledge-hub', element: <Outlet context={{ permissions }} />,
    children: [{ path: ':section', element: <HubWorkspace /> }],
  }], { initialEntries: [`/knowledge-hub/${section}`] });
  return render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
}
beforeEach(() => { request.mockReset(); });

describe('knowledge hub workbench', () => {
  it('reads live records but hides mutation controls for observers', async () => {
    request.mockResolvedValue({ items: [libraryRecord], total: 1, page: 1, page_size: 25 });
    renderWorkspace('library', ['knowledge_hub.read']);
    expect(await screen.findByText('到馆人次')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '登记月度指标' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '修订' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '详情' })).toBeInTheDocument();
  });
  it('submits a versioned revision without allowing identity changes', async () => {
    request.mockImplementation(path => Promise.resolve(path.includes('options')
      ? { sources: [], domains: [], assets: [] }
      : { items: [libraryRecord], total: 1, page: 1, page_size: 25 }));
    renderWorkspace('library');
    fireEvent.click(await screen.findByRole('button', { name: '修订' }));
    expect(screen.getByLabelText('指标名称')).toBeDisabled();
    expect(screen.getByLabelText('统计月份首日')).toBeDisabled();
    fireEvent.change(screen.getByLabelText('数值'), { target: { value: '14' } });
    fireEvent.change(screen.getByLabelText('登记或变更依据'), { target: { value: '核对月度报表' } });
    await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('/library/record-1/revision', {
      metric_code: 'visits', metric_name: '到馆人次', period: '2026-09-01', organization: '图书馆',
      value: 14, unit: '人次', source_reference: '月报', note: '', base_version: 2, reason: '核对月度报表',
    }));
  });
  it('does not disguise failed requests as an empty successful workspace', async () => {
    request.mockRejectedValue(new Error('权限核验失败'));
    renderWorkspace('resources');
    expect(await screen.findByText('权限核验失败')).toBeInTheDocument();
    expect(screen.queryByText('尚无可见记录')).not.toBeInTheDocument();
  });
  it('retains third-party registration boundaries in the form', async () => {
    request.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25, sources: [], domains: [], assets: [] });
    renderWorkspace('sources');
    fireEvent.click(screen.getByRole('button', { name: '登记来源' }));
    expect(screen.getByLabelText('参考入口地址（不含凭据，可不填）')).toBeInTheDocument();
    expect(screen.getByText(/登记来源不会自动连接第三方系统/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: '保存' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: '取消' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(request.mock.calls.every(call => call[1] === undefined)).toBe(true);
  });
  it('renders saved notice and contact text without rendering HTML', async () => {
    request.mockResolvedValue({ items: [
      { id: '1', code: 'workbench_notice', value: '<b>请核对来源</b>' },
      { id: '2', code: 'service_contact', value: '资源建设部' },
    ] });
    render(<QueryClientProvider client={new QueryClient()}><HubSettingsBanner /></QueryClientProvider>);
    expect(await screen.findByText('<b>请核对来源</b>')).toBeInTheDocument();
    expect(screen.getByText('服务联系：资源建设部')).toBeInTheDocument();
  });
});
