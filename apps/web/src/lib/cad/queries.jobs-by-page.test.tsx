import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ listCadJobs: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { cadKeys, useCadJobs } from './queries';

const setup = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
};

describe('useCadJobs: задания листа', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listCadJobs.mockResolvedValue({ data: { items: [], server_time: '' } });
  });

  it('без страницы запрос общий, без query', async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useCadJobs('p1', 'r1'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const options = api.listCadJobs.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(options.query).toBeUndefined();
  });

  it('со страницей передаёт page_index, ключ - отдельный, но с префиксом jobs', async () => {
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useCadJobs('p1', 'r1', 5), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const options = api.listCadJobs.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(options.query).toEqual({ page_index: 5 });
    const key = cadKeys.jobsOfPage('p1', 'r1', 5);
    expect(key.slice(0, 4)).toEqual(cadKeys.jobs('p1', 'r1'));
    expect(key).not.toEqual(cadKeys.jobs('p1', 'r1'));
    // сброс по префиксу jobs задевает постраничный запрос
    api.listCadJobs.mockClear();
    await client.invalidateQueries({ queryKey: cadKeys.jobs('p1', 'r1') });
    await waitFor(() => expect(api.listCadJobs).toHaveBeenCalledTimes(1));
  });
});
