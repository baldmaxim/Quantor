import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { diagnostics, preview, SHA } from '@/components/cad/viewer/fixtures';
import type * as ViewQueries from '@/lib/cad/view-queries';
import { MEP_HIDDEN_KEY } from '@/lib/cad/mep-layers';
import { resetStoredNumbers } from '@/lib/cad/useStoredNumber';
import { Camera } from '@/lib/viewer/camera';
import { useWorkspaceStore } from '@/store/workspace';

const PARENT = '11111111-1111-4111-8111-111111111111';
const ROUTE = '33333333-3333-4333-8333-333333333333';
const ROUTE_SHA = 'c'.repeat(64);

const mocks = vi.hoisted(() => ({
  bindings: [] as unknown[],
  remarks: { current: [] as { id: string; status: string; bbox_pt: number[] }[] },
}));

const parentDetail = {
  job_id: PARENT,
  revision_id: 'r1',
  result_attempt: 2,
  result_status: 'completed_requires_review',
  pages: [{ index: 0, legacy_pdf_page: 1, views: [{ view: 1 }, { view: 2 }] }],
};
const routeDetail = {
  job_id: ROUTE,
  revision_id: 'r1',
  result_attempt: 1,
  result_status: 'completed_requires_review',
  pages: [{ index: 0, legacy_pdf_page: 1, views: [{ view: 2 }] }],
};

vi.mock('@/lib/cad/queries', () => ({
  useCadJobs: () => ({
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    data: {
      items: [
        {
          job_id: ROUTE,
          job_type: 'cad_mep_route',
          parent_job_id: PARENT,
          page_index: 0,
          view: 2,
          status: 'succeeded',
          result_status: 'completed_requires_review',
          requested_pages: [0],
          created_at: '2026-11-10T12:00:00Z',
        },
        {
          job_id: PARENT,
          job_type: 'cad_pdf_convert',
          parent_job_id: null,
          page_index: null,
          view: null,
          status: 'succeeded',
          result_status: 'completed_requires_review',
          requested_pages: [0],
          created_at: '2026-11-10T10:00:00Z',
        },
      ],
    },
  }),
  useCadJob: (_p: string, _r: string | null, jobId: string | null) => ({
    isError: false,
    data: jobId === ROUTE ? routeDetail : jobId === PARENT ? parentDetail : undefined,
  }),
}));
vi.mock('@/lib/cad/zones-queries', () => ({
  useCadZones: () => ({
    data: undefined,
    isPending: false,
    fetchStatus: 'idle',
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  useCreateCadZone: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateCadZone: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteCadZone: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('@/lib/cad/view-queries', async (importOriginal) => ({
  ...(await importOriginal<typeof ViewQueries>()),
  useCadView: (params: { jobId: string; attempt: number; view: number }, enabled: boolean) => {
    if (enabled !== true) return { isError: false, data: undefined };
    if (params.jobId === ROUTE) {
      return {
        isError: false,
        data: diagnostics({
          job_id: ROUTE,
          attempt: 1,
          view: 2,
          dxf: { name: 'views/p001_v02/mep_routes.dxf', sha256: ROUTE_SHA, size: 10 },
        }),
      };
    }
    return {
      isError: false,
      data: diagnostics({
        job_id: PARENT,
        attempt: 2,
        view: params.view,
        route_jobs: [
          {
            job_id: ROUTE,
            status: 'succeeded',
            attempt: 1,
            created_at: '2026-11-10T12:00:00Z',
            finished_at: null,
            error_code: null,
            floor_elevation_mm: 10000,
            floor_height_mm: 3000,
            generator_version: 'cad_mep.v1',
            accepted: false,
          },
        ],
      }),
    };
  },
  useCadPreview: (params: { jobId: string }, enabled: boolean) => ({
    isError: false,
    isPending: false,
    data:
      enabled !== true
        ? undefined
        : params.jobId === ROUTE
          ? preview({
              job_id: ROUTE,
              dxf_sha256: ROUTE_SHA,
              layers: ['M-OV-T1', 'M-OV-T2', 'M-NODE'],
              paths: [{ layer: 0, closed: false, fill: false, points: [0, 0, 1000, 0] }],
            })
          : preview({ job_id: PARENT, dxf_sha256: SHA }),
  }),
}));
vi.mock('@/components/cad/viewer/useCadRemarks', () => ({
  useCadRemarks: (binding: unknown) => {
    mocks.bindings.push(binding);
    return {
      remarks: mocks.remarks.current,
      loading: false,
      loadError: null,
      reload: vi.fn(),
      reviewer: '',
      setReviewer: vi.fn(),
      saving: false,
      error: null,
      add: vi.fn(),
      update: vi.fn(),
      remove: vi.fn(),
      importFile: vi.fn(),
    };
  },
}));

import { useWorkspaceCad } from './useWorkspaceCad';

const camera = new Camera();
const navigate = vi.fn();

type Inputs = Parameters<typeof useWorkspaceCad>[0];

const inputs = (patch: Partial<Inputs> = {}): Inputs => ({
  projectId: 'p1',
  revisionId: 'r1',
  sheets: [{ page_index: 0 }],
  sheet: { id: 's0', page_index: 0, page_label: '1' },
  page: { pageIndex: 0, width: 842, height: 595 },
  camera,
  viewportSize: () => ({ width: 800, height: 600 }),
  enabled: true,
  active: true,
  tabParam: null,
  jobParam: null,
  viewParam: null,
  navigate,
  ...patch,
});

const mount = (patch: Partial<Inputs> = {}) =>
  renderHook((props: Inputs) => useWorkspaceCad(props), { initialProps: inputs(patch) });

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  resetStoredNumbers();
  mocks.bindings.length = 0;
  mocks.remarks.current = [];
  useWorkspaceStore.setState({ leftTab: 'documents' });
});

describe('useWorkspaceCad: трассы механики', () => {
  it('более новое route-задание не подменяет преобразование листа', () => {
    const { result } = mount();
    expect(result.current.side.job?.jobId).toBe(PARENT);
    expect(result.current.side.view?.layers.mep ?? null).toBeNull();
    expect(result.current.side.view?.mep?.route).toBeNull();
    expect(result.current.side.view?.mep?.routeJobs.map((item) => item.job_id)).toEqual([ROUTE]);
    expect(result.current.side.view?.mep?.parent).toMatchObject({
      jobId: PARENT,
      attempt: 2,
      pageIndex: 0,
    });
  });

  it('трассы в адресе: вид родителя на холсте, слои трасс в панели, вид и выбор - по заданию', () => {
    const { result } = mount({ jobParam: ROUTE });
    const side = result.current.side;
    expect(side.job?.jobId).toBe(PARENT);
    expect(result.current.bar?.view).toBe(2);
    expect(side.view?.mep?.route?.summaryId).toBe(ROUTE);
    expect(side.view?.mep?.route?.params).toMatchObject({ jobId: ROUTE, attempt: 1, view: 2 });
    expect(side.view?.layers.mep?.names).toEqual(['M-OV-T1', 'M-OV-T2', 'M-NODE']);
    expect(side.view?.layers.mep?.visible.size).toBe(3);
    expect(side.view?.layers.layers).toEqual(['WALLS', 'DOORS']);
    expect(result.current.left?.selectedJobId).toBe(ROUTE);
    expect(result.current.painter).not.toBeNull();
  });

  it('замечания привязаны к route-заданию и его DXF', () => {
    mount({ jobParam: ROUTE });
    expect(mocks.bindings.at(-1)).toMatchObject({
      jobId: ROUTE,
      attempt: 1,
      pageIndex: 0,
      view: 2,
      dxfSha256: ROUTE_SHA,
    });
  });

  it('без трасс замечания принадлежат виду родителя', () => {
    mount();
    expect(mocks.bindings.at(-1)).toMatchObject({ jobId: PARENT, attempt: 2, dxfSha256: SHA });
  });

  it('открытые замечания считаются у показанного вида', () => {
    mocks.remarks.current = [
      { id: 'a', status: 'open', bbox_pt: [1, 1, 5, 5] },
      { id: 'b', status: 'resolved', bbox_pt: [1, 1, 5, 5] },
      { id: 'c', status: 'open', bbox_pt: [1, 1, 5, 5] },
    ];
    expect(mount().result.current.side.view?.mep?.openRemarks).toBe(2);
    mocks.remarks.current = [{ id: 'b', status: 'resolved', bbox_pt: [1, 1, 5, 5] }];
    expect(mount().result.current.side.view?.mep?.openRemarks).toBe(0);
  });

  it('route-задание, не относящееся к листу, из адреса отбрасывается', () => {
    const { result } = mount({
      jobParam: ROUTE,
      sheet: { id: 's1', page_index: 5, page_label: '6' },
      sheets: [{ page_index: 5 }],
      page: { pageIndex: 5, width: 842, height: 595 },
    });
    expect(result.current.side.state).toBe('none');
  });

  it('выбор трасс и возврат к виду пишут задание и вид в адрес', () => {
    const { result } = mount();
    act(() => result.current.side.view?.mep?.onSelectRoute(ROUTE));
    expect(navigate).toHaveBeenLastCalledWith({ job: ROUTE, view: '1' });
    act(() => result.current.side.view?.mep?.onSelectRoute(null));
    expect(navigate).toHaveBeenLastCalledWith({ job: PARENT, view: '1' });
  });

  it('выбор route-задания слева открывает его на своём виде', () => {
    const { result } = mount();
    act(() => result.current.left?.onSelectJob(ROUTE));
    expect(navigate).toHaveBeenLastCalledWith({ job: ROUTE, view: '2' });
  });

  it('слой трасс выключается и это помнится в браузере', () => {
    const { result } = mount({ jobParam: ROUTE });
    act(() => result.current.side.view?.layers.mep?.onToggle(2));
    expect(result.current.side.view?.layers.mep?.visible.has(2)).toBe(false);
    expect(result.current.side.view?.layers.mep?.visible.has(0)).toBe(true);
    expect(Number(window.localStorage.getItem(MEP_HIDDEN_KEY))).toBeGreaterThan(0);

    act(() => result.current.side.view?.layers.mep?.onSetHidden([0, 1, 2], false));
    expect(result.current.side.view?.layers.mep?.visible.size).toBe(3);
  });
});
