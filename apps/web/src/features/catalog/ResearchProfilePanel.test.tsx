import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ResearchProfilePanel } from './ResearchProfilePanel';

afterEach(() => vi.unstubAllGlobals());
function show(profile: unknown) {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ profile }) });
  vi.stubGlobal('fetch', fetcher);
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><ResearchProfilePanel objectId="org-1" /></MemoryRouter></QueryClientProvider>);
  return fetcher;
}
describe('ResearchProfilePanel', () => {
  it('shows institution snapshot scope, classifications and supporting paper links', async () => {
    show({ object_type: 'organization', total_papers: 1, start_year: 2025, end_year: 2025,
      coverage: { NSFC_APPLICATION_CODE: 1, MESH: 0 }, papers: [{ publication_id: 'p1', title: '老年护理论文', year: 2025 }],
      rows: [{ scheme: 'NSFC_APPLICATION_CODE', scheme_version: '2026', code: 'H19', name: '老年医学', paper_count: 1, primary_paper_count: 1, publication_ids: ['p1'], pending_publication_ids: ['p1'], source_kinds: ['algorithmic_inference'] }] });
    expect(await screen.findByText(/仅统计论文中明确署名于本机构/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: '研究方向画像' })).toHaveAttribute('id', 'research-profile');
    expect(screen.getByRole('region', { name: '研究方向画像' })).toHaveClass('sg-research-profile');
    expect(screen.getByLabelText('分类口径').closest('.sg-research-profile-controls')).not.toBeNull();
    fireEvent.click(screen.getByText(/老年医学（H19）/));
    expect(screen.queryByText(/含 1 篇待审核/)).not.toBeInTheDocument();
    expect(screen.queryByText(/经确认采用/)).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '老年护理论文' })).toHaveAttribute('href', '/outputs/p1');
    fireEvent.change(screen.getByLabelText('分类口径'), { target: { value: 'MESH' } });
    expect(screen.getByText('暂时还不能展示研究方向')).toBeInTheDocument();
    expect(screen.getByText(/尚无带来源依据的可展示分类/)).toBeInTheDocument();
  });
  it('explains empty scope without manufacturing a profile', async () => {
    show(null);
    expect(await screen.findByText('所选范围暂无可用于画像的论文。')).toBeInTheDocument();
  });
});
