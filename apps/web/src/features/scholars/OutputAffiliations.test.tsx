import { requiredValue } from '../../shared/requiredValue';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, it } from 'vitest';
import type { ScholarAffiliation } from '../../generated/smartlib-api';
import { groupOutputAffiliations, OutputAffiliations } from './OutputAffiliations';

function row(id: string, org: string, paper: string | null, raw: string): ScholarAffiliation {
  return { relation_id: id, organization_id: org, organization_name: '大学', category: 'output',
    context_object_id: paper, context_title: paper ? `论文${paper}` : null, raw_affiliation: raw, is_current: false, evidence: [] };
}
it('groups by organization and paper while preserving multiple original statements', () => {
  const rows = [row('r1','o1','p1','原文甲'), row('r2','o1','p1','原文乙'), row('r3','o1','p2','原文丙')];
  const groups = groupOutputAffiliations(rows);
  expect(groups).toHaveLength(1);
  expect(groups[0]?.papers.size).toBe(2);
  render(<MemoryRouter><OutputAffiliations items={rows} /></MemoryRouter>);
  expect(screen.getAllByRole('heading')).toHaveLength(1);
  expect(screen.getByText('2 篇论文支持此机构署名')).toBeInTheDocument();
  const summary = screen.getByText('2 篇论文支持此机构署名');
  const details = requiredValue(summary.closest('details'));
  expect(details.open).toBe(false);
  fireEvent.click(summary);
  expect(details.open).toBe(true);
  expect(screen.getAllByRole('link', { name: /^论文/ })).toHaveLength(2);
  for (const text of ['原文甲','原文乙','原文丙']) expect(screen.getByText(`机构原文：${text}`)).toBeInTheDocument();
  fireEvent.click(summary);
  expect(details.open).toBe(false);
});
it('nests confirmed children with level labels, links, and initially collapsed papers', () => {
  const parent = { ...row('r1','o1','p1','甲'), organization_level: 1 };
  const child = { ...row('r2','o2','p2','乙'), organization_name: '学院', organization_level: 2, parent_organization_ids: ['o1'] };
  const { container } = render(<MemoryRouter><OutputAffiliations items={[child, parent]} /></MemoryRouter>);
  expect(screen.getByText('一级机构')).toBeInTheDocument();
  expect(screen.getByText('二级机构')).toBeInTheDocument();
  expect(container.querySelector('.sg-affiliation-children')).toHaveTextContent('学院');
  expect(screen.getByRole('link', { name: '查看学院的机构详情' })).toHaveAttribute('href', '/institutions/o2');
  expect(container.querySelectorAll('.sg-affiliation-support[open]')).toHaveLength(0);
});
it('keeps cyclic and ambiguous hierarchy visible without recursive loops', () => {
  const rows = [
    { ...row('r1','o1','p1','甲'), parent_organization_ids: ['o2'] },
    { ...row('r2','o2','p2','乙'), parent_organization_ids: ['o1'] },
    { ...row('r3','o3','p3','丙'), parent_organization_ids: ['o1','o2'] },
  ];
  const { container } = render(<MemoryRouter><OutputAffiliations items={rows} /></MemoryRouter>);
  expect(container.querySelectorAll('.sg-affiliation-node')).toHaveLength(3);
  expect(container.querySelectorAll('.sg-affiliation-tree > li')).toHaveLength(2);
});
it('does not merge different entities with the same name or unrelated missing-source records', () => {
  const rows = [row('r1','o1',null,'甲'),row('r2','o1',null,'乙'),row('r3','o2','p1','丙')];
  expect(groupOutputAffiliations(rows)).toHaveLength(2);
  expect(groupOutputAffiliations(rows)[0]?.papers.size).toBe(2);
  expect(groupOutputAffiliations([{ ...requiredValue(rows[0]), category: 'authoritative' }])).toHaveLength(0);
});
