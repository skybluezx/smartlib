import {
  useCallback, useEffect, useMemo, useRef, useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';
import {
  AddAlt, CheckmarkFilled, Maximize, Minimize, Reset, TrashCan, Undo, ZoomIn, ZoomOut,
} from '@carbon/icons-react';
import { Button, Dropdown, InlineLoading, InlineNotification, Modal } from '@carbon/react';
import type { GraphEdge, GraphNode, NeighborhoodResult } from '../../generated/smartlib-api';
import { getKnowledgeNeighborhoodView } from '../../shared/api/smartlib';
import { clusteredGraphLayout, clusterEnvelopes } from './clusteredGraphLayout';
import { clientToGraph, type GraphPointer } from './graphInteraction';

interface InteractiveRelationshipGraphProps {
  initialNetwork: NeighborhoodResult;
  rootName: string;
  title: string;
  description: string;
  sectionClassName?: string;
  filterId: string;
  typeLabels: Partial<Record<string, string>>;
  relationLabel: (edge: GraphEdge) => string;
  reviewLabel: (value: string) => string;
}

interface Point { x: number; y: number; cluster: number; role: 'core' | 'peripheral' }
interface ViewState { x: number; y: number; zoom: number }

const VIEWBOX_WIDTH = 1280;
const VIEWBOX_HEIGHT = 780;

export function InteractiveRelationshipGraph({
  initialNetwork, rootName, title, description, sectionClassName = '', filterId,
  typeLabels, relationLabel, reviewLabel,
}: InteractiveRelationshipGraphProps) {
  const [network, setNetwork] = useState(initialNetwork);
  const [type, setType] = useState('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [expandedView, setExpandedView] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set([initialNetwork.root_object_id]));
  const [expandingId, setExpandingId] = useState<string | null>(null);
  const [expandError, setExpandError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [positionOverrides, setPositionOverrides] = useState<Map<string, Point>>(() => new Map());
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(() => new Set());
  const [deleteCandidate, setDeleteCandidate] = useState<GraphNode | null>(null);
  const [relationEvidenceOpen, setRelationEvidenceOpen] = useState(false);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const viewRef = useRef<ViewState>({ x: 0, y: 0, zoom: 1 });
  const dragRef = useRef<{ pointerId: number; x: number; y: number; originX: number; originY: number } | null>(null);
  const nodeDragRef = useRef<{ pointerId: number; objectId: string; start: GraphPointer; origin: Point } | null>(null);
  const clusterDragRef = useRef<{ pointerId: number; cluster: number; start: GraphPointer; origins: Map<string, Point>; element: SVGGraphicsElement } | null>(null);
  const nodePositionsRef = useRef<Map<string, Point>>(new Map());
  const expansionControllerRef = useRef<AbortController | null>(null);

  const applyView = useCallback(() => {
    const view = viewRef.current;
    if (surfaceRef.current) {
      surfaceRef.current.style.transform = `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.zoom})`;
    }
  }, []);

  useEffect(() => () => expansionControllerRef.current?.abort(), []);

  useEffect(() => {
    if (!expandedView) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setExpandedView(false); };
    document.addEventListener('keydown', close);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', close);
    };
  }, [expandedView]);

  const visibleNodes = useMemo(() => network.nodes
    .filter((node) => !hiddenIds.has(node.object_id))
    .filter((node) => node.object_id === network.root_object_id || type === 'all' || node.object_type === type), [hiddenIds, network.nodes, network.root_object_id, type]);
  const visibleIds = useMemo(() => new Set(visibleNodes.map((node) => node.object_id)), [visibleNodes]);
  const visibleEdges = useMemo(() => network.edges.filter((edge) => visibleIds.has(edge.subject_id) && visibleIds.has(edge.object_id)), [network.edges, visibleIds]);
  const autoPositions = useMemo(() => clusteredGraphLayout(
      visibleNodes.map((node) => ({ id: node.object_id, label: node.canonical_name })),
      visibleEdges.map((edge) => ({ source: edge.subject_id, target: edge.object_id, weight: edge.confidence ?? 1 })),
      { width: VIEWBOX_WIDTH, height: VIEWBOX_HEIGHT, padding: 32, clusterGap: 32, expandable: true, spacious: true },
    ), [visibleEdges, visibleNodes]);
  const positions = useMemo(() => {
    const result = new Map<string, Point>(autoPositions);
    positionOverrides.forEach((point, objectId) => { if (result.has(objectId)) result.set(objectId, point); });
    return result;
  }, [positionOverrides, autoPositions]);
  const root = network.nodes.find((node) => node.object_id === network.root_object_id) ?? network.nodes[0];
  const selected = network.nodes.find((node) => node.object_id === selectedId) ?? root;
  const selectedEdges = network.edges.filter((edge) => edge.subject_id === selected?.object_id || edge.object_id === selected?.object_id);
  const types = Array.from(new Set(network.nodes.filter((node) => node.object_id !== network.root_object_id).map((node) => node.object_type)));
  const typeItems = [{ id: 'all', label: '全部关系' }, ...types.map((value) => ({ id: value, label: typeLabels[value] ?? value }))];

  useEffect(() => { nodePositionsRef.current = new Map(positions); }, [positions]);

  const updateZoom = (next: number) => {
    const normalized = Math.min(4, Math.max(.2, Number(next.toFixed(2))));
    viewRef.current.zoom = normalized;
    setZoom(normalized);
    applyView();
  };

  const resetView = () => {
    expansionControllerRef.current?.abort();
    setNetwork(initialNetwork);
    setExpandedIds(new Set([initialNetwork.root_object_id]));
    setHiddenIds(new Set());
    setSelectedId(null);
    setExpandingId(null);
    setExpandError(null);
    setDeleteCandidate(null);
    setRelationEvidenceOpen(false);
    dragRef.current = null;
    nodeDragRef.current = null;
    clusterDragRef.current = null;
    setDragging(false);
    setDraggingNodeId(null);
    viewRef.current = { x: 0, y: 0, zoom: 1 };
    setZoom(1);
    setPositionOverrides(new Map());
    applyView();
  };

  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const clusterElement = (event.target as Element).closest<SVGGraphicsElement>('[data-cluster-envelope="true"], [data-cluster-handle="true"]');
    if (clusterElement) {
      const cluster = Number(clusterElement.dataset.clusterId);
      const start = clientToGraph(svgRef.current, event.clientX, event.clientY);
      if (!Number.isFinite(cluster) || !start) return;
      event.preventDefault(); event.stopPropagation();
      const origins = new Map(Array.from(nodePositionsRef.current.entries()).filter(([, point]) => point.cluster === cluster));
      clusterElement.setPointerCapture(event.pointerId);
      clusterDragRef.current = { pointerId: event.pointerId, cluster, start, origins, element: clusterElement };
      return;
    }
    if ((event.target as Element).closest('[data-graph-node="true"]')) return;
    dragRef.current = {
      pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      originX: viewRef.current.x, originY: viewRef.current.y,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (drag?.pointerId !== event.pointerId) return;
    viewRef.current.x = drag.originX + event.clientX - drag.x;
    viewRef.current.y = drag.originY + event.clientY - drag.y;
    applyView();
  };

  const endDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    dragRef.current = null;
    setDragging(false);
  };

  const startNodeDrag = (event: ReactPointerEvent<SVGGElement>, objectId: string) => {
    const origin = nodePositionsRef.current.get(objectId);
    const start = clientToGraph(svgRef.current, event.clientX, event.clientY);
    if (!origin || !start) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedId(objectId);
    nodeDragRef.current = { pointerId: event.pointerId, objectId, start, origin };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDraggingNodeId(objectId);
  };

  const moveNode = (event: ReactPointerEvent) => {
    const drag = nodeDragRef.current;
    if (drag?.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const current = clientToGraph(svgRef.current, event.clientX, event.clientY);
    if (!current) return;
    const point = {
      ...drag.origin,
      x: drag.origin.x + current.x - drag.start.x,
      y: drag.origin.y + current.y - drag.start.y,
    };
    nodePositionsRef.current.set(drag.objectId, point);
    setPositionOverrides((currentOverrides) => new Map(currentOverrides).set(drag.objectId, point));
  };

  const endNodeDrag = (event: ReactPointerEvent) => {
    const drag = nodeDragRef.current;
    if (drag?.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const nodeElement = event.currentTarget;
    if ('hasPointerCapture' in nodeElement && typeof nodeElement.hasPointerCapture === 'function' && nodeElement.hasPointerCapture(event.pointerId)) nodeElement.releasePointerCapture(event.pointerId);
    nodeDragRef.current = null;
    setDraggingNodeId(null);
  };

  const moveCluster = (event: ReactPointerEvent) => {
    const drag = clusterDragRef.current;
    if (drag?.pointerId !== event.pointerId) return;
    event.stopPropagation();
    const current = clientToGraph(svgRef.current, event.clientX, event.clientY);
    if (!current) return;
    const delta = { x: current.x - drag.start.x, y: current.y - drag.start.y };
    setPositionOverrides((overrides) => {
      const next = new Map(overrides);
      drag.origins.forEach((point, objectId) => next.set(objectId, { ...point, x: point.x + delta.x, y: point.y + delta.y }));
      return next;
    });
  };

  const endClusterDrag = (event: ReactPointerEvent) => {
    const drag = clusterDragRef.current;
    if (drag?.pointerId !== event.pointerId) return;
    event.stopPropagation();
    if (drag.element.hasPointerCapture(event.pointerId)) drag.element.releasePointerCapture(event.pointerId);
    clusterDragRef.current = null;
  };

  const removeSelectedNode = () => {
    if (!deleteCandidate || deleteCandidate.object_id === network.root_object_id) return;
    setHiddenIds((current) => new Set(current).add(deleteCandidate.object_id));
    setPositionOverrides((current) => { const next = new Map(current); next.delete(deleteCandidate.object_id); return next; });
    setSelectedId(network.root_object_id);
    setDeleteCandidate(null);
    setRelationEvidenceOpen(false);
  };

  const expandNode = async (objectId: string) => {
    if (expandedIds.has(objectId) || expandingId) return;
    setSelectedId(objectId);
    setExpandError(null);
    setExpandingId(objectId);
    expansionControllerRef.current?.abort();
    const controller = new AbortController();
    expansionControllerRef.current = controller;
    try {
      const result = await getKnowledgeNeighborhoodView(objectId, controller.signal);
      if (controller.signal.aborted) return;
      setNetwork((current) => mergeNetworks(current, result));
      setExpandedIds((current) => new Set(current).add(objectId));
    } catch (error) {
      if (!controller.signal.aborted) setExpandError(error instanceof Error ? error.message : '节点关系展开失败');
    } finally {
      if (!controller.signal.aborted) setExpandingId(null);
    }
  };

  const shownNodeCount = visibleNodes.length;
  const clipped = network.nodes.length > shownNodeCount;
  const legendTypes = Array.from(new Set(visibleNodes.map((node) => node.object_type)));
  const envelopes = clusterEnvelopes(positions);
  const fittedEnvelopes = clusterEnvelopes(autoPositions);
  const layoutBounds = {
    x: fittedEnvelopes.length ? Math.min(...fittedEnvelopes.map(e => e.cx-e.rx-24)) : 0,
    y: fittedEnvelopes.length ? Math.min(...fittedEnvelopes.map(e => e.cy-e.ry-24)) : 0,
    right: fittedEnvelopes.length ? Math.max(...fittedEnvelopes.map(e => e.cx+e.rx+24)) : VIEWBOX_WIDTH,
    bottom: fittedEnvelopes.length ? Math.max(...fittedEnvelopes.map(e => e.cy+e.ry+24)) : VIEWBOX_HEIGHT,
  };
  const sectionClasses = `${sectionClassName} sg-interactive-network ${expandedView ? 'sg-network-expanded' : ''}`.trim();
  const fittedWidth = Math.max(640, layoutBounds.right-layoutBounds.x);
  const fittedHeight = Math.max(390, layoutBounds.bottom-layoutBounds.y);
  return <>
  <section className={sectionClasses} role={expandedView ? 'dialog' : undefined} aria-modal={expandedView || undefined} aria-label={expandedView ? `${title}放大视图` : undefined}>
    <header className="sg-section-heading">
      <div><h2>{title}</h2><p>{description}</p></div>
      <div className="sg-network-status"><CheckmarkFilled /><span>关系图已加载<small>{visibleNodes.length} 个对象 · {visibleEdges.length} 条关系 · 已展开 {[...expandedIds].filter((id) => visibleIds.has(id)).length} 个节点{network.truncated ? ' · 当前关系未完整加载，请重试' : ''}</small></span></div>
    </header>
    <div className="sg-network-toolbar">
      <Dropdown id={filterId} label="关系范围" titleText="显示范围" items={typeItems} itemToString={(item) => item?.label ?? ''} selectedItem={typeItems.find((item) => item.id === type) ?? typeItems[0]} onChange={({ selectedItem: item }) => { setType(item?.id ?? 'all'); setSelectedId(null); }} />
      <div className="sg-network-view-actions">
        <Button kind="ghost" hasIconOnly renderIcon={ZoomOut} iconDescription="缩小图谱" disabled={zoom <= .2} onClick={() => updateZoom(zoom - .1)} />
        <span aria-label={`当前缩放 ${Math.round(zoom * 100)}%`}>{Math.round(zoom * 100)}%</span>
        <Button kind="ghost" hasIconOnly renderIcon={ZoomIn} iconDescription="放大图谱内容" disabled={zoom >= 4} onClick={() => updateZoom(zoom + .1)} />
        <Button kind="ghost" hasIconOnly renderIcon={Reset} iconDescription="重置图谱" onClick={resetView} />
        {hiddenIds.size > 0 && <Button kind="ghost" size="sm" renderIcon={Undo} onClick={() => setHiddenIds(new Set())}>恢复已移除节点（{hiddenIds.size}）</Button>}
        <Button kind="ghost" size="sm" renderIcon={expandedView ? Minimize : Maximize} onClick={() => setExpandedView((value) => !value)}>{expandedView ? '退出放大' : '放大图谱区域'}</Button>
      </div>
    </div>
    <div className="sg-network-help"><span>拖拽空白区域移动画布</span><span>节点可自由调整，包围圈随之变化</span><span>拖拽虚线区域或移动把手移动整个簇</span><span>重置恢复当前显示范围的初始节点、关系和布局</span><span>双击节点展开全部一度关系；已展开数包含中心节点</span></div>
    <div className="sg-network-legend" aria-label="节点类型图例">{legendTypes.map((value) => <span key={value} className={`type-${value}`}><i />{typeLabels[value] ?? value}</span>)}</div>
    {expandError && <InlineNotification lowContrast kind="error" title="节点展开失败" subtitle={expandError} hideCloseButton={false} onCloseButtonClick={() => setExpandError(null)} />}
    <div className="sg-network-workspace">
      <div
        className={`sg-network-canvas ${dragging ? 'is-dragging' : ''}`}
        aria-label="可拖拽的交互关系图"
        onPointerDown={startDrag}
        onPointerMove={(event) => { moveNode(event); moveCluster(event); moveDrag(event); }}
        onPointerUp={(event) => { endNodeDrag(event); endClusterDrag(event); endDrag(event); }}
        onPointerCancel={(event) => { endNodeDrag(event); endClusterDrag(event); endDrag(event); }}
        onDoubleClick={(event) => { if (!(event.target as Element).closest('[data-graph-node="true"], [data-cluster-envelope="true"]')) setExpandedView(true); }}
      >
        <div ref={surfaceRef} className="sg-network-surface">
          <svg ref={svgRef} viewBox={`${(layoutBounds.x+layoutBounds.right-fittedWidth)/2} ${(layoutBounds.y+layoutBounds.bottom-fittedHeight)/2} ${fittedWidth} ${fittedHeight}`} role="img" aria-label={`${rootName}的关系网络`}>
            {envelopes.map((envelope) => <ellipse key={envelope.cluster} data-cluster-envelope="true" data-cluster-id={envelope.cluster} className="sg-cluster-envelope" cx={envelope.cx} cy={envelope.cy} rx={envelope.rx} ry={envelope.ry} />)}
            {visibleEdges.map((edge) => {
              const a = positions.get(edge.subject_id); const b = positions.get(edge.object_id);
              const active = edge.subject_id === selected?.object_id || edge.object_id === selected?.object_id;
              return a && b ? <line key={edge.relation_id} className={`${a.cluster === b.cluster ? 'intra-cluster' : 'inter-cluster'} ${active ? 'active' : ''}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} /> : null;
            })}
            {envelopes.map((envelope) => <g key={`handle-${envelope.cluster}`} data-cluster-handle="true" data-cluster-id={envelope.cluster} className="sg-cluster-drag-handle" transform={`translate(${envelope.cx - envelope.rx} ${envelope.cy})`} role="button" aria-label={`移动第 ${envelope.cluster + 1} 个关系簇`}><title>拖动整个关系簇</title><circle r="10" /><path d="M-6 0H6M0-6V6M-6 0l2-2M-6 0l2 2M6 0L4-2M6 0L4 2M0-6l-2 2M0-6l2 2M0 6l-2-2M0 6l2-2" /></g>)}
            {visibleNodes.map((node) => {
              const point = positions.get(node.object_id); if (!point) return null;
              const isRoot = node.object_id === network.root_object_id;
              const isExpanded = expandedIds.has(node.object_id);
              return <g key={node.object_id} transform={`translate(${point.x} ${point.y})`} data-graph-node="true" className={`type-${node.object_type} role-${point.role} cluster-${point.cluster} ${isRoot ? 'root' : ''} ${node.object_id === selected?.object_id ? 'selected' : ''} ${isExpanded ? 'expanded' : ''} ${draggingNodeId === node.object_id ? 'is-node-dragging' : ''}`} tabIndex={0} role="button" aria-label={`${typeLabels[node.object_type] ?? node.object_type} ${node.canonical_name}${isExpanded ? '，已展开' : '，可展开'}`} onPointerDown={(event) => startNodeDrag(event, node.object_id)} onPointerMove={moveNode} onPointerUp={endNodeDrag} onPointerCancel={endNodeDrag} onClick={() => setSelectedId(node.object_id)} onDoubleClick={(event) => { event.stopPropagation(); void expandNode(node.object_id); }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(node.object_id); } }}>
                <circle cx={0} cy={0} r={isRoot ? 48 : point.role === 'core' ? 40 : 34} />
                {isExpanded && !isRoot && <circle className="expanded-marker" cx={27} cy={-27} r={6} />}
                <text x={0} y={-3}>{truncate(node.canonical_name, 12)}</text>
                <text className="type" x={0} y={16}>{typeLabels[node.object_type] ?? node.object_type}</text>
              </g>;
            })}
          </svg>
        </div>
        {clipped && <div className="sg-network-limit-note">当前显示 {shownNodeCount} / {network.nodes.length} 个对象，可按类型缩小范围。</div>}
      </div>
      <aside className="sg-node-detail">
        <span>{typeLabels[selected?.object_type ?? ''] ?? selected?.object_type}</span>
        <h3>{selected?.canonical_name}</h3>
        <p>{selected?.description ?? '该对象尚未提供摘要。'}</p>
        <dl><div><dt>当前相关关系</dt><dd>{selectedEdges.length} 条</dd></div><div><dt>关系依据</dt><dd>{selectedEdges.reduce((total, edge) => total + edge.evidence_ids.length, 0)} 条</dd></div><div><dt>展开状态</dt><dd>{selected && expandedIds.has(selected.object_id) ? '已读取一度关系' : '尚未展开'}</dd></div></dl>
        {selected && <Button kind="primary" size="sm" renderIcon={AddAlt} disabled={expandedIds.has(selected.object_id) || expandingId !== null} onClick={() => void expandNode(selected.object_id)}>{expandingId === selected.object_id ? '正在展开' : expandedIds.has(selected.object_id) ? '已展开一度关系' : '展开一度关系'}</Button>}
        {expandingId === selected?.object_id && <InlineLoading description="正在读取相邻对象" />}
        {selected && <Button kind="tertiary" size="sm" onClick={() => setRelationEvidenceOpen(true)}>查看关系来源</Button>}
        {selected && <Button kind="danger--tertiary" size="sm" renderIcon={TrashCan} disabled={selected.object_id === network.root_object_id} onClick={() => setDeleteCandidate(selected)}>从当前图中移除</Button>}
        <small className="sg-node-remove-note">移除仅影响当前图谱视图，不删除系统数据。</small>
      </aside>
    </div>
    <div className="sg-relation-ledger"><h3>关系说明</h3>{visibleEdges.slice(0, 80).map((edge) => <div key={edge.relation_id}><span>{nodeName(network.nodes, edge.subject_id)}</span><strong>{relationLabel(edge)}</strong><span>{nodeName(network.nodes, edge.object_id)}</span><small>{edge.evidence_ids.length} 条依据</small></div>)}</div>
  </section>
  {relationEvidenceOpen && selected && <RelationEvidenceDrawer selected={selected} edges={selectedEdges} nodes={network.nodes} typeLabels={typeLabels} relationLabel={relationLabel} reviewLabel={reviewLabel} onClose={() => setRelationEvidenceOpen(false)} />}
  <Modal open={Boolean(deleteCandidate)} danger modalHeading="从当前图谱移除节点" primaryButtonText="从当前视图移除" secondaryButtonText="取消" onRequestClose={() => setDeleteCandidate(null)} onRequestSubmit={removeSelectedNode}>
    <p>将“{deleteCandidate?.canonical_name}”及其当前可见连线从本次图谱视图中隐藏。PostgreSQL、HugeGraph 和其他业务数据不会被删除，可随时使用“恢复已移除节点”重新显示。</p>
  </Modal>
  </>;
}

function RelationEvidenceDrawer({ selected, edges, nodes, typeLabels, relationLabel, onClose }: { selected: GraphNode; edges: GraphEdge[]; nodes: GraphNode[]; typeLabels: Partial<Record<string, string>>; relationLabel: (edge: GraphEdge) => string; reviewLabel: (value: string) => string; onClose: () => void }) {
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [onClose]);
  const evidenceCount = edges.reduce((total, edge) => total + edge.evidence_ids.length, 0);
  return <div className="sg-evidence-layer" role="dialog" aria-modal="true" aria-labelledby="relation-evidence-title">
    <button className="sg-evidence-scrim" aria-label="关闭关系来源" onClick={onClose} />
    <aside className="sg-evidence-drawer sg-relation-evidence-drawer">
      <header><div><span>当前选中节点 · {typeLabels[selected.object_type] ?? selected.object_type}</span><h2 id="relation-evidence-title">{selected.canonical_name}的关系来源</h2></div><Button kind="ghost" onClick={onClose}>关闭</Button></header>
      <div className="sg-evidence-summary"><strong>{edges.length}</strong><span>条直接关系</span><code>{evidenceCount} 条证据标识</code></div>
      {edges.length === 0 ? <div className="sg-relation-evidence-empty">该节点在当前图谱中没有直接关系来源。</div> : <div className="sg-evidence-list">{edges.map((edge) => {
        const attributes = evidenceAttributes(edge.attributes);
        return <article key={edge.relation_id}>
          <div><span>置信度 {edge.confidence === null ? '未标注' : `${Math.round(edge.confidence * 100)}%`}</span></div>
          <h3>{nodeName(nodes, edge.subject_id)} <strong>{relationLabel(edge)}</strong> {nodeName(nodes, edge.object_id)}</h3>
          <p>这条记录是当前选中节点与相邻对象之间的直接关系。</p>
          <dl><div><dt>关系编号</dt><dd><code>{edge.relation_id}</code></dd></div><div><dt>事实类型</dt><dd>{edge.fact_class}</dd></div>{attributes.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
          <details><summary>{edge.evidence_ids.length} 条证据标识</summary>{edge.evidence_ids.length ? <div className="sg-relation-evidence-ids">{edge.evidence_ids.map((id) => <code key={id}>{id}</code>)}</div> : <p>这条关系暂未关联独立证据标识。</p>}</details>
        </article>;
      })}</div>}
      <footer><Button onClick={onClose}>完成查看</Button></footer>
    </aside>
  </div>;
}

function evidenceAttributes(attributes?: Record<string, unknown>): [string, string][] {
  if (!attributes) return [];
  const labels: Record<string, string> = { source: '来源', mapping_method: '匹配方式', raw_affiliation: '原始机构文本', publication_id: '论文编号', rule_version: '规则版本' };
  return Object.entries(labels).flatMap(([key, label]) => {
    const value = attributes[key];
    return value === undefined || value === null || value === '' ? [] : [[label, typeof value === 'string' ? value : JSON.stringify(value)] as [string, string]];
  });
}


function mergeNetworks(current: NeighborhoodResult, incoming: NeighborhoodResult): NeighborhoodResult {
  const nodes = new Map(current.nodes.map((node) => [node.object_id, node]));
  const edges = new Map(current.edges.map((edge) => [edge.relation_id, edge]));
  incoming.nodes.forEach((node) => nodes.set(node.object_id, node));
  incoming.edges.forEach((edge) => edges.set(edge.relation_id, edge));
  return {
    ...current,
    nodes: Array.from(nodes.values()), edges: Array.from(edges.values()),
    truncated: current.truncated || incoming.truncated,
    took_ms: current.took_ms + incoming.took_ms,
  };
}

function truncate(value: string, length: number) { return value.length > length ? `${value.slice(0, length)}…` : value; }
function nodeName(nodes: GraphNode[], id: string) { return nodes.find((node) => node.object_id === id)?.canonical_name ?? '受限对象'; }
