import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { diagnostics, JOB_ID, preview } from '@/components/cad/viewer/fixtures';
import type * as ViewQueries from '@/lib/cad/view-queries';
import { Camera } from '@/lib/viewer/camera';
import { useWorkspaceStore } from '@/store/workspace';

const mocks = vi.hoisted(() => ({
  jobs: vi.fn(),
  job: vi.fn(),
  view: vi.fn(),
  preview: vi.fn(),
  remarks: vi.fn(),
  jobsData: { current: undefined as unknown },
  jobData: { current: undefined as unknown },
}));

vi.mock('@/lib/cad/queries', () => ({
  useCadJobs: (...args: unknown[]) => {
    mocks.jobs(...args);
    return { isPending: false, isError: false, data: mocks.jobsData.current, refetch: vi.fn() };
  },
  useCadJob: (...args: unknown[]) => {
    mocks.job(...args);
    return { isError: false, data: mocks.jobData.current };
  },
}));
vi.mock('@/lib/cad/view-queries', async (importOriginal) => ({
  ...(await importOriginal<typeof ViewQueries>()),
  useCadView: (...args: unknown[]) => {
    mocks.view(...args);
    return { isError: false, data: args[1] === true ? diagnostics() : undefined };
  },
  useCadPreview: (...args: unknown[]) => {
    mocks.preview(...args);
    return { isError: false, isPending: false, data: args[1] === true ? preview() : undefined };
  },
}));
vi.mock('@/components/cad/viewer/useCadRemarks', () => ({
  useCadRemarks: (...args: unknown[]) => {
    mocks.remarks(...args);
    return {
      remarks: [],
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

const summary = (patch: Record<string, unknown> = {}) => ({
  job_id: JOB_ID,
  status: 'succeeded',
  result_status: 'completed_requires_review',
  requested_pages: [0],
  created_at: '2026-11-10T10:00:00Z',
  ...patch,
});

const detail = {
  job_id: JOB_ID,
  revision_id: 'r1',
  result_attempt: 1,
  result_status: 'completed_requires_review',
  pages: [{ index: 0, legacy_pdf_page: 1, views: [{ view: 1 }, { view: 2 }] }],
};

const camera = new Camera();

type Inputs = Parameters<typeof useWorkspaceCad>[0];

const inputs = (patch: Partial<Inputs> = {}): Inputs => ({
  projectId: 'p1',
  revisionId: 'r1',
  sheet: { page_index: 0, page_label: '1' },
  page: { pageIndex: 0, width: 842, height: 595 },
  camera,
  viewportSize: () => ({ width: 800, height: 600 }),
  enabled: true,
  active: true,
  tabParam: null,
  ...patch,
});

const mount = (patch: Partial<Inputs> = {}) =>
  renderHook((props: Inputs) => useWorkspaceCad(props), { initialProps: inputs(patch) });

beforeEach(() => {
  vi.clearAllMocks();
  mocks.jobsData.current = { items: [], server_time: '' };
  mocks.jobData.current = undefined;
  useWorkspaceStore.setState({ leftTab: 'documents', cadOverlay: true });
});

describe('useWorkspaceCad: запросы', () => {
  it('без флага cad.export ни одного запроса CAD не уходит', () => {
    mount({ enabled: false });
    expect(mocks.jobs).toHaveBeenCalledWith('p1', null);
    expect(mocks.job).toHaveBeenCalledWith('p1', null, null);
  });

  it('вкладка CAD ещё не открывалась - запросы не уходят; после открытия идут и остаются', () => {
    const hook = mount({ active: false });
    expect(mocks.jobs).toHaveBeenLastCalledWith('p1', null);

    hook.rerender(inputs({ active: true }));
    expect(mocks.jobs).toHaveBeenLastCalledWith('p1', 'r1');

    hook.rerender(inputs({ active: false }));
    expect(mocks.jobs).toHaveBeenLastCalledWith('p1', 'r1');
  });

  it('?tab=cad открывает вкладку CAD в хранилище', () => {
    mount({ tabParam: 'cad' });
    expect(useWorkspaceStore.getState().leftTab).toBe('cad');
  });

  it('другое значение tab вкладку не меняет', () => {
    mount({ tabParam: 'takeoff' });
    expect(useWorkspaceStore.getState().leftTab).toBe('documents');
  });
});

describe('useWorkspaceCad: состояния листа', () => {
  it('нет заданий - «не преобразовывался», ссылка на ревизию', () => {
    const { result } = mount();
    expect(result.current.panel.state).toBe('none');
    expect(result.current.panel.cadHref).toBe('/projects/p1/cad?revision=r1');
    expect(result.current.painter).toBeNull();
  });

  it('лист не выбран', () => {
    expect(mount({ sheet: null }).result.current.panel.state).toBe('no-sheet');
  });

  it('идёт задание - running, ссылка на задание', () => {
    mocks.jobsData.current = { items: [summary({ status: 'running', result_status: null })] };
    const { result } = mount();
    expect(result.current.panel.state).toBe('running');
    expect(result.current.panel.cadHref).toBe(`/projects/p1/cad?revision=r1&job=${JOB_ID}`);
  });

  it('отказ - failed', () => {
    mocks.jobsData.current = { items: [summary({ status: 'failed', result_status: null })] };
    expect(mount().result.current.panel.state).toBe('failed');
  });

  it('распознан: вид по умолчанию - первый, ссылка с листом и видом, слой DXF собран', () => {
    mocks.jobsData.current = { items: [summary()] };
    mocks.jobData.current = detail;
    const { result } = mount();
    const { panel } = result.current;
    expect(panel.state).toBe('recognized');
    expect(panel.recognized?.views).toEqual([1, 2]);
    expect(panel.recognized?.view).toBe(1);
    expect(panel.recognized?.overlayAvailable).toBe(true);
    expect(panel.cadHref).toBe(`/projects/p1/cad?revision=r1&job=${JOB_ID}&page=0&view=1`);
    expect(result.current.painter).not.toBeNull();
    // замечания читаются у показанного вида
    expect(mocks.remarks.mock.calls.at(-1)?.[1]).toBe(true);
  });

  it('выбор другого вида меняет вид и ссылку', () => {
    mocks.jobsData.current = { items: [summary()] };
    mocks.jobData.current = detail;
    const { result } = mount();
    act(() => result.current.panel.recognized?.onViewChange(2));
    expect(result.current.panel.recognized?.view).toBe(2);
    expect(result.current.panel.cadHref).toContain('&view=2');
    expect(mocks.view.mock.calls.at(-1)?.[0]).toMatchObject({ view: 2, attempt: 1, pageIndex: 0 });
  });

  it('переключатель выключает DXF; он живёт в хранилище и держится при закрытой вкладке', () => {
    mocks.jobsData.current = { items: [summary()] };
    mocks.jobData.current = detail;
    const { result } = mount();
    act(() => result.current.panel.recognized?.onOverlayChange(false));
    expect(useWorkspaceStore.getState().cadOverlay).toBe(false);
    expect(result.current.painter).toBeNull();

    act(() => useWorkspaceStore.getState().setCadOverlay(true));
    expect(result.current.painter).not.toBeNull();
  });

  it('вкладка закрыта после открытия: DXF остаётся, рамок замечаний нет', () => {
    mocks.jobsData.current = { items: [summary()] };
    mocks.jobData.current = detail;
    const hook = mount();
    hook.rerender(inputs({ active: false }));
    expect(hook.result.current.painter).not.toBeNull();
    expect(hook.result.current.capture).toBeNull();
  });
});

describe('useWorkspaceCad: отметка участка', () => {
  const recognizedMount = () => {
    mocks.jobsData.current = { items: [summary()] };
    mocks.jobData.current = detail;
    return mount();
  };

  it('захват включается кнопкой, Esc отменяет', () => {
    const { result } = recognizedMount();
    expect(result.current.capture).toBeNull();

    act(() => result.current.panel.recognized?.remarks?.onMarkingChange(true));
    expect(result.current.capture).not.toBeNull();
    expect(result.current.capture?.camera).toBe(camera);
    expect(result.current.capture?.page).toEqual({ width: 842, height: 595 });

    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(result.current.capture).toBeNull();
  });

  it('нарисованный участок становится черновиком, а режим гаснет', () => {
    const { result } = recognizedMount();
    act(() => result.current.panel.recognized?.remarks?.onMarkingChange(true));
    act(() => result.current.capture?.onDrawn([10, 20, 110, 220]));
    expect(result.current.capture).toBeNull();
    expect(result.current.panel.recognized?.remarks?.draft).toEqual([10, 20, 110, 220]);
    // черновик рисуется на листе
    expect(result.current.painter).not.toBeNull();
  });

  it('размер листа неизвестен - отметка недоступна', () => {
    const { result } = mount({ page: null });
    expect(result.current.capture).toBeNull();
  });

  it('смена вида сбрасывает черновик и режим отметки', () => {
    const { result } = recognizedMount();
    act(() => result.current.panel.recognized?.remarks?.onMarkingChange(true));
    act(() => result.current.capture?.onDrawn([10, 20, 110, 220]));
    act(() => result.current.panel.recognized?.onViewChange(2));
    expect(result.current.panel.recognized?.remarks?.draft).toBeNull();
  });
});
