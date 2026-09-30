import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { KnowledgeCatalog } from './KnowledgeCatalog';

const { getKnowledgeCatalog, getOrganizationHierarchyFilterOptions, getProjectKindFilterOptions } = vi.hoisted(() => ({
  getKnowledgeCatalog: vi.fn(),
  getOrganizationHierarchyFilterOptions: vi.fn(),
  getProjectKindFilterOptions: vi.fn(),
}));

vi.mock('../../shared/api/smartlib', () => ({
  getKnowledgeCatalog,
  getOrganizationHierarchyFilterOptions,
  getProjectKindFilterOptions,
}));

function renderCatalog(kind: 'outputs' | 'institutions', initialEntry = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const outputs = kind === 'outputs';
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[initialEntry]}><KnowledgeCatalog
    title={outputs ? '科研成果' : '机构字典'}
    description="真实业务目录"
    searchPlaceholder="搜索"
    kind={kind}
    showTypeFilter={outputs}
    types={outputs ? [{ id: 'publication', label: '论文' }, { id: 'project', label: '项目' }] : [
      { id: 'organization', label: '机构' },
      { id: 'department', label: '学院与部门' },
    ]}
  /></MemoryRouter></QueryClientProvider>);
}

describe('KnowledgeCatalog', () => {
  beforeEach(() => {
    getKnowledgeCatalog.mockReset();
    getOrganizationHierarchyFilterOptions.mockReset();
    getOrganizationHierarchyFilterOptions.mockResolvedValue({
      scopes: [{
        object_id: '85000000-0000-4000-8000-000000000011',
        canonical_name: '大连医科大学',
        descendant_count: 48,
      }],
      levels: [1, 2],
    });
    getProjectKindFilterOptions.mockReset();
    getProjectKindFilterOptions.mockResolvedValue({
      items: [{
        object_id: '85000000-0000-4000-8000-000000000099',
        canonical_name: '国家自然科学基金面上项目',
        category_label: '境内中央公共资助',
        project_count: 36,
      }],
    });
  });

  it('renders source-backed publication identifiers and total', async () => {
    getKnowledgeCatalog.mockResolvedValueOnce({
      total: 155, page: 1, page_size: 20,
      items: [{
        object_id: '85000000-0000-4000-8000-000000000001', object_type: 'publication',
        canonical_name: '真实论文题名', description: 'Crossref 核验元数据。', visibility: 'campus',
        quality_state: 'validated', review_state: 'approved', version: 1,
        attributes: { doi: '10.1000/example', year: 2025 },
        created_by: '71000000-0000-4000-8000-000000000001',
        created_at: '2026-09-03T00:00:00Z', updated_at: '2026-09-03T00:00:00Z',
      }],
    });
    renderCatalog('outputs');
    expect(await screen.findByRole('heading', { name: '真实论文题名' })).toBeInTheDocument();
    expect(screen.getByText('155')).toBeInTheDocument();
    expect(screen.getByText('10.1000/example')).toBeInTheDocument();
  });

  it('shows an honest empty institution state', async () => {
    getKnowledgeCatalog.mockResolvedValueOnce({ total: 0, page: 1, page_size: 20, items: [] });
    renderCatalog('institutions');
    expect(await screen.findByRole('heading', { name: '当前暂无可展示的机构字典' })).toBeInTheDocument();
    expect(screen.getByText(/未关联的机构元数据不会在此展示/)).toBeInTheDocument();
    expect(screen.queryByText('类型')).not.toBeInTheDocument();
    expect(getKnowledgeCatalog).toHaveBeenCalledWith(
      expect.objectContaining({ linkedOnly: true }),
      expect.any(AbortSignal),
    );
  });

  it('shows the verified parent path for a non-top-level organization', async () => {
    getKnowledgeCatalog.mockResolvedValueOnce({
      total: 1, page: 1, page_size: 20,
      items: [{
        object_id: '85000000-0000-4000-8000-000000000010', object_type: 'organization',
        canonical_name: '大连医科大学基础医学院', description: null, visibility: 'campus',
        quality_state: 'validated', review_state: 'approved', version: 1,
        attributes: { organization_level: '2' },
        hierarchy_path: [{
          object_id: '85000000-0000-4000-8000-000000000011',
          object_type: 'organization', canonical_name: '大连医科大学',
        }],
        created_by: '71000000-0000-4000-8000-000000000001',
        created_at: '2026-09-08T00:00:00Z', updated_at: '2026-09-08T00:00:00Z',
      }],
    });

    const { container } = renderCatalog('institutions');

    const toggle = await screen.findByText('1 个下级机构');
    expect(toggle.closest('details')).not.toHaveAttribute('open');
    fireEvent.click(toggle);
    expect(toggle.closest('details')).toHaveAttribute('open');
    expect(screen.getByText('二级')).toBeInTheDocument();
    expect(screen.getByText('二级').closest('.sg-catalog-level')).toHaveTextContent('二级');
    expect(container.querySelector('.sg-catalog-type')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '大连医科大学' })).toHaveAttribute(
      'href', '/institutions/85000000-0000-4000-8000-000000000011',
    );
    expect(screen.getAllByText('大连医科大学基础医学院')).toHaveLength(1);
    fireEvent.click(toggle);
    expect(toggle.closest('details')).not.toHaveAttribute('open');
  });

  it('groups children across API pages without duplicating parents or merging names', async () => {
    const parent = { object_id: 'parent', object_type: 'organization', canonical_name: '学校', attributes: { organization_level: 1 }, hierarchy_path: [] };
    const child = { object_id: 'child', object_type: 'organization', canonical_name: '学院', attributes: { organization_level: 2 }, hierarchy_path: [{ object_id: 'parent', canonical_name: '学校', object_type: 'organization' }] };
    const unrelated = { ...parent, object_id: 'unrelated' };
    getKnowledgeCatalog.mockResolvedValueOnce({ total: 3, page: 1, page_size: 2, items: [parent, unrelated] });
    getKnowledgeCatalog.mockResolvedValueOnce({ total: 3, page: 2, page_size: 2, items: [child] });
    const { container } = renderCatalog('institutions');
    const toggle = await screen.findByText('1 个下级机构');
    expect(getKnowledgeCatalog).toHaveBeenCalledTimes(2);
    expect(container.querySelectorAll('.sg-institution-tree-group')).toHaveLength(2);
    expect(screen.getAllByRole('heading', { name: '学校' })).toHaveLength(2);
    expect(toggle.closest('details')).not.toHaveAttribute('open');
    expect(toggle.closest('section')?.querySelectorAll('li')).toHaveLength(1);
  });

  it('shows a level tag without a redundant hierarchy row for a top-level organization', async () => {
    getKnowledgeCatalog.mockResolvedValueOnce({
      total: 1, page: 1, page_size: 20,
      items: [{
        object_id: '85000000-0000-4000-8000-000000000011', object_type: 'organization',
        canonical_name: '大连医科大学', description: null, visibility: 'campus',
        quality_state: 'validated', review_state: 'approved', version: 1,
        attributes: { organization_level: '1' }, hierarchy_path: [],
        created_by: '71000000-0000-4000-8000-000000000001',
        created_at: '2026-09-08T00:00:00Z', updated_at: '2026-09-08T00:00:00Z',
      }],
    });

    renderCatalog('institutions');

    expect(await screen.findByText('一级')).toBeInTheDocument();
    expect(screen.queryByText('机构层次')).not.toBeInTheDocument();
  });

  it('uses server-side organization scope and level filters from the URL', async () => {
    getKnowledgeCatalog.mockResolvedValueOnce({ total: 0, page: 1, page_size: 100, items: [] });

    renderCatalog(
      'institutions',
      '/institutions?root=85000000-0000-4000-8000-000000000011&level=2',
    );

    expect(await screen.findByText('查看范围')).toBeInTheDocument();
    expect(screen.getByText('查看粒度')).toBeInTheDocument();
    await waitFor(() => expect(getKnowledgeCatalog).toHaveBeenCalledWith(
      expect.objectContaining({
        objectTypes: ['organization', 'department'],
        hierarchyRootId: '85000000-0000-4000-8000-000000000011',
        organizationLevel: 2,
      }),
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText('大连医科大学')).toBeInTheDocument();
    expect(screen.getByText('仅二级机构')).toBeInTheDocument();
  });

  it('shows individual grant ownership and pending identifiers', async () => {
    getKnowledgeCatalog.mockResolvedValueOnce({
      total: 58, page: 1, page_size: 20,
      items: [{
        object_id: '85000000-0000-4000-8000-000000000058', object_type: 'project',
        canonical_name: '丁俊莹 | 2026年度国家自然科学基金获批项目 (项目名称待补)',
        description: '项目详细信息待补。', visibility: 'restricted',
        quality_state: 'unverified', review_state: 'pending', version: 1,
        attributes: { year: 2026, principal_investigator_name: '丁俊莹' },
        created_by: '71000000-0000-4000-8000-000000000001',
        created_at: '2026-09-04T00:00:00Z', updated_at: '2026-09-04T00:00:00Z',
      }],
    });
    renderCatalog('outputs');
    expect(await screen.findByText('负责人 丁俊莹')).toBeInTheDocument();
    expect(screen.getByText('类别待补')).toBeInTheDocument();
    expect(screen.getByText('批准号待补')).toBeInTheDocument();
  });

  it('shows and applies the project-kind filter only for project results', async () => {
    getKnowledgeCatalog.mockResolvedValue({ total: 36, page: 1, page_size: 20, items: [] });

    renderCatalog(
      'outputs',
      '/outputs?type=project&projectKind=85000000-0000-4000-8000-000000000099',
    );

    expect(await screen.findByText('项目种类')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('combobox', { name: '项目种类' })).toHaveValue(
      '国家自然科学基金面上项目（36）',
    ));
    await waitFor(() => expect(getKnowledgeCatalog).toHaveBeenCalledWith(
      expect.objectContaining({
        objectTypes: ['project'],
        projectKindId: '85000000-0000-4000-8000-000000000099',
      }),
      expect.any(AbortSignal),
    ));
  });

  it('does not load project kinds while browsing all output types', async () => {
    getKnowledgeCatalog.mockResolvedValue({ total: 0, page: 1, page_size: 20, items: [] });

    renderCatalog('outputs');

    await screen.findByRole('heading', { name: '当前暂无可展示的科研成果' });
    expect(screen.queryByText('项目种类')).not.toBeInTheDocument();
    expect(getProjectKindFilterOptions).not.toHaveBeenCalled();
  });
});
