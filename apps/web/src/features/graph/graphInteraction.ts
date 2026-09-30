export interface GraphPointer { x: number; y: number }

export function clientToGraph(svg: SVGSVGElement | null, clientX: number, clientY: number): GraphPointer | null {
  if (!svg) return null;
  if (typeof svg.getScreenCTM === 'function' && typeof svg.createSVGPoint === 'function') {
    const matrix = svg.getScreenCTM();
    if (matrix) {
      const point = svg.createSVGPoint(); point.x = clientX; point.y = clientY;
      const transformed = point.matrixTransform(matrix.inverse());
      return { x: transformed.x, y: transformed.y };
    }
  }
  const rect = svg.getBoundingClientRect();
  const viewBox = (svg.getAttribute('viewBox') ?? '').split(/\s+/).map(Number);
  const [viewX = 0, viewY = 0, viewWidth = rect.width || 1, viewHeight = rect.height || 1] = viewBox;
  if (rect.width > 0 && rect.height > 0) {
    return {
      x: viewX + (clientX - rect.left) * viewWidth / rect.width,
      y: viewY + (clientY - rect.top) * viewHeight / rect.height,
    };
  }
  return { x: clientX, y: clientY };
}
