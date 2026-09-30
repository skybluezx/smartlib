import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DirectionExtensions } from '../analytics/DirectionExtensions';
import type { DirectionScheme } from '../../generated/smartlib-api';
import { ResearchWorkbench } from './ResearchWorkbench';

afterEach(() => vi.unstubAllGlobals());
function wrap(node: React.ReactNode) { render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>); }
describe('second phase pages', () => {
  it('shows real scope metrics and supporting papers', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | Request) => Promise.resolve(new Response(JSON.stringify((typeof input === 'string' ? input : input.url).endsWith('/entities') ? [] : {
      papers: 1, classified: 1, directions: [{ code: 'H19', name: '老年医学', version: '2026', count: 1, papers: ['p'] }],
      trends: [], intersections: [], collaboration: [], paper_titles: { p: '测试论文' }, note: '样本范围'
    }), {headers: {'Content-Type': 'application/json'}}))));
    const scheme = { key: 'nsfc', scheme: 'NSFC_APPLICATION_CODE', name: '国自然', version: '2026', covered_publications: 1,
      directions: [{ object_id: 'd', name: '老年医学', publication_ids: ['p'] }] } as DirectionScheme;
    wrap(<DirectionExtensions workspace={{publication_count: 1, schemes: [scheme], papers: [{object_id:'p',title:'测试论文',year:2025}]}} scheme={scheme} />);
    expect(await screen.findByText('年度变化')).toBeInTheDocument();
    expect(screen.getByRole('region', {name:'潜在合作线索列表'})).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '老年医学 · 2025 · 1 篇' }));
    expect(screen.getByRole('link', { name: '测试论文' })).toHaveAttribute('href', '/outputs/p');
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.any(Request)));
    const request = vi.mocked(fetch).mock.calls.find(([input]) => input instanceof Request)?.[0];
    if (!(request instanceof Request)) throw new Error('Expected scoped API request');
    expect(request.url).toContain('/scoped-analysis');
    expect(await request.clone().json()).toEqual({publication_ids:['p'],scheme:'NSFC_APPLICATION_CODE',scheme_version:'2026',collaboration_institution_id:null});
  });
  it('exposes missing standards and empty project data honestly', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve({ ok: true, json: () => Promise.resolve( url.includes('/standards?') ? [] : {
      papers: [], projects: [], entities: [], tasks: [], standards: [], gaps: ['缺少教育部学科目录'], scope: '测试范围'
    }) }))); 
    wrap(<ResearchWorkbench />);
    expect(await screen.findByText('缺少教育部学科目录')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '标准与缺项' }));
    expect(screen.getByRole('button', { name: '核验并导入目录' })).toBeDisabled();
    expect(screen.getByRole('link', { name: /下载格式模板/ })).toHaveAttribute('href', '/research-moe-template.json');
  });
});
