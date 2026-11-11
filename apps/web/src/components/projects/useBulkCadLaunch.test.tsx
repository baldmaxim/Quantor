import type * as ApiClient from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { FC, ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ createJob: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  createCadJob: mocks.createJob,
}));

import { BULK_CAD_CONCURRENCY, useBulkCadLaunch } from './useBulkCadLaunch';

const setup = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, 'invalidateQueries');
  const Wrapper: FC<{ children: ReactNode }> = ({ children }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const hook = renderHook(() => useBulkCadLaunch('p-1', 'rev-1'), { wrapper: Wrapper });
  return { ...hook, invalidate };
};

describe('useBulkCadLaunch', () => {
  beforeEach(() => {
    mocks.createJob.mockReset();
  });

  it('по заданию на лист с auto_scale и не больше трёх запросов одновременно', async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const releases: Array<() => void> = [];
    mocks.createJob.mockImplementation(
      () =>
        new Promise((resolve) => {
          inFlight += 1;
          maxInFlight = Math.max(maxInFlight, inFlight);
          releases.push(() => {
            inFlight -= 1;
            resolve({ data: { job_id: 'job' } });
          });
        }),
    );
    const { result, invalidate } = setup();

    let done: Promise<void> = Promise.resolve();
    act(() => {
      done = result.current.launch([0, 1, 2, 3, 4, 5, 6]);
    });

    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledTimes(BULK_CAD_CONCURRENCY));
    expect(result.current.running).toBe(true);
    expect(result.current.total).toBe(7);

    // Освобождаем по одному: в полёте всегда не больше трёх, пока очередь не пуста.
    while (result.current.running) {
      const release = releases.shift();
      if (release) await act(async () => release());
      else await act(async () => Promise.resolve());
    }
    await done;

    expect(maxInFlight).toBe(BULK_CAD_CONCURRENCY);
    expect(mocks.createJob).toHaveBeenCalledTimes(7);
    expect(result.current.placed).toBe(7);
    expect(result.current.failures).toEqual([]);
    for (const [index, call] of mocks.createJob.mock.calls.entries()) {
      expect(call[0]).toMatchObject({
        path: { project_id: 'p-1', revision_id: 'rev-1' },
        body: { pages: [index], finishes: false, schedules: false, auto_scale: true },
      });
    }
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['cad', 'p-1', 'rev-1', 'pipeline'] });
  });

  it('отказ одного листа не останавливает остальные и попадает в сводку', async () => {
    mocks.createJob.mockImplementation(({ body }: { body: { pages: number[] } }) =>
      body.pages[0] === 1
        ? Promise.reject({ status: 409, code: 'CAD_CALIBRATION_REQUIRED', message: 'x' })
        : Promise.resolve({ data: { job_id: `job-${String(body.pages[0])}` } }),
    );
    const { result } = setup();

    await act(async () => {
      await result.current.launch([0, 1, 2]);
    });

    expect(mocks.createJob).toHaveBeenCalledTimes(3);
    expect(result.current.running).toBe(false);
    expect(result.current.placed).toBe(2);
    expect(result.current.failures).toHaveLength(1);
    expect(result.current.failures[0]?.pageIndex).toBe(1);
    expect(result.current.failures[0]?.message).not.toBe('');
  });

  it('пустой список ничего не запускает', async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.launch([]);
    });
    expect(mocks.createJob).not.toHaveBeenCalled();
    expect(result.current.running).toBe(false);
  });
});
