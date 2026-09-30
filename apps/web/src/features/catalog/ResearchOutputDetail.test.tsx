import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ResearchOutputDetail } from './ResearchOutputDetail';

const { getKnowledgeCatalogDetail, getKnowledgeObjectNetwork, getKnowledgeNeighborhoodView, getKnowledgeObjectResourceContentUrl } = vi.hoisted(() => ({
  getKnowledgeCatalogDetail: vi.fn(), getKnowledgeObjectNetwork: vi.fn(), getKnowledgeNeighborhoodView: vi.fn(), getKnowledgeObjectResourceContentUrl: vi.fn(),
}));

vi.mock('../../shared/api/smartlib', () => ({ getKnowledgeCatalogDetail, getKnowledgeObjectNetwork, getKnowledgeNeighborhoodView, getKnowledgeObjectResourceContentUrl }));

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/outputs/85000000-0000-4000-8000-000000000001']}><ResearchOutputDetail objectId="85000000-0000-4000-8000-000000000001" /></MemoryRouter></QueryClientProvider>);
}

const baseObject = {
  object_id: '85000000-0000-4000-8000-000000000001', canonical_name: '真实成果题名',
  description: '真实成果摘要。', visibility: 'campus' as const, quality_state: 'validated',
  review_state: 'approved', version: 2, attributes: {},
  created_by: '71000000-0000-4000-8000-000000000001',
  created_at: '2026-09-04T00:00:00Z', updated_at: '2026-09-04T00:00:00Z',
};

beforeEach(() => {
  getKnowledgeObjectResourceContentUrl.mockReturnValue('/api/v1/catalog/objects/publication/resources/resource/content');
  getKnowledgeObjectNetwork.mockResolvedValue({
    root_object_id: baseObject.object_id,
    nodes: [
      { object_id: baseObject.object_id, object_type: 'publication', canonical_name: '真实成果题名', description: '摘要', object_version: 2, projection_version: 'graph-projection-v1' },
      { object_id: '85000000-0000-4000-8000-000000000002', object_type: 'person', canonical_name: '测试作者', description: null, object_version: 1, projection_version: 'graph-projection-v1' },
    ],
    edges: [{ relation_id: '87000000-0000-4000-8000-000000000001', subject_id: '85000000-0000-4000-8000-000000000002', object_id: baseObject.object_id, predicate: 'person.authored', fact_class: 'human_confirmed', confidence: 1, review_state: 'approved', evidence_ids: ['88000000-0000-4000-8000-000000000001'], relation_version: 1, projection_version: 'graph-projection-v1' }],
    backend: 'hugegraph', projection_version: 'graph-projection-v1', truncated: false, took_ms: 8.2,
  });
});

describe('ResearchOutputDetail', () => {
  it('keeps missing publication-year metrics explicit', async () => {
    getKnowledgeCatalogDetail.mockResolvedValue({
      object: { ...baseObject, object_type: 'publication' },
      type_details: {publication_year: 2024}, journal_metrics: [],
    });
    renderDetail();
    expect(await screen.findByText('尚未收录与论文发表年份（2024 年）匹配的期刊指标。')).toBeInTheDocument();
    expect(screen.queryByRole('region', {name: '期刊指标明细，可横向滚动'})).not.toBeInTheDocument();
  });

  it('shows publication metadata, identifiers, author roles, fulltext and graph evidence', async () => {
    getKnowledgeCatalogDetail.mockResolvedValue({
      object: { ...baseObject, object_type: 'publication' },
      type_details: { journal_name: 'Journal of Tests', publication_year: 2025, publication_status: 'published', fulltext_state: 'extracted' },
      journal_metrics: [{record_id: 'metric-1', metric_system: 'jcr', metric_year: 2025, release_id: 'release-1', release_label: 'JCR 2025', impact_factor: 8.2, quartile: 'Q1', categories: ['Biology'], source_row_number: 10}],
      identifiers: [{ identifier_type: 'doi', value: '10.1000/example', is_primary: true, verification_status: 'matched' }],
      contributors: [{ order: 1, name: '测试作者', person_object_id: '85000000-0000-4000-8000-000000000002', roles: ['first_author', 'corresponding_author'], verification_status: 'matched' }],
      resources: [
        { resource_id: '89000000-0000-4000-8000-000000000001', file_name: 'paper.pdf', mime_type: 'application/pdf', resource_role: 'article', size_bytes: 2048, extraction_state: 'extracted', license_tags: [] },
        { resource_id: '89000000-0000-4000-8000-000000000002', file_name: 'correction.pdf', mime_type: 'application/pdf', resource_role: 'correction', size_bytes: 1024, extraction_state: 'extracted', license_tags: [] },
        { resource_id: '89000000-0000-4000-8000-000000000003', file_name: 'supporting.pdf', mime_type: 'application/pdf', resource_role: 'supplementary', size_bytes: 4096, extraction_state: 'extracted', license_tags: [] },
      ],
    });
    renderDetail();
    expect(await screen.findByRole('heading', { level: 1, name: '真实成果题名' })).toBeInTheDocument();
    expect(screen.getByText('Journal of Tests')).toBeInTheDocument();
    expect(screen.getByRole('heading', {name:'论文发表年期刊指标'})).toBeInTheDocument();
    expect(screen.getByText('8.2')).toBeInTheDocument();
    expect(screen.getByText('Biology')).toBeInTheDocument();
    expect(screen.getByText('JCR 2025')).toBeInTheDocument();
    expect(screen.getByText('10.1000/example')).toBeInTheDocument();
    expect(screen.getByText('第一作者')).toBeInTheDocument();
    expect(screen.getByText('通讯作者')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看学者 测试作者 的详情' })).toHaveAttribute('href', '/scholars/85000000-0000-4000-8000-000000000002');
    expect(screen.getByRole('link', { name: '查看学者 测试作者 的详情' })).toHaveTextContent('学者');
    expect(screen.getByText('paper.pdf')).toBeInTheDocument();
    expect(screen.getByText('correction.pdf')).toBeInTheDocument();
    expect(screen.getByText('论文全文')).toBeInTheDocument();
    expect(screen.getByText('勘误文件')).toBeInTheDocument();
    expect(screen.getByText('补充材料')).toBeInTheDocument();
    expect(screen.getByText('supporting.pdf')).toBeInTheDocument();
    const resourcesSection = screen.getByRole('heading', { level: 2, name: '全文资源' }).closest('section');
    if (!resourcesSection) throw new Error('全文资源区域未渲染');
    expect(within(resourcesSection).queryByText('全文已解析')).not.toBeInTheDocument();
    const readButton = screen.getAllByRole('button', { name: '阅读全文' })[0];
    if (!readButton) throw new Error('阅读按钮未渲染');
    fireEvent.click(readButton);
    const reader = screen.getByRole('dialog', { name: '全文阅读窗口' });
    expect(reader).toBeInTheDocument();
    expect(within(reader).queryByText('论文全文')).not.toBeInTheDocument();
    expect(within(reader).queryByText('在下方阅读区内上下滚动浏览全部页面')).not.toBeInTheDocument();
    expect(within(reader).queryByText('paper.pdf')).not.toBeInTheDocument();
    const expandButton = within(reader).getByRole('button', { name: '放大阅读窗口' });
    fireEvent.click(expandButton);
    expect(within(reader).getByRole('button', { name: '还原阅读窗口' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTitle('真实成果题名全文 PDF')).toHaveAttribute('src', '/api/v1/catalog/objects/publication/resources/resource/content');
    expect(await screen.findByRole('heading', {name: '图谱关系'})).toBeInTheDocument();
    expect(screen.getByText(/1 条依据/)).toBeInTheDocument();
  });

  it('uses project-specific fields and keeps missing values explicit', async () => {
    getKnowledgeCatalogDetail.mockResolvedValue({
      object: { ...baseObject, object_type: 'project', canonical_name: '丁俊莹的国自然项目' },
      type_details: { principal_investigator_name: '丁俊莹', year: 2026 }, identifiers: [], contributors: [], resources: [],
    });
    getKnowledgeObjectNetwork.mockResolvedValueOnce({
      root_object_id: baseObject.object_id, nodes: [], edges: [], backend: 'hugegraph', projection_version: 'graph-projection-v1', truncated: false, took_ms: 2,
    });
    renderDetail();
    expect(await screen.findByText('负责人')).toBeInTheDocument();
    expect(screen.getByText('丁俊莹')).toBeInTheDocument();
    expect(screen.getByText('项目类别')).toBeInTheDocument();
    expect(screen.getAllByText('尚未收录').length).toBeGreaterThan(0);
  });

  it('distinguishes supported outputs from the unestablished project investigator', async () => {
    const attributes = { principal_investigator_status: 'not_established', funding_program_id: 'kind-001', grant_number: 'TEST-001' };
    getKnowledgeCatalogDetail.mockResolvedValue({
      object: { ...baseObject, object_type: 'project', attributes },
      type_details: attributes, identifiers: [], contributors: [], resources: [],
    });
    getKnowledgeObjectNetwork.mockResolvedValueOnce({ root_object_id: baseObject.object_id, nodes: [], edges: [], backend: 'hugegraph', projection_version: 'graph-projection-v1', truncated: false, took_ms: 1 });
    renderDetail();
    expect(await screen.findByText('项目负责人尚未建立')).toBeInTheDocument();
    expect(screen.queryByText('资助来源类别（暂定）')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '查看项目种类及分类' })).toHaveAttribute('href', '/outputs/kind-001');
    expect(screen.getByText(/论文作者不等同项目申请人或负责人/)).toBeInTheDocument();
    expect(screen.getByText('尚未建立')).toBeInTheDocument();
  });

  it('owns source classification on the project kind, not a concrete project', async () => {
    const attributes = { record_kind: 'funding_category', funding_source_category_label: '境内中央公共资助' };
    getKnowledgeCatalogDetail.mockResolvedValue({ object: { ...baseObject, object_type: 'funding_program', attributes }, type_details: attributes, identifiers: [], contributors: [], resources: [] });
    renderDetail();
    expect(await screen.findByText('资助来源类别（暂定）')).toBeInTheDocument();
    expect(screen.getByText('境内中央公共资助')).toBeInTheDocument();
    expect(screen.getByText(/不是一项具体科研成果/)).toBeInTheDocument();
  });
});
