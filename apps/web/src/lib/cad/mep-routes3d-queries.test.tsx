import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { FC, ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { routeMark, useCadMepRoutes3d } from './mep-routes3d-queries';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readCadMepRoutes3D: vi.fn(),
  listCadJobs: vi.fn(),
}));

/** Рабочая область: план показывает route-задание `j2`. */
const input = {
  projectId: 'p1',
  revisionId: 'r1',
  pageIndex: 2,
  view: 1,
  parentJobId: 'j1',
  routeJobId: 'j2',
  enabled: true,
};

const wrapper = (): FC<{ children: ReactNode }> => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper: FC<{ children: ReactNode }> = ({ children }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

const refuse = (code: string) =>
  Promise.reject({ detail: { code } }) as never;

const routes3d = {
  job_id: 'j2',
  generator_version: 'cad_mep.v7',
  floor_elevation_mm: 3000,
  floor_height_mm: 2800,
  levels_elevation_mm: 3000,
  levels_height_mm: 2800,
  heights_match: true,
  polylines: [{ layer: 'M-OV-T1', pts: [[0, 0, 100]] }],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(client.listCadJobs).mockResolvedValue({ data: { items: [] } } as never);
});

describe('трассы 3D: чтение', () => {
  it('готовый ответ - ready с данными; запрос идёт с листом, видом и заданием плана', async () => {
    vi.mocked(client.readCadMepRoutes3D).mockResolvedValue({ data: routes3d } as never);
    const { result } = renderHook(() => useCadMepRoutes3d(input), { wrapper: wrapper() });
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(client.readCadMepRoutes3D).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { project_id: 'p1' },
        query: { revision_id: 'r1', page_index: 2, view: 1, job_id: 'j2' },
      }),
    );
  });

  it('404 CAD_ROUTES_NOT_FOUND - none', async () => {
    vi.mocked(client.readCadMepRoutes3D).mockImplementation(() => refuse('CAD_ROUTES_NOT_FOUND'));
    const { result } = renderHook(() => useCadMepRoutes3d(input), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.status).toBe('none'));
  });

  it('404 CAD_ROUTES3D_MISSING - stale', async () => {
    vi.mocked(client.readCadMepRoutes3D).mockImplementation(() => refuse('CAD_ROUTES3D_MISSING'));
    const { result } = renderHook(() => useCadMepRoutes3d(input), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.status).toBe('stale'));
  });

  it('прочий отказ - error, без исключения', async () => {
    vi.mocked(client.readCadMepRoutes3D).mockImplementation(() => refuse('CAD_ENGINE_FAILED'));
    const { result } = renderHook(() => useCadMepRoutes3d(input), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.status).toBe('error'));
  });

  it('выключенный запрос ничего не читает', () => {
    const { result } = renderHook(() => useCadMepRoutes3d({ ...input, enabled: false }), {
      wrapper: wrapper(),
    });
    expect(result.current.status).toBe('loading');
    expect(client.readCadMepRoutes3D).not.toHaveBeenCalled();
  });
});

describe('трассы 3D: какое задание', () => {
  const summary = (patch: Partial<client.CadJobSummaryRead>) => ({
    job_id: 'r-old',
    job_type: 'cad_mep_route' as const,
    parent_job_id: 'j1',
    status: 'succeeded' as const,
    page_index: 2,
    view: 1,
    attempt: 1,
    created_at: '2026-11-11T10:00:00Z',
    finished_at: '2026-11-11T10:05:00Z',
    ...patch,
  });

  it('на плане трасс нет (null) - none без запроса', async () => {
    const { result } = renderHook(() => useCadMepRoutes3d({ ...input, routeJobId: null }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.status).toBe('none'));
    expect(client.readCadMepRoutes3D).not.toHaveBeenCalled();
  });

  it('без задания плана - автовыбор плана: новейшее у задания листа, чужой родитель не берётся', async () => {
    vi.mocked(client.listCadJobs).mockResolvedValue({
      data: {
        items: [
          summary({}),
          summary({ job_id: 'r-new', created_at: '2026-11-11T12:00:00Z' }),
          summary({ job_id: 'r-foreign', parent_job_id: 'j9', created_at: '2026-11-11T13:00:00Z' }),
        ],
      },
    } as never);
    vi.mocked(client.readCadMepRoutes3D).mockResolvedValue({ data: routes3d } as never);
    const { result } = renderHook(() => useCadMepRoutes3d({ ...input, routeJobId: undefined }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(vi.mocked(client.readCadMepRoutes3D).mock.calls[0]?.[0]).toMatchObject({
      query: { job_id: 'r-new' },
    });
  });

  it('без задания плана и без трасс у задания листа - none', async () => {
    const { result } = renderHook(() => useCadMepRoutes3d({ ...input, routeJobId: undefined }), {
      wrapper: wrapper(),
    });
    await waitFor(() => expect(result.current.status).toBe('none'));
    expect(client.readCadMepRoutes3D).not.toHaveBeenCalled();
  });

  it('отметка меняется с попыткой и завершением; задания нет в списке - один id', () => {
    const jobs = [summary({ job_id: 'j2', attempt: 2 })];
    expect(routeMark(jobs, 'j2')).toBe('j2:succeeded:2:2026-11-11T10:05:00Z');
    expect(routeMark(jobs, 'j3')).toBe('j3');
  });
});
