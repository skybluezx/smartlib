import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SearchLivePanel } from './SearchLivePanel';

vi.mock('../../shared/api/smartlib', () => ({
  searchVisibleKnowledge: vi.fn().mockResolvedValue({
    query_text: 'SmartLib',
    retrieval_mode: 'lexical',
    hits: [{
      object_id: '00000000-0000-0000-0000-000000000001',
      object_type: 'resource',
      canonical_name: 'SmartLib 检索投影验证',
      description: '真实搜索投影',
      score: 2,
      recall_channels: ['lexical'],
      object_version: 1,
      projection_version: 'search-document-v1',
      source_updated_at: '2026-08-25T00:00:00Z',
      evidence_ids: [],
    }],
    facets: { object_types: { resource: 1 } },
    next_cursor: null,
    backend: 'postgres',
    took_ms: 3.2,
    warnings: ['POC baseline'],
  }),
}));

describe('SearchLivePanel', () => {
  it('renders typed, versioned search results from the platform capability', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><SearchLivePanel /></QueryClientProvider>);
    expect(await screen.findByText('SmartLib 检索投影验证')).toBeInTheDocument();
    expect(screen.getByText('PostgreSQL 基线')).toBeInTheDocument();
    expect(screen.getByText(/search-document-v1/)).toBeInTheDocument();
  });
});

