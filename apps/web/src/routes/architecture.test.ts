import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('production route boundaries', () => {
  it('does not import demo fixtures directly from route modules', () => {
    const routesDir = resolve(import.meta.dirname);
    const offenders = readdirSync(routesDir)
      .filter((name) => name.endsWith('.tsx'))
      .filter((name) => readFileSync(resolve(routesDir, name), 'utf8').includes('/fixtures/demo'));
    expect(offenders).toEqual([]);
  });

  it('routes ScholarGraph through the real Scholar feature without demo fixtures', () => {
    const route = readFileSync(resolve(import.meta.dirname, 'ScholarRoute.tsx'), 'utf8');
    const feature = readFileSync(resolve(import.meta.dirname, '../features/scholars/ScholarGraph.tsx'), 'utf8');
    expect(route).toContain('../features/scholars/ScholarGraph');
    expect(route).not.toContain('DemoBoundary');
    expect(route).not.toContain('features/demo');
    expect(feature).not.toContain('/fixtures/demo');
  });
});
