import { describe, expect, it } from 'vitest';
import { isClassificationNode, researchOutputTypes } from './knowledgeSemantics';

describe('knowledge object semantics', () => {
  it('keeps classification nodes out of the research output catalog', () => {
    expect(researchOutputTypes.map((type) => type.id)).toEqual([
      'publication', 'project', 'patent', 'dataset',
    ]);
    expect(researchOutputTypes.map(type => type.id).includes('funding_program' as (typeof researchOutputTypes)[number]['id'])).toBe(false);
  });

  it('identifies funding programmes as classification nodes', () => {
    expect(isClassificationNode('funding_program')).toBe(true);
    expect(isClassificationNode('project')).toBe(false);
  });
});
