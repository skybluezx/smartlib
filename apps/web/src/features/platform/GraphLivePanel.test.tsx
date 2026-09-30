import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GraphLivePanel } from './GraphLivePanel';

vi.mock('../../shared/api/smartlib', () => ({
  getVisibleKnowledgeNetwork: vi.fn().mockResolvedValue({
    rootName: 'SmartLib 学校知识基础设施',
    result: {
      root_object_id: '00000000-0000-0000-0000-000000000001',
      nodes: [
        { object_id: '00000000-0000-0000-0000-000000000001', object_type: 'concept',
          canonical_name: 'SmartLib 学校知识基础设施', description: null, object_version: 1,
          projection_version: 'canonical-graph-v1' },
        { object_id: '00000000-0000-0000-0000-000000000002', object_type: 'concept',
          canonical_name: 'SmartLib 统一能力接口', description: null, object_version: 1,
          projection_version: 'canonical-graph-v1' },
      ],
      edges: [{ relation_id: '00000000-0000-0000-0000-000000000010',
        subject_id: '00000000-0000-0000-0000-000000000001',
        object_id: '00000000-0000-0000-0000-000000000002', predicate: 'platform.exposes_capability',
        fact_class: 'human_confirmed', confidence: 1, review_state: 'approved', evidence_ids: [],
        relation_version: 1, projection_version: 'canonical-graph-v1' }],
      backend: 'postgres', projection_version: 'canonical-graph-v1', truncated: false, took_ms: 2.4,
    },
  }),
}));

describe('GraphLivePanel', () => {
  it('renders governed nodes, relations and projection version from the graph capability', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><GraphLivePanel /></QueryClientProvider>);
    expect(await screen.findByText('开放统一能力')).toBeInTheDocument();
    expect(screen.getByText('PostgreSQL 基线')).toBeInTheDocument();
    expect(screen.getByText(/canonical-graph-v1/)).toBeInTheDocument();
  });
});
