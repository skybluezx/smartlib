import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ScholarGraph } from './ScholarGraph';
import { getScholarNetworkView } from '../../shared/api/smartlib';

const { scholar } = vi.hoisted(() => ({
  scholar: {
    object_id: 'person-1', scholar_id: 'SL-NSF26-0001', canonical_name: '丁俊莹', initials: '丁',
    title: null, department: null, discipline: null, primary_direction: null,
    metrics: { publications: 0, projects: 0, collaborators: 0 }, synthetic: false,
    dataset_version: '2026-nsf-representative-publications-v1', object_version: 1,
    updated_at: '2026-09-01T07:39:17Z',
  },
}));

vi.mock('../../shared/api/smartlib', () => ({
  searchScholarDirectory: vi.fn().mockResolvedValue([scholar]),
  getScholarProfileView: vi.fn().mockResolvedValue({
    summary: scholar,
    description: '论文署名经用户确认的独立作者；不代表本校人事归属。',
    profile_kind: 'fact_profile', disciplines: [], research_directions: [],
    representative_publications: [], projects: [], collaborators: [],
    metric_scope: 'current_visible_approved_relations',
    overview: { counts: { publication: 2, project: 0, person: 3, concept: 4 }, scope: 'current_visible_approved_and_pending', truncated: false,
      papers: ['publication-1', 'publication-2'].map((id, i) => ({ object_id: id, canonical_name: i ? '图谱未返回的论文' : '真实论文题名', description: null, review_state: 'pending', relation_id: `r${i}`, evidence_count: 1, year: 2025, doi: i ? null : '10.1000/example', pmid: null, pmcid: null })) },
  }),
  getScholarNetworkView: vi.fn().mockResolvedValue({
    root_object_id: 'person-1',
    nodes: [
      { object_id: 'person-1', object_type: 'person', canonical_name: '丁俊莹', description: null, object_version: 1, projection_version: 'graph-projection-v1' },
      { object_id: 'publication-1', object_type: 'publication', canonical_name: '真实论文题名', description: 'Crossref 核验论文。', object_version: 1, projection_version: 'graph-projection-v1' },
    ],
    edges: [{ relation_id: 'relation-1', subject_id: 'person-1', object_id: 'publication-1', predicate: 'person.authored', fact_class: 'business_fact', confidence: .5, review_state: 'pending', evidence_ids: ['evidence-1'], relation_version: 1, projection_version: 'graph-projection-v1' }],
    backend: 'hugegraph', projection_version: 'graph-projection-v1', truncated: false, took_ms: 2.7,
  }),
  getKnowledgeNeighborhoodView: vi.fn(),
  getScholarEvidenceView: vi.fn().mockResolvedValue({
    scholar_id: 'SL-NSF26-0001', object_version: 1,
    items: [{ evidence_id: 'evidence-1', object_id: 'publication-1', evidence_type: 'publication', citation: 'Excel row 2 verified against Crossref DOI 10.1000/example', excerpt: 'NCBI PubMed PMID 123456 corroboration', source_reference_id: 'source-ref-1', source_name: 'Crossref REST API', source_version: 'publication-auto-verification-v1', observed_at: '2026-09-01T14:58:33Z', dataset_version: null, synthetic: false, relation_id: 'relation-1', predicate: 'person.authored', fact_class: 'business_fact', confidence: .5, review_state: 'pending' }],
  }),
}));

function renderRoute(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/scholars" element={<ScholarGraph />} /><Route path="/scholars/:scholarId" element={<ScholarGraph />} /></Routes></MemoryRouter></QueryClientProvider>);
}

describe('ScholarGraph', () => {
  it('renders the source-backed directory and missing fields honestly', async () => {
    renderRoute('/scholars');
    expect(await screen.findByText('丁俊莹')).toBeInTheDocument();
    expect(screen.getByText('SL-NSF26-0001')).toBeInTheDocument();
    expect(screen.getAllByText('尚未收录').length).toBeGreaterThan(0);
    expect(screen.getByText('真实业务记录')).toBeInTheDocument();
  });

  it('links profile, publication identifiers, HugeGraph status and evidence', async () => {
    renderRoute('/scholars/SL-NSF26-0001');
    expect(await screen.findByRole('heading', { level: 1, name: '丁俊莹' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '返回学者目录' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '人事登记机构' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '成果署名机构' })).toBeInTheDocument();
    expect(screen.getByText('尚未收录人事登记机构；论文机构不会自动填入此处。')).toBeInTheDocument();
    expect(screen.queryByText('论文署名经用户确认的独立作者；不代表本校人事归属。')).not.toBeInTheDocument();
    expect(screen.queryByText('返回目录和原筛选位置')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '学者目录' })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('tab', { name: /论文成果/ }));
    expect(screen.getByRole('tab', { name: /论文成果 2/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '图谱未返回的论文' })).toHaveAttribute('href', '/outputs/publication-2');
    expect((await screen.findAllByText('真实论文题名')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('10.1000/example').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('tab', { name: /关系网络/ }));
    expect(await screen.findByText('关系图已加载')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '查看数据来源' }));
    expect(await screen.findByText('Crossref REST API')).toBeInTheDocument();
  });
  it('keeps complete counts and papers available when the graph fails', async () => {
    vi.mocked(getScholarNetworkView).mockRejectedValueOnce(new Error('graph unavailable'));
    renderRoute('/scholars/SL-NSF26-0001');
    expect(await screen.findByRole('tab', { name: /论文成果 2/ })).toBeInTheDocument();
    expect(screen.getByText('共同论文作者去重，不含本人')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /论文成果/ }));
    expect(screen.getByRole('link', { name: '图谱未返回的论文' })).toBeInTheDocument();
  });
});
