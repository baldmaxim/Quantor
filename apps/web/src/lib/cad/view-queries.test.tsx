import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { FC, ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { diagnostics } from '@/components/cad/viewer/fixtures';

import { useCadView, viewNeedsRefresh, viewStaleTime, type ICadViewParams } from './view-queries';

const mocks = vi.hoisted(() => ({ readCadView: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  readCadView: mocks.readCadView,
}));

const PARAMS: ICadViewParams = {
  projectId: 'p',
  revisionId: 'r',
  jobId: 'j',
  attempt: 1,
  pageIndex: 0,
  view: 1,
};

const reply = (previewAvailable: boolean) => ({
  data: diagnostics({ job_id: 'j', attempt: 1, page_index: 0, view: 1, preview_available: previewAvailable }),
});

describe('viewStaleTime / viewNeedsRefresh', () => {
  it('ответ без предпросмотра сразу устаревает, готовый - нет', () => {
    expect(viewStaleTime(undefined)).toBe(0);
    expect(viewStaleTime({ preview_available: false })).toBe(0);
    expect(viewStaleTime({ preview_available: true })).toBeGreaterThan(0);
  });

  it('перечитывать надо только готовое задание с ответом без предпросмотра', () => {
    expect(viewNeedsRefresh({ preview_available: false }, 'succeeded')).toBe(true);
    expect(viewNeedsRefresh({ preview_available: false }, 'running')).toBe(false);
    expect(viewNeedsRefresh({ preview_available: false }, 'queued')).toBe(false);
    expect(viewNeedsRefresh({ preview_available: true }, 'succeeded')).toBe(false);
    expect(viewNeedsRefresh(undefined, 'succeeded')).toBe(false);
    expect(viewNeedsRefresh({ preview_available: false }, undefined)).toBe(false);
  });
});

describe('useCadView: диагностика до готовности не залипает', () => {
  beforeEach(() => mocks.readCadView.mockReset());

  it('при завершении задания ответ без предпросмотра перечитывается', async () => {
    mocks.readCadView.mockResolvedValueOnce(reply(false)).mockResolvedValue(reply(true));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper: FC<{ children: ReactNode }> = ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      ({ status }: { status: string }) => useCadView(PARAMS, true, status),
      { wrapper, initialProps: { status: 'running' } },
    );

    await waitFor(() => expect(result.current.data?.preview_available).toBe(false));
    expect(mocks.readCadView).toHaveBeenCalledTimes(1);

    rerender({ status: 'succeeded' });
    await waitFor(() => expect(result.current.data?.preview_available).toBe(true));
    expect(mocks.readCadView).toHaveBeenCalledTimes(2);
  });

  it('честный ответ без предпросмотра у завершённого задания перечитывается один раз, не в цикле', async () => {
    mocks.readCadView.mockResolvedValue(reply(false));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper: FC<{ children: ReactNode }> = ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result, rerender } = renderHook(
      ({ status }: { status: string }) => useCadView(PARAMS, true, status),
      { wrapper, initialProps: { status: 'succeeded' } },
    );
    await waitFor(() => expect(mocks.readCadView).toHaveBeenCalledTimes(2));
    rerender({ status: 'succeeded' });
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(result.current.data?.preview_available).toBe(false);
    expect(mocks.readCadView).toHaveBeenCalledTimes(2);
  });
});
