export interface ClusterLayoutNode {
  id: string;
  label?: string;
  communityId?: number | null;
}

export interface ClusterLayoutEdge {
  source: string;
  target: string;
  weight?: number;
}

export interface ClusterLayoutPoint {
  x: number;
  y: number;
  cluster: number;
  role: 'core' | 'peripheral';
}

export interface ClusterEnvelope {
  cluster: number;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
}

interface LayoutOptions {
  width: number;
  height: number;
  padding?: number;
  clusterGap?: number;
  expandable?: boolean;
  spacious?: boolean;
}

interface Community {
  id: string;
  nodes: ClusterLayoutNode[];
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

export function clusteredGraphLayout(nodes: ClusterLayoutNode[], edges: ClusterLayoutEdge[], options: LayoutOptions): Map<string, ClusterLayoutPoint> {
  const padding = options.padding ?? 60;
  if (nodes.length === 0) return new Map();
  const nodeIds = new Set(nodes.map((node) => node.id));
  const validEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target) && edge.source !== edge.target);
  const adjacency = buildAdjacency(nodes, validEdges);
  const degree = weightedDegree(nodes, adjacency);
  const authoritative = nodes.every((node) => node.communityId != null);
  const groups = new Map<number, ClusterLayoutNode[]>();
  if (authoritative) nodes.forEach((node) => groups.set(node.communityId ?? -1, [...(groups.get(node.communityId ?? -1) ?? []), node]));
  const communities = authoritative
    ? [...groups].sort(([a], [b]) => a - b).map(([id, members]) => ({ id: String(id), nodes: members }))
    : detectCommunities(nodes, validEdges, adjacency, degree)
      .sort((left, right) => right.nodes.length - left.nodes.length || left.id.localeCompare(right.id));
  const centers = communityCenters(communities.length, options.width, options.height, padding);
  const result = new Map<string, ClusterLayoutPoint>();

  communities.forEach((community, clusterIndex) => {
    const clusterId = authoritative ? Number(community.id) : clusterIndex;
    const center = centers[clusterIndex] ?? { x: options.width / 2, y: options.height / 2 };
    const ordered = [...community.nodes].sort((left, right) => (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0) || (left.label ?? left.id).localeCompare(right.label ?? right.id, 'zh-CN'));
    const coreCount = ordered.length <= 3 ? 1 : Math.min(5, Math.max(2, Math.ceil(Math.sqrt(ordered.length) / 2)));
    const coreNodes = ordered.slice(0, coreCount);
    const peripheralNodes = ordered.slice(coreCount);
    const isSingleCluster = communities.length === 1;
    const radiusX = isSingleCluster
      ? Math.min(options.width * .4, Math.max(130, Math.sqrt(ordered.length) * 48))
      : Math.min(options.width * .19, Math.max(82, 48 + Math.sqrt(ordered.length) * 27));
    const radiusY = isSingleCluster
      ? Math.min(options.height * .38, Math.max(95, Math.sqrt(ordered.length) * 32))
      : Math.min(options.height * .2, Math.max(65, 40 + Math.sqrt(ordered.length) * 20));

    coreNodes.forEach((node, index) => {
      const angle = index / Math.max(1, coreNodes.length) * Math.PI * 2 - Math.PI / 2;
      const coreRadius = coreNodes.length === 1 ? 0 : Math.min(34, 12 + coreNodes.length * 4);
      result.set(node.id, { x: center.x + Math.cos(angle) * coreRadius, y: center.y + Math.sin(angle) * coreRadius * .72, cluster: clusterId, role: 'core' });
    });

    if (peripheralNodes.length === 0) return;
    const ringCount = Math.max(1, Math.ceil(peripheralNodes.length / 14));
    const ringGroups = Array.from({ length: ringCount }, () => [] as ClusterLayoutNode[]);
    peripheralNodes.forEach((node, index) => ringGroups[Math.min(ringCount - 1, Math.floor(index / 14))]?.push(node));
    ringGroups.forEach((ringNodes, ringIndex) => {
      const fraction = ringCount === 1 ? 1 : .46 + ringIndex / (ringCount - 1) * .54;
      ringNodes.forEach((node, index) => {
        const coreAffinity = strongestCoreIndex(node.id, coreNodes, adjacency);
        const sectorOffset = coreNodes.length > 1 ? coreAffinity / coreNodes.length * Math.PI * 2 : 0;
        const angle = index / Math.max(1, ringNodes.length) * Math.PI * 2 - Math.PI / 2 + sectorOffset + ringIndex * GOLDEN_ANGLE * .18;
        result.set(node.id, { x: center.x + Math.cos(angle) * radiusX * fraction, y: center.y + Math.sin(angle) * radiusY * fraction, cluster: clusterId, role: 'peripheral' });
      });
    });
  });

  if (options.spacious) spaceClusterNodes(result);
  else separateCloseNodes(result, nodes, options.width, options.height, padding);
  if (options.expandable) packClusters(result, options.width / options.height, padding, options.clusterGap ?? 72);
  else separateClusters(result, options.width, options.height, padding, options.clusterGap ?? 72);
  return result;
}

export function clusterEnvelopes(points: Map<string, ClusterLayoutPoint>): ClusterEnvelope[] {
  const groups = new Map<number, ClusterLayoutPoint[]>();
  points.forEach((point) => groups.set(point.cluster, [...(groups.get(point.cluster) ?? []), point]));
  return Array.from(groups.entries()).map(([cluster, clusterPoints]) => envelopeForPoints(cluster, clusterPoints));
}

function envelopeForPoints(cluster: number, clusterPoints: ClusterLayoutPoint[]): ClusterEnvelope {
  const xs = clusterPoints.map((point) => point.x); const ys = clusterPoints.map((point) => point.y);
  const minimumX = Math.min(...xs); const maximumX = Math.max(...xs);
  const minimumY = Math.min(...ys); const maximumY = Math.max(...ys);
  const cx = (minimumX + maximumX) / 2; const cy = (minimumY + maximumY) / 2;
  let rx = Math.max(62, (maximumX - minimumX) / 2 + 50);
  let ry = Math.max(56, (maximumY - minimumY) / 2 + 50);
  const nodeClearance = 46;
  const samples = clusterPoints.flatMap((point) => [
    { x: point.x - nodeClearance, y: point.y }, { x: point.x + nodeClearance, y: point.y },
    { x: point.x, y: point.y - nodeClearance }, { x: point.x, y: point.y + nodeClearance },
    { x: point.x - 32, y: point.y - 32 }, { x: point.x + 32, y: point.y - 32 },
    { x: point.x - 32, y: point.y + 32 }, { x: point.x + 32, y: point.y + 32 },
  ]);
  const maximumNormalizedDistance = samples.reduce((maximum, point) => Math.max(maximum, Math.sqrt(((point.x - cx) / rx) ** 2 + ((point.y - cy) / ry) ** 2)), 1);
  if (maximumNormalizedDistance > 1) {
    rx *= maximumNormalizedDistance * 1.02;
    ry *= maximumNormalizedDistance * 1.02;
  }
  return { cluster, cx, cy, rx, ry };
}

function buildAdjacency(nodes: ClusterLayoutNode[], edges: ClusterLayoutEdge[]) {
  const adjacency = new Map(nodes.map((node) => [node.id, new Map<string, number>()]));
  edges.forEach((edge) => {
    const weight = Math.max(.25, Math.sqrt(edge.weight ?? 1));
    adjacency.get(edge.source)?.set(edge.target, (adjacency.get(edge.source)?.get(edge.target) ?? 0) + weight);
    adjacency.get(edge.target)?.set(edge.source, (adjacency.get(edge.target)?.get(edge.source) ?? 0) + weight);
  });
  return adjacency;
}

function weightedDegree(nodes: ClusterLayoutNode[], adjacency: Map<string, Map<string, number>>) {
  return new Map(nodes.map((node) => [node.id, Array.from(adjacency.get(node.id)?.values() ?? []).reduce((total, weight) => total + weight, 0)]));
}

function detectCommunities(nodes: ClusterLayoutNode[], edges: ClusterLayoutEdge[], adjacency: Map<string, Map<string, number>>, degree: Map<string, number>): Community[] {
  if (edges.length === 0) return nodes.map((node) => ({ id: node.id, nodes: [node] }));
  const labels = new Map(nodes.map((node) => [node.id, node.id]));
  const totals = new Map(nodes.map((node) => [node.id, degree.get(node.id) ?? 0]));
  const totalWeight = Math.max(1, Array.from(degree.values()).reduce((total, value) => total + value, 0));
  const order = [...nodes].sort((left, right) => (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0) || left.id.localeCompare(right.id));

  for (let pass = 0; pass < 18; pass += 1) {
    let moved = false;
    for (const node of order) {
      const current = labels.get(node.id) ?? node.id;
      const nodeDegree = degree.get(node.id) ?? 0;
      totals.set(current, (totals.get(current) ?? 0) - nodeDegree);
      const weightsByCommunity = new Map<string, number>();
      adjacency.get(node.id)?.forEach((weight, neighborId) => {
        const community = labels.get(neighborId) ?? neighborId;
        weightsByCommunity.set(community, (weightsByCommunity.get(community) ?? 0) + weight);
      });
      weightsByCommunity.set(current, weightsByCommunity.get(current) ?? 0);
      let best = current;
      let bestScore = Number.NEGATIVE_INFINITY;
      Array.from(weightsByCommunity.entries()).sort(([left], [right]) => left.localeCompare(right)).forEach(([candidate, internalWeight]) => {
        const score = internalWeight - nodeDegree * (totals.get(candidate) ?? 0) / totalWeight * 1.08;
        if (score > bestScore + 1e-8) { best = candidate; bestScore = score; }
      });
      labels.set(node.id, best);
      totals.set(best, (totals.get(best) ?? 0) + nodeDegree);
      if (best !== current) moved = true;
    }
    if (!moved) break;
  }

  const grouped = new Map<string, ClusterLayoutNode[]>();
  nodes.forEach((node) => {
    const label = labels.get(node.id) ?? node.id;
    grouped.set(label, [...(grouped.get(label) ?? []), node]);
  });
  return Array.from(grouped.entries()).map(([id, communityNodes]) => ({ id, nodes: communityNodes }));
}

function communityCenters(count: number, width: number, height: number, padding: number) {
  const center = { x: width / 2, y: height / 2 };
  if (count === 1) return [center];
  if (count === 2) return [{ x: width * .3, y: center.y }, { x: width * .7, y: center.y }];
  if (count === 3) return [{ x: center.x, y: height * .3 }, { x: width * .3, y: height * .7 }, { x: width * .7, y: height * .7 }];
  if (count === 4) return [{ x: width * .3, y: height * .3 }, { x: width * .7, y: height * .3 }, { x: width * .3, y: height * .7 }, { x: width * .7, y: height * .7 }];
  const radiusX = Math.max(1, width / 2 - padding - 120);
  const radiusY = Math.max(1, height / 2 - padding - 90);
  return Array.from({ length: count }, (_, index) => {
    const angle = index / count * Math.PI * 2 - Math.PI / 2;
    return { x: center.x + Math.cos(angle) * radiusX, y: center.y + Math.sin(angle) * radiusY };
  });
}

function strongestCoreIndex(nodeId: string, coreNodes: ClusterLayoutNode[], adjacency: Map<string, Map<string, number>>) {
  let bestIndex = 0;
  let bestWeight = -1;
  coreNodes.forEach((core, index) => {
    const weight = adjacency.get(nodeId)?.get(core.id) ?? 0;
    if (weight > bestWeight) { bestIndex = index; bestWeight = weight; }
  });
  return bestIndex;
}

function separateCloseNodes(points: Map<string, ClusterLayoutPoint>, nodes: ClusterLayoutNode[], width: number, height: number, padding: number) {
  for (let pass = 0; pass < 36; pass += 1) {
    for (let leftIndex = 0; leftIndex < nodes.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < nodes.length; rightIndex += 1) {
        const left = points.get(nodes[leftIndex]?.id ?? '');
        const right = points.get(nodes[rightIndex]?.id ?? '');
        if (!left || !right) continue;
        if (left.cluster !== right.cluster) continue;
        const dx = right.x - left.x || .01;
        const dy = right.y - left.y || .01;
        const distance = Math.hypot(dx, dy);
        const minimum = 68;
        if (distance >= minimum) continue;
        const shift = (minimum - distance) / 2;
        const unitX = dx / Math.max(distance, .01);
        const unitY = dy / Math.max(distance, .01);
        left.x -= unitX * shift; left.y -= unitY * shift;
        right.x += unitX * shift; right.y += unitY * shift;
        left.x = clamp(left.x, padding, width - padding); left.y = clamp(left.y, padding, height - padding);
        right.x = clamp(right.x, padding, width - padding); right.y = clamp(right.y, padding, height - padding);
      }
    }
  }
}

function separateClusters(points: Map<string, ClusterLayoutPoint>, width: number, height: number, padding: number, gap: number) {
  const clusterIds = Array.from(new Set(Array.from(points.values()).map((point) => point.cluster))).sort((left, right) => left - right);
  if (clusterIds.length < 2) return;

  for (let pass = 0; pass < 120; pass += 1) {
    let moved = false;
    for (let leftIndex = 0; leftIndex < clusterIds.length; leftIndex += 1) {
      for (let rightIndex = leftIndex + 1; rightIndex < clusterIds.length; rightIndex += 1) {
        const leftId = clusterIds[leftIndex]; const rightId = clusterIds[rightIndex];
        if (leftId === undefined || rightId === undefined) continue;
        const left = clusterBounds(points, leftId, gap / 2);
        const right = clusterBounds(points, rightId, gap / 2);
        if (!left || !right) continue;
        const overlapX = Math.min(left.maxX, right.maxX) - Math.max(left.minX, right.minX);
        const overlapY = Math.min(left.maxY, right.maxY) - Math.max(left.minY, right.minY);
        if (overlapX <= 0 || overlapY <= 0) continue;

        const horizontal = overlapX <= overlapY;
        const direction = horizontal
          ? (right.cx === left.cx ? (rightId > leftId ? 1 : -1) : Math.sign(right.cx - left.cx))
          : (right.cy === left.cy ? (rightId > leftId ? 1 : -1) : Math.sign(right.cy - left.cy));
        const distance = (horizontal ? overlapX : overlapY) / 2 + 1;
        moveCluster(points, leftId, horizontal ? -direction * distance : 0, horizontal ? 0 : -direction * distance, width, height, padding);
        moveCluster(points, rightId, horizontal ? direction * distance : 0, horizontal ? 0 : direction * distance, width, height, padding);
        moved = true;
      }
    }
    if (!moved) break;
  }
}

function clusterBounds(points: Map<string, ClusterLayoutPoint>, cluster: number, expansion = 0) {
  const members = Array.from(points.values()).filter((point) => point.cluster === cluster);
  if (!members.length) return null;
  const envelope = envelopeForPoints(cluster, members);
  return {
    minX: envelope.cx - envelope.rx - expansion, maxX: envelope.cx + envelope.rx + expansion,
    minY: envelope.cy - envelope.ry - expansion, maxY: envelope.cy + envelope.ry + expansion,
    cx: envelope.cx, cy: envelope.cy,
  };
}

function moveCluster(points: Map<string, ClusterLayoutPoint>, cluster: number, dx: number, dy: number, width: number, height: number, padding: number) {
  const bounds = clusterBounds(points, cluster);
  if (!bounds) return;
  const boundedDx = clamp(dx, padding - bounds.minX, width - padding - bounds.maxX);
  const boundedDy = clamp(dy, padding - bounds.minY, height - padding - bounds.maxY);
  points.forEach((point) => {
    if (point.cluster !== cluster) return;
    point.x += boundedDx; point.y += boundedDy;
  });
}

function clamp(value: number, minimum: number, maximum: number) { return Math.min(maximum, Math.max(minimum, value)); }

// Reserve room for the largest node and its label. A deterministic grid avoids
// collision solvers squeezing nodes back together at fixed viewport boundaries.
function spaceClusterNodes(points: Map<string, ClusterLayoutPoint>) {
  const groups = new Map<number, ClusterLayoutPoint[]>();
  points.forEach(p => groups.set(p.cluster, [...(groups.get(p.cluster) ?? []), p]));
  for (const members of groups.values()) {
    const occupied = new Set<string>();
    const cx = members.reduce((sum,p) => sum+p.x,0)/members.length;
    const cy = members.reduce((sum,p) => sum+p.y,0)/members.length;
    for (const p of members) {
      const x = Math.round((p.x-cx)/160), y = Math.round((p.y-cy)/104);
      let best: {x:number;y:number;distance:number} | undefined;
      for (let ring=0; !best; ring++) {
        for (let dx=-ring; dx<=ring; dx++) for (let dy=-ring; dy<=ring; dy++) {
          if (Math.max(Math.abs(dx),Math.abs(dy))!==ring || occupied.has(`${x+dx}:${y+dy}`)) continue;
          const distance = ((x+dx)*160+cx-p.x)**2 + ((y+dy)*104+cy-p.y)**2;
          if (!best || distance<best.distance) best={x:x+dx,y:y+dy,distance};
        }
      }
      occupied.add(`${best.x}:${best.y}`);
      p.x=cx+best.x*160; p.y=cy+best.y*104;
    }
  }
}


// Pack complete envelope rectangles without clamping them back into a fixed viewport.
function packClusters(points: Map<string, ClusterLayoutPoint>, aspect: number, padding: number, gap: number) {
  const envelopes = clusterEnvelopes(points).sort((a, b) => b.ry - a.ry || b.rx - a.rx || a.cluster - b.cluster);
  const area = envelopes.reduce((sum, item) => sum + (item.rx * 2 + gap) * (item.ry * 2 + gap), 0);
  const rowWidth = Math.max(Math.sqrt(area * aspect), ...envelopes.map((item) => item.rx * 2));
  const offsets = new Map<number, { x: number; y: number }>();
  let x = padding; let y = padding; let rowHeight = 0;
  for (const envelope of envelopes) {
    const width = envelope.rx * 2; const height = envelope.ry * 2;
    if (x > padding && x + width > padding + rowWidth) { x = padding; y += rowHeight + gap; rowHeight = 0; }
    offsets.set(envelope.cluster, { x: x + envelope.rx - envelope.cx, y: y + envelope.ry - envelope.cy });
    x += width + gap;
    rowHeight = Math.max(rowHeight, height);
  }
  points.forEach((point) => { const offset = offsets.get(point.cluster); if (offset) { point.x += offset.x; point.y += offset.y; } });
}
