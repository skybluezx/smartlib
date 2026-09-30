import { requiredValue } from '../../shared/requiredValue';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GraphEdge, NeighborhoodResult } from '../../generated/smartlib-api';
import { InteractiveRelationshipGraph } from './InteractiveRelationshipGraph';

const { getKnowledgeNeighborhoodView } = vi.hoisted(() => ({ getKnowledgeNeighborhoodView: vi.fn() }));
vi.mock('../../shared/api/smartlib', () => ({ getKnowledgeNeighborhoodView }));

const initialNetwork: NeighborhoodResult = {
  root_object_id: 'person-1',
  nodes: [
    { object_id: 'person-1', object_type: 'person', canonical_name: '测试学者', description: null, object_version: 1, projection_version: 'v1' },
    { object_id: 'publication-1', object_type: 'publication', canonical_name: '测试论文', description: null, object_version: 1, projection_version: 'v1' },
  ],
  edges: [
    { relation_id: 'edge-1', subject_id: 'person-1', object_id: 'publication-1', predicate: 'person.authored', fact_class: 'business_fact', confidence: 1, review_state: 'approved', evidence_ids: ['evidence-1'], relation_version: 1, projection_version: 'v1' },
  ],
  backend: 'hugegraph', projection_version: 'v1', truncated: false, took_ms: 2,
};

const labels = { person: '学者', publication: '论文', organization: '机构' };
const relationLabel = (edge: GraphEdge) => edge.predicate === 'person.authored' ? '作者' : '所属机构';

function renderGraph() {
  return render(<InteractiveRelationshipGraph
    initialNetwork={initialNetwork} rootName="测试学者" title="学术关系网络" description="逐节点探索"
    filterId="test-network-filter" typeLabels={labels} relationLabel={relationLabel} reviewLabel={() => '已核验'}
  />);
}

beforeEach(() => {
  getKnowledgeNeighborhoodView.mockReset();
  getKnowledgeNeighborhoodView.mockResolvedValue({
    root_object_id: 'publication-1',
    nodes: [
      initialNetwork.nodes[1],
      initialNetwork.nodes[0],
      { object_id: 'organization-1', object_type: 'organization', canonical_name: '测试大学', description: null, object_version: 1, projection_version: 'v1' },
    ],
    edges: [
      { relation_id: 'edge-2', subject_id: 'person-1', object_id: 'organization-1', predicate: 'person.affiliated_with', fact_class: 'business_fact', confidence: 1, review_state: 'approved', evidence_ids: [], relation_version: 1, projection_version: 'v1' },
    ],
    backend: 'hugegraph', projection_version: 'v1', truncated: false, took_ms: 3,
  });
});

describe('InteractiveRelationshipGraph', () => {
  it('expands the selected node by one degree and merges the returned graph', async () => {
    renderGraph();
    fireEvent.click(screen.getByRole('button', { name: /论文 测试论文/ }));
    fireEvent.click(screen.getByRole('button', { name: '展开一度关系' }));
    await waitFor(() => expect(getKnowledgeNeighborhoodView).toHaveBeenCalledWith('publication-1', expect.any(AbortSignal)));
    expect(await screen.findByRole('button', { name: /机构 测试大学/ })).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === 'SMALL' && element.textContent.includes('已展开 2 个节点'))).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重置图谱' }));
    expect(screen.queryByRole('button', { name: /机构 测试大学/ })).not.toBeInTheDocument();
    expect(screen.getByText('2 个对象 · 1 条关系 · 已展开 1 个节点')).toBeInTheDocument();
  });

  it('renders more than 60 nodes without silently clipping the graph', () => {
    const nodes = Array.from({length: 70}, (_, i) => ({...requiredValue(initialNetwork.nodes[1]), object_id: `paper-${i}`, canonical_name: `论文${i}`}));
    const network = {...initialNetwork, nodes: [requiredValue(initialNetwork.nodes[0]), ...nodes], edges: nodes.map((n,i) => ({...requiredValue(initialNetwork.edges[0]), relation_id: `e-${i}`, object_id: n.object_id}))};
    const {container} = render(<InteractiveRelationshipGraph initialNetwork={network} rootName="测试学者" title="图" description="" filterId="large" typeLabels={labels} relationLabel={relationLabel} reviewLabel={() => '已核验'} />);
    expect(container.querySelectorAll('[data-graph-node="true"]')).toHaveLength(71);
    expect(screen.getByText('71 个对象 · 70 条关系 · 已展开 1 个节点')).toBeInTheDocument();
  });

  it('ignores an expansion result arriving after reset', async () => {
    let resolve!: (value: NeighborhoodResult) => void;
    getKnowledgeNeighborhoodView.mockImplementationOnce(() => new Promise(r => {resolve = r;}));
    renderGraph();
    fireEvent.click(screen.getByRole('button', {name: /论文 测试论文/}));
    fireEvent.click(screen.getByRole('button', {name: '展开一度关系'}));
    fireEvent.click(screen.getByRole('button', {name: '重置图谱'}));
    resolve({...initialNetwork, nodes: [...initialNetwork.nodes, {...requiredValue(initialNetwork.nodes[1]), object_id: 'late', canonical_name: '过期节点'}]});
    await waitFor(() => expect(screen.queryByRole('button', {name: /过期节点/})).not.toBeInTheDocument());
    expect(screen.getByText('2 个对象 · 1 条关系 · 已展开 1 个节点')).toBeInTheDocument();
  });

  it('opens a larger graph workspace and closes it with Escape', () => {
    renderGraph();
    fireEvent.click(screen.getByRole('button', { name: '放大图谱区域' }));
    expect(screen.getByRole('dialog', { name: '学术关系网络放大视图' })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '学术关系网络放大视图' })).not.toBeInTheDocument();
  });

  it('keeps the selected display scope and restores its initial graph on reset', async () => {
    Element.prototype.scrollIntoView = vi.fn();
    renderGraph();
    fireEvent.click(screen.getByRole('button', {name: /论文 测试论文/}));
    fireEvent.click(screen.getByRole('button', {name: '展开一度关系'}));
    await screen.findByRole('button', {name: /机构 测试大学/});
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.click(screen.getByRole('option', {name: '论文'}));
    expect(screen.getByText('2 个对象 · 1 条关系 · 已展开 2 个节点')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', {name: '重置图谱'}));
    expect(screen.getByRole('combobox')).toHaveTextContent('论文');
    expect(screen.getByText('2 个对象 · 1 条关系 · 已展开 1 个节点')).toBeInTheDocument();
    expect(screen.queryByRole('button', {name: /机构 测试大学/})).not.toBeInTheDocument();
  });

  it('pans the graph surface when the empty canvas is dragged', () => {
    const { container } = renderGraph();
    const canvas = screen.getByLabelText('可拖拽的交互关系图');
    Object.defineProperty(canvas, 'setPointerCapture', { value: vi.fn() });
    Object.defineProperty(canvas, 'releasePointerCapture', { value: vi.fn() });
    fireEvent.pointerDown(canvas, { pointerId: 1, clientX: 100, clientY: 80 });
    fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 145, clientY: 110 });
    fireEvent.pointerUp(canvas, { pointerId: 1, clientX: 145, clientY: 110 });
    expect(container.querySelector<HTMLElement>('.sg-network-surface')?.style.transform).toBe('translate3d(45px, 30px, 0) scale(1)');
  });

  it('drags a node independently and moves its connected edge', () => {
    const { container } = renderGraph();
    const node = screen.getByRole('button', { name: /论文 测试论文/ });
    Object.defineProperty(node, 'setPointerCapture', { value: vi.fn() });
    Object.defineProperty(node, 'releasePointerCapture', { value: vi.fn() });
    const beforeTransform = node.getAttribute('transform');
    const line = container.querySelector('line');
    const beforeX2 = line?.getAttribute('x2');
    fireEvent.pointerDown(node, { pointerId: 2, clientX: 200, clientY: 150 });
    fireEvent.pointerMove(node, { pointerId: 2, clientX: 260, clientY: 185 });
    fireEvent.pointerUp(node, { pointerId: 2, clientX: 260, clientY: 185 });
    expect(node.getAttribute('transform')).not.toBe(beforeTransform);
    expect(line?.getAttribute('x2')).not.toBe(beforeX2);
  });

  it('allows free node movement and expands the cluster envelope around it', async () => {
    const { container } = renderGraph();
    const node = screen.getByRole('button', { name: /论文 测试论文/ });
    Object.defineProperty(node, 'setPointerCapture', { value: vi.fn() });
    Object.defineProperty(node, 'releasePointerCapture', { value: vi.fn() });
    const envelope = container.querySelector<SVGEllipseElement>('[data-cluster-envelope="true"]');
    const radiusBefore = Number(envelope?.getAttribute('rx'));
    fireEvent.pointerDown(node, { pointerId: 7, clientX: 200, clientY: 150 });
    fireEvent.pointerMove(node, { pointerId: 7, clientX: 1800, clientY: 150 });
    fireEvent.pointerUp(node, { pointerId: 7, clientX: 1800, clientY: 150 });
    await waitFor(() => {
      const x = Number(node.getAttribute('transform')?.match(/translate\(([-\d.]+)/)?.[1]);
      expect(x).toBeGreaterThan(1280);
      expect(Number(envelope?.getAttribute('rx'))).toBeGreaterThan(radiusBefore);
    });
  });

  it('moves a complete cluster without a hidden graph boundary', async () => {
    const { container } = renderGraph();
    const canvas = screen.getByLabelText('可拖拽的交互关系图');
    const handle = screen.getByRole('button', { name: '移动第 1 个关系簇' });
    Object.defineProperty(handle, 'setPointerCapture', { value: vi.fn() });
    Object.defineProperty(handle, 'hasPointerCapture', { value: vi.fn(() => false) });
    const node = screen.getByRole('button', { name: /学者 测试学者/ });
    const xBefore = Number(node.getAttribute('transform')?.match(/translate\(([-\d.]+)/)?.[1]);
    fireEvent.pointerDown(handle, { pointerId: 8, clientX: 200, clientY: 150 });
    fireEvent.pointerMove(canvas, { pointerId: 8, clientX: 1800, clientY: 150 });
    fireEvent.pointerUp(canvas, { pointerId: 8, clientX: 1800, clientY: 150 });
    await waitFor(() => {
      const x = Number(node.getAttribute('transform')?.match(/translate\(([-\d.]+)/)?.[1]);
      expect(x - xBefore).toBeGreaterThan(1500);
      expect(container.querySelector('[data-cluster-handle="true"]')).toBeInTheDocument();
    });
  });

  it('styles node types separately and shows evidence for the current selection', () => {
    renderGraph();
    const publication = screen.getByRole('button', { name: /论文 测试论文/ });
    expect(publication).toHaveClass('type-publication');
    fireEvent.click(publication);
    fireEvent.click(screen.getByRole('button', { name: '查看关系来源' }));
    const drawer = screen.getByRole('dialog', { name: '测试论文的关系来源' });
    expect(drawer).toHaveTextContent('当前选中节点 · 论文');
    expect(drawer).toHaveTextContent('测试学者 作者 测试论文');
    expect(drawer).toHaveTextContent('evidence-1');
  });

  it('removes a selected node only from the current view and restores it', async () => {
    renderGraph();
    fireEvent.click(screen.getByRole('button', { name: /论文 测试论文/ }));
    fireEvent.click(screen.getByRole('button', { name: '从当前图中移除' }));
    expect(screen.getByText(/PostgreSQL、HugeGraph 和其他业务数据不会被删除/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '从当前视图移除' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: /论文 测试论文/ })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: '恢复已移除节点（1）' }));
    expect(screen.getByRole('button', { name: /论文 测试论文/ })).toBeInTheDocument();
  });
});
