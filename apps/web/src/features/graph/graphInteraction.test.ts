import { describe, expect, it } from 'vitest';
import { clientToGraph } from './graphInteraction';

describe('graphInteraction geometry', () => {
  it('falls back to viewBox scaling when an SVG matrix is unavailable', () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 1000 600');
    Object.defineProperty(svg, 'getBoundingClientRect', { value: () => ({ left: 10, top: 20, width: 500, height: 300 }) });
    expect(clientToGraph(svg, 260, 170)).toEqual({ x: 500, y: 300 });
  });
});
