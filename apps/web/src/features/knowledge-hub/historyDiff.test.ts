import { describe, expect, it } from 'vitest';
import { historyDiff } from './historyDiff';
describe('historyDiff', () => {
  it('distinguishes missing fields from explicit empty values', () => {
    expect(historyDiff({}, { description: null })).toEqual([{ field: 'description', before: undefined, after: null }]);
  });
  it('shows changed nested evidence and preserves unchanged fields', () => {
    expect(historyDiff({ name: 'A', evidence: { page: 1 } }, { name: 'A', evidence: { page: 2 } })).toEqual([
      { field: 'evidence', before: { page: 1 }, after: { page: 2 } },
    ]);
  });
});
