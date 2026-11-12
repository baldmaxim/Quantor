import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  putCadConstructionProps: vi.fn(),
  bulkCadConstructionProps: vi.fn(),
  putCadSheetLevels: vi.fn(),
  recomputeCadWalls: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { building3dKeys } from './building3d-queries';
import {
  useBulkConstructionProps,
  useRecomputeCadWalls,
  useSaveConstructionProps,
  useSaveSheetLevels,
} from './constructions-queries';
import { floor3dKeys } from './floor3d-queries';
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

const invalidatedKeys = (spy: ReturnType<typeof setup>['spy']) =>
  spy.mock.calls.map(([filters]) => filters?.queryKey);

describe('правка конструкций обновляет 3D листа', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.putCadConstructionProps.mockResolvedValue({ data: { id: 'c1' } });
    api.bulkCadConstructionProps.mockResolvedValue({ data: {} });
    api.putCadSheetLevels.mockResolvedValue({ data: {} });
    api.recomputeCadWalls.mockResolvedValue({ data: {} });
  });

  const expectInvalidated = (spy: ReturnType<typeof setup>['spy']) => {
    const keys = invalidatedKeys(spy);
    expect(keys).toContainEqual(floor3dKeys.view(PARAMS));
    expect(keys).toContainEqual(building3dKeys.project('p1'));
  };

  it('параметры одной конструкции', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useSaveConstructionProps(PARAMS), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ key: 'c1', props: {} });
    });
    await waitFor(() => expectInvalidated(spy));
  });

  it('массовая правка', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useBulkConstructionProps(PARAMS), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ keys: ['c1'], patch: {} });
    });
    await waitFor(() => expectInvalidated(spy));
  });

  it('высоты листа', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useSaveSheetLevels(PARAMS), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({});
    });
    await waitFor(() => expectInvalidated(spy));
  });

  it('пересчёт конструкций', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useRecomputeCadWalls(PARAMS), { wrapper });
    await act(async () => {
      await result.current.mutateAsync();
    });
    await waitFor(() => expectInvalidated(spy));
  });

  it('вида нет - ничего не инвалидируется', async () => {
    const { spy, wrapper } = setup();
    const { result } = renderHook(() => useSaveSheetLevels(null), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({}).catch(() => undefined);
    });
    expect(spy).not.toHaveBeenCalled();
  });
});
