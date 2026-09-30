import { requiredValue } from '../../shared/requiredValue';
import { describe, expect, it } from 'vitest';
import { clusteredGraphLayout, clusterEnvelopes } from './clusteredGraphLayout';

const nodes = ['a', 'a1', 'a2', 'b', 'b1', 'b2'].map((id) => ({ id, label: id }));
const edges = [
  { source: 'a', target: 'a1', weight: 6 },
  { source: 'a', target: 'a2', weight: 5 },
  { source: 'a1', target: 'a2', weight: 4 },
  { source: 'b', target: 'b1', weight: 6 },
  { source: 'b', target: 'b2', weight: 5 },
  { source: 'b1', target: 'b2', weight: 4 },
  { source: 'a', target: 'b', weight: .25 },
];

describe('clusteredGraphLayout', () => {
  it('separates densely connected communities and keeps their hubs in the core', () => {
    const positions = clusteredGraphLayout(nodes, edges, { width: 1000, height: 620 });
    expect(positions.get('a')?.cluster).toBe(positions.get('a1')?.cluster);
    expect(positions.get('b')?.cluster).toBe(positions.get('b1')?.cluster);
    expect(positions.get('a')?.cluster).not.toBe(positions.get('b')?.cluster);
    expect(positions.get('a')?.role).toBe('core');
    expect(positions.get('b')?.role).toBe('core');
  });

  it('is deterministic, bounded and prevents nodes from occupying the same point', () => {
    const first = clusteredGraphLayout(nodes, edges, { width: 1000, height: 620, padding: 60 });
    const second = clusteredGraphLayout(nodes, edges, { width: 1000, height: 620, padding: 60 });
    expect(second).toEqual(first);
    const points = Array.from(first.values());
    points.forEach((point) => {
      expect(point.x).toBeGreaterThanOrEqual(60);
      expect(point.x).toBeLessThanOrEqual(940);
      expect(point.y).toBeGreaterThanOrEqual(60);
      expect(point.y).toBeLessThanOrEqual(560);
    });
    for (let left = 0; left < points.length; left += 1) {
      for (let right = left + 1; right < points.length; right += 1) {
        const a = points[left]; const b = points[right];
        if (!a || !b) continue;
        expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(a.cluster === b.cluster ? 53.9 : 71.9);
      }
    }
  });

  it('keeps the rendered cluster envelopes apart', () => {
    const positions = clusteredGraphLayout(nodes, edges, { width: 1000, height: 620, padding: 60, clusterGap: 80 });
    const envelopes = clusterEnvelopes(positions);
    expect(envelopes).toHaveLength(2);
    const left = envelopes[0]; const right = envelopes[1];
    if (!left || !right) throw new Error('Expected two cluster envelopes');
    const separatedHorizontally = Math.abs(left.cx - right.cx) >= left.rx + right.rx;
    const separatedVertically = Math.abs(left.cy - right.cy) >= left.ry + right.ry;
    expect(separatedHorizontally || separatedVertically).toBe(true);
  });

  it('contains diagonal nodes and their visible radius inside the ellipse', () => {
    const points = new Map([
      ['top-left', { x: 100, y: 100, cluster: 0, role: 'core' as const }],
      ['bottom-right', { x: 500, y: 420, cluster: 0, role: 'peripheral' as const }],
      ['center', { x: 280, y: 250, cluster: 0, role: 'core' as const }],
    ]);
    const envelope = clusterEnvelopes(points)[0];
    if (!envelope) throw new Error('Expected a cluster envelope');
    points.forEach((point) => {
      const samples = [[point.x - 40, point.y], [point.x + 40, point.y], [point.x, point.y - 40], [point.x, point.y + 40]];
      samples.forEach(([x = 0, y = 0]) => {
        const normalized = ((x - envelope.cx) / envelope.rx) ** 2 + ((y - envelope.cy) / envelope.ry) ** 2;
        expect(normalized).toBeLessThanOrEqual(1);
      });
    });
  });
});


it('packs many clusters without overlapping their envelopes on an expanded canvas', () => {
  const nodes = Array.from({ length: 80 }, (_, i) => ({ id: `n${i}` }));
  const points = clusteredGraphLayout(nodes, [], { width: 1240, height: 720, padding: 64, clusterGap: 120, expandable: true });
  const envelopes = clusterEnvelopes(points);
  expect(envelopes).toHaveLength(80);
  for (let i = 0; i < envelopes.length; i++) {
    for (let j = i + 1; j < envelopes.length; j++) {
      const a = requiredValue(envelopes[i]); const b = requiredValue(envelopes[j]);
      const xGap = Math.abs(a.cx - b.cx) - a.rx - b.rx;
      const yGap = Math.abs(a.cy - b.cy) - a.ry - b.ry;
      expect(Math.max(xGap, yGap)).toBeGreaterThanOrEqual(119.99);
    }
  }
});

it('keeps dense node circles and labels apart without dropping nodes', () => {
  const dense = Array.from({length: 180}, (_,i) => ({id: `dense-${i}`, label: '较长的机构与论文名称', communityId: i < 120 ? 0 : 1}));
  const positions = clusteredGraphLayout(dense, [], {width:1280,height:780,expandable:true,spacious:true,clusterGap:120});
  expect(positions.size).toBe(180);
  const points = [...positions.values()];
  for(let i=0;i<points.length;i++) for(let j=i+1;j<points.length;j++) {
    expect(Math.abs(requiredValue(points[i]).x-requiredValue(points[j]).x)>=159.9 || Math.abs(requiredValue(points[i]).y-requiredValue(points[j]).y)>=103.9).toBe(true);
  }
  expect(clusteredGraphLayout(dense, [], {width:1280,height:780,expandable:true,spacious:true,clusterGap:120})).toEqual(positions);
});

it('preserves authoritative community IDs even when display edges change', () => {
  const nodes = [{ id: 'a', communityId: 4 }, { id: 'b', communityId: 4 }, { id: 'c', communityId: 9 }];
  const options = { width: 1240, height: 720, expandable: true };
  const first = clusteredGraphLayout(nodes, [{ source: 'a', target: 'c' }], options);
  const second = clusteredGraphLayout(nodes, [{ source: 'a', target: 'b' }], options);
  expect([...first.values()].map((p) => p.cluster)).toEqual([4, 4, 9]);
  expect([...second.values()].map((p) => p.cluster)).toEqual([4, 4, 9]);
});
