import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  create: vi.fn(),
  decide: vi.fn(),
  read: vi.fn(),
}));

vi.mock('@quantor/api-client', () => ({
  createCadFacadesJob: api.create,
  decideCadFacadeViews: api.decide,
  readCadFacades: api.read,
}));

import { useDecideCadFacadeViews, useStartCadFacades } from './facades-queries';

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {children}
  </QueryClientProvider>
);

describe('facades-queries', () => {
  it('запуск: POST jobs с revision_id и page_indexes null', async () => {
    api.create.mockResolvedValue({ data: { job_id: 'j' } });
    const { result } = renderHook(() => useStartCadFacades('p1', 'r1'), { wrapper });
    await act(async () => {
      await result.current.mutateAsync();
    });
    expect(api.create).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1' },
      body: { revision_id: 'r1', page_indexes: null },
    });
  });

  it('решение: POST decide с view_ids и решением', async () => {
    api.decide.mockResolvedValue({ data: { views: [] } });
    const { result } = renderHook(() => useDecideCadFacadeViews('p1', 'r1'), { wrapper });
    await act(async () => {
      result.current.mutate({ viewIds: ['a'], decision: 'accept' });
    });
    await waitFor(() => expect(api.decide).toHaveBeenCalled());
    expect(api.decide).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1' },
      body: { view_ids: ['a'], decision: 'accept' },
    });
  });
});
