import type { KnowledgeObjectView } from '../../generated/smartlib-api';

type ObjectType = KnowledgeObjectView['object_type'];

export const researchOutputTypes = [
  { id: 'publication', label: '论文' },
  { id: 'project', label: '项目' },
  { id: 'patent', label: '专利' },
  { id: 'dataset', label: '数据集' },
] satisfies { id: ObjectType; label: string }[];

export function isClassificationNode(objectType: ObjectType) {
  return objectType === 'funding_program';
}
