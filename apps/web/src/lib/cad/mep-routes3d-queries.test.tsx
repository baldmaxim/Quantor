import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { FC, ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { latestRouteMark, useCadMepRoutes3d } from './mep-routes3d-queries';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readCadMepRoutes3D: vi.fn(),
  listCadJobs: vi.fn(),
}));

const input = { projectId: 'p1', revisionId: 'r1', pageIndex: 2, view: 1, enabled: true };

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
  vi.mocked(client.listCadJobs).mockResolvedValue({ data: { items: [] } } as never);
});

describe('трассы 3D: чтение', () => {
  it('готовый ответ - ready с данными; запрос идёт с листом и видом', async () => {
    vi.mocked(client.readCadMepRoutes3D).mockResolvedValue({ data: routes3d } as never);
    const { result } = renderHook(() => useCadMepRoutes3d(input), { wrapper: wrapper() });
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(client.readCadMepRoutes3D).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { project_id: 'p1' },
        query: { revision_id: 'r1', page_index: 2, view: 1 },
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

describe('отметка новейшего route-задания', () => {
  const job = (patch: Partial<Parameters<typeof latestRouteMark>[0][number]>) => ({
    job_id: 'j1',
    job_type: 'cad_mep_route' as const,
    status: 'succeeded',
    page_index: 2,
    view: 1,
    attempt: 1,
    created_at: '2026-11-11T10:00:00Z',
    finished_at: '2026-11-11T10:05:00Z',
    ...patch,
  });

  it('берёт новейшее успешное задание своего листа и вида', () => {
    const mark = latestRouteMark(
      [
        job({ job_id: 'old' }),
        job({ job_id: 'new', created_at: '2026-11-11T12:00:00Z', attempt: 2 }),
        job({ job_id: 'other-page', page_index: 3, created_at: '2026-11-11T13:00:00Z' }),
        job({ job_id: 'running', status: 'running', created_at: '2026-11-11T14:00:00Z' }),
        job({ job_id: 'convert', job_type: 'cad_pdf_convert', created_at: '2026-11-11T15:00:00Z' }),
      ],
      2,
      1,
    );
    expect(mark.startsWith('new:2:')).toBe(true);
  });

  it('нет подходящих - none', () => {
    expect(latestRouteMark([], 2, 1)).toBe('none');
  });
});
