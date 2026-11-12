import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  createCadJob: vi.fn(),
  retryCadJob: vi.fn(),
  approveCadView: vi.fn(),
  createCadMepRoutes: vi.fn(),
  recomputeCadMepRoutes: vi.fn(),
  recomputeCadWalls: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { useRecomputeCadWalls } from './constructions-queries';
import { useApproveCadView, useBuildMepRoutes, useRecomputeMepRoutes } from './mep-queries';
import { cadPipelineKey } from './pipeline-queries';
import { cadKeys, useCreateCadJob, useRetryCadJob } from './queries';
import type { ICadViewParams } from './view-queries';

const PARAMS: ICadViewParams = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'j1',
  attempt: 1,
  pageIndex: 3,
  view: 1,
};

const setup = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const spy = vi.spyOn(client, 'invalidateQueries');
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { spy, wrapper };
};

const keysOf = (spy: ReturnType<typeof setup>['spy']) =>
  spy.mock.calls.map(([filters]) => filters?.queryKey);

/** Каждое действие, ставящее или повторяющее задание CAD, сбрасывает список заданий и конвейер листа. */
describe('мутации заданий CAD обновляют конвейер листа', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const fn of Object.values(api)) fn.mockResolvedValue({ data: { job_id: 'j1' } });
  });

  const expectBoth = (spy: ReturnType<typeof setup>['spy']) => {
    const keys = keysOf(spy);
    expect(keys).toContainEqual(cadKeys.jobs('p1', 'r1'));
    expect(keys).toContainEqual(cadPipelineKey('p1', 'r1'));
  };

  it('создание задания', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useCreateCadJob('p1', 'r1'), { wrapper });
    await act(async () => result.current.mutate({ pages: [0] }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expectBoth(spy);
  });

  it('повтор задания', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useRetryCadJob('p1', 'r1', 'j1'), { wrapper });
    await act(async () => result.current.mutate());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expectBoth(spy);
  });

  it('одобрение вида', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useApproveCadView(PARAMS), { wrapper });
    await act(async () => result.current.mutate({}));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expectBoth(spy);
  });

  it('постройка трасс', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useBuildMepRoutes(PARAMS), { wrapper });
    await act(async () => result.current.mutate({ floorElevationMm: null, floorHeightMm: null }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expectBoth(spy);
  });

  it('пересчёт трасс', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useRecomputeMepRoutes(PARAMS), { wrapper });
    await act(async () => result.current.mutate({ floorElevationMm: null, floorHeightMm: null }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expectBoth(spy);
  });

  it('пересчёт конструкций', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useRecomputeCadWalls(PARAMS), { wrapper });
    await act(async () => result.current.mutate());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(keysOf(spy)).toContainEqual(cadPipelineKey('p1', 'r1'));
  });
});
