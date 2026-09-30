import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { it, expect } from 'vitest';
import { FundingCoverageList } from './ScholarGraphAnalyticsPage';

it('expands categories into kinds rather than concrete projects', () => {
  render(<MemoryRouter><FundingCoverageList publicationCount={10} items={[{ id: 'category', name: '地方资助', count: 5, source: '', kinds: [{ object_id: 'kind', name: '辽宁自然科学基金', project_count: 3, publication_count: 5 }] }]} /></MemoryRouter>);
  const toggle = screen.getByRole('button', { name: /地方资助（1 个项目种类）/ });
  fireEvent.click(toggle);
  expect(screen.getByRole('link', { name: '辽宁自然科学基金' })).toHaveAttribute('href', '/outputs/kind');
  expect(screen.getByText('3 个具体项目 · 5 篇论文')).toBeVisible();
  expect(screen.queryByText(/编号：/)).not.toBeInTheDocument();
});

it('expands and collapses all concrete projects without changing coverage', () => {
  render(<MemoryRouter><FundingCoverageList publicationCount={10} items={[{ id: 'c', name: '中央资助', count: 5, source: '类内去重', projects: [{ object_id: 'p', name: '测试项目', kind_name: '国自然', grant_number: '123' }] }]} /></MemoryRouter>);
  const toggle = screen.getByRole('button', { name: /中央资助/ });
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByRole('link', { name: '测试项目' })).not.toBeInTheDocument();
  fireEvent.click(toggle);
  expect(screen.getByRole('link', { name: '测试项目' })).toHaveAttribute('href', '/outputs/p');
  expect(screen.getByText('编号：123')).toBeVisible();
  expect(screen.getByText('50%')).toBeVisible();
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute('aria-expanded', 'false');
  expect(screen.queryByRole('link', { name: '测试项目' })).not.toBeInTheDocument();
});
