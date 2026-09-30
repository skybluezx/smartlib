import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { InstitutionDetail } from './InstitutionDetail';

const { getKnowledgeCatalogDetail, getKnowledgeObjectNetwork, getKnowledgeNeighborhoodView } = vi.hoisted(() => ({
  getKnowledgeCatalogDetail: vi.fn(), getKnowledgeObjectNetwork: vi.fn(), getKnowledgeNeighborhoodView: vi.fn(),
}));

vi.mock('../../shared/api/smartlib', () => ({ getKnowledgeCatalogDetail, getKnowledgeObjectNetwork, getKnowledgeNeighborhoodView }));

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/institutions/organization-1']}><InstitutionDetail objectId="organization-1" /></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
  getKnowledgeCatalogDetail.mockResolvedValue({
    object: {
      object_id: 'organization-1', object_type: 'organization', canonical_name: '测试医科大学',
      description: '从论文全文作者单位中提取的机构。', visibility: 'restricted', quality_state: 'unverified',
      review_state: 'pending', version: 1, created_by: 'actor-1', created_at: '2026-09-03T00:00:00Z',
      updated_at: '2026-09-04T00:00:00Z', attributes: { source: 'publication_fulltext', identity_resolution_status: 'normalized_name_pending_review', synthetic: false },
    },
    type_details: { source: 'publication_fulltext', identity_resolution_status: 'normalized_name_pending_review', synthetic: false },
    identifiers: [], contributors: [], resources: [],
    institution_associations: {
      scholar_count: 1, output_count: 3, truncated: false,
      metric_scope: 'institution_descendants_to_approved_scholars_to_approved_outputs',
      scholars: [{ object_id: 'person-1', canonical_name: '测试学者', output_count: 3 }],
      outputs: [{ object_id: 'publication-1', object_type: 'publication', canonical_name: '测试论文', year: 2025, scholar_count: 1 }],
    },
  });
  getKnowledgeObjectNetwork.mockResolvedValue({
    root_object_id: 'organization-1',
    nodes: [
      { object_id: 'organization-1', object_type: 'organization', canonical_name: '测试医科大学', description: null, object_version: 1, projection_version: 'v1' },
      { object_id: 'person-1', object_type: 'person', canonical_name: '测试学者', description: null, object_version: 1, projection_version: 'v1' },
    ],
    edges: [{ relation_id: 'edge-1', subject_id: 'person-1', object_id: 'organization-1', predicate: 'person.affiliated_with', fact_class: 'literature_fact', confidence: .96, review_state: 'approved', evidence_ids: ['evidence-1'], relation_version: 1, projection_version: 'v1' }],
    backend: 'hugegraph', projection_version: 'v1', truncated: false, took_ms: 4,
  });
});

describe('InstitutionDetail', () => {
  it('shows real organization fields, related scholars and the shared interactive graph', async () => {
    renderDetail();
    expect(await screen.findByRole('heading', { level: 1, name: '测试医科大学' })).toBeInTheDocument();
    expect(screen.queryByText('名称已规范化，待复核')).not.toBeInTheDocument();
    expect((await screen.findAllByRole('link', { name: /测试学者/ }))[0]).toHaveAttribute('href', '/scholars/person-1');
    expect(screen.getByRole('link', { name: /测试论文/ })).toHaveAttribute('href', '/outputs/publication-1');
    expect(screen.getByText('经关联学者去重')).toBeInTheDocument();
    expect(await screen.findByText('关系图已加载')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '查看研究方向画像' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '机构字典' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '放大图谱区域' })).toBeInTheDocument();
  });

  it('keeps discipline objects outside the institution dictionary detail', async () => {
    getKnowledgeCatalogDetail.mockResolvedValueOnce({
      object: {
        object_id: 'discipline-1', object_type: 'discipline', canonical_name: '影像医学', description: '申请代码；代码 H27',
        visibility: 'public', quality_state: 'validated', review_state: 'approved', version: 1, created_by: 'actor-1',
        created_at: '2026-09-03T00:00:00Z', updated_at: '2026-09-04T00:00:00Z', attributes: {},
      },
      type_details: { scheme: 'NSFC_APPLICATION_CODE_2026', scheme_code: 'H27', level: 1, official: true, source_authority: '国家自然科学基金委员会', source_url: 'https://example.edu/source' },
      identifiers: [], contributors: [], resources: [],
    });
    renderDetail();
    expect(await screen.findByText('对象类型不适用于本页面')).toBeInTheDocument();
    expect(screen.getByText('请返回机构字典重新选择。')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 1, name: '影像医学' })).not.toBeInTheDocument();
  });
});
