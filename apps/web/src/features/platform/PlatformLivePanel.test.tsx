import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PlatformLivePanel } from './PlatformLivePanel';

vi.mock('../../shared/api/smartlib', () => ({
  getVisibleKnowledgeObjects: vi.fn().mockResolvedValue([
    { object_id: '00000000-0000-0000-0000-000000000001', canonical_name: '演示知识对象' },
  ]),
}));

describe('PlatformLivePanel', () => {
  it('renders objects returned by the typed API boundary', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><PlatformLivePanel /></QueryClientProvider>);
    expect(screen.getByText('正在读取权威库…')).toBeInTheDocument();
    expect(await screen.findByText('演示知识对象')).toBeInTheDocument();
  });
});
