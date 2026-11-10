import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { diagnostics, FRAME_NO, JOB_ID, preview } from '@/components/cad/viewer/fixtures';
import type * as ViewQueries from '@/lib/cad/view-queries';
import { resetStoredNumbers } from '@/lib/cad/useStoredNumber';
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
  diagnosticsPatch: { current: {} as Parameters<typeof diagnostics>[0] },
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
    return {
      isError: false,
      data: args[1] === true ? diagnostics(mocks.diagnosticsPatch.current) : undefined,
    };
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

const OTHER_JOB = '99999999-9999-4999-8999-999999999999';

const camera = new Camera();
const navigate = vi.fn();

type Inputs = Parameters<typeof useWorkspaceCad>[0];

const inputs = (patch: Partial<Inputs> = {}): Inputs => ({
  projectId: 'p1',
  revisionId: 'r1',
  sheets: [{ page_index: 0 }, { page_index: 1 }, { page_index: 2 }],
  sheet: { page_index: 0, page_label: '1' },
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

const recognized = () => {
  mocks.jobsData.current = { items: [summary()] };
  mocks.jobData.current = detail;
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  resetStoredNumbers();
  mocks.jobsData.current = { items: [], server_time: '' };
  mocks.jobData.current = undefined;
  mocks.diagnosticsPatch.current = {};
  useWorkspaceStore.setState({ leftTab: 'documents', cadMode: 'overlay' });
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
    expect(hook.result.current.opened).toBe(false);

    hook.rerender(inputs({ active: true }));
    expect(mocks.jobs).toHaveBeenLastCalledWith('p1', 'r1');

    hook.rerender(inputs({ active: false }));
    expect(mocks.jobs).toHaveBeenLastCalledWith('p1', 'r1');
    expect(hook.result.current.opened).toBe(true);
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
  it('нет заданий: «не преобразовывался», строки над холстом и слоя нет', () => {
    const { result } = mount();
    expect(result.current.side.state).toBe('none');
    expect(result.current.side.job).toBeNull();
    expect(result.current.bar).toBeNull();
    expect(result.current.painter).toBeNull();
    expect(result.current.pageOpacity).toBe(1);
  });

  it('лист не выбран', () => {
    expect(mount({ sheet: null }).result.current.side.state).toBe('no-sheet');
  });

  it.each([
    ['идёт задание', { status: 'running', result_status: null }],
    ['отказ', { status: 'failed', result_status: null }],
  ])('%s: у листа есть задание, но диагностики вида нет', (_, patch) => {
    mocks.jobsData.current = { items: [summary(patch)] };
    mocks.jobData.current = { ...detail, result_attempt: null, result_status: null };
    const { result } = mount();
    expect(result.current.side.state).toBe('ready');
    expect(result.current.side.job?.jobId).toBe(JOB_ID);
    expect(result.current.side.view).toBeNull();
    expect(result.current.bar).toBeNull();
  });

  it('распознан: вид по умолчанию первый, слой DXF собран, строка над холстом есть', () => {
    recognized();
    const { result } = mount();
    expect(result.current.side.state).toBe('ready');
    expect(result.current.side.job).toMatchObject({ jobId: JOB_ID, page: 0, view: 1 });
    expect(result.current.bar?.views).toEqual([1, 2]);
    expect(result.current.bar?.view).toBe(1);
    expect(result.current.bar?.mode).toBe('overlay');
    expect(result.current.bar?.dxfAvailable).toBe(true);
    expect(result.current.side.view?.layers.layers).toEqual(['WALLS', 'DOORS']);
    expect(result.current.painter).not.toBeNull();
    // замечания читаются у показанного вида
    expect(mocks.remarks.mock.calls.at(-1)?.[1]).toBe(true);
  });

  it('строка над холстом только на вкладке CAD', () => {
    recognized();
    const { result } = mount({ active: false });
    expect(result.current.bar).toBeNull();
  });
});

describe('useWorkspaceCad: задание и вид в адресе', () => {
  it('явное задание, закрывающее лист, показывается вместо последнего', () => {
    mocks.jobsData.current = {
      items: [
        summary(),
        summary({ job_id: OTHER_JOB, created_at: '2026-11-09T10:00:00Z', requested_pages: [0, 1] }),
      ],
    };
    mocks.jobData.current = detail;
    const { result } = mount({ jobParam: OTHER_JOB });
    expect(result.current.side.job?.jobId).toBe(OTHER_JOB);
  });

  it('задание из адреса, не закрывающее лист, отбрасывается: берётся последнее по листу', () => {
    mocks.jobsData.current = {
      items: [summary(), summary({ job_id: OTHER_JOB, requested_pages: [5] })],
    };
    mocks.jobData.current = detail;
    expect(mount({ jobParam: OTHER_JOB }).result.current.side.job?.jobId).toBe(JOB_ID);
  });

  it('неизвестное задание из адреса отбрасывается', () => {
    recognized();
    expect(mount({ jobParam: OTHER_JOB }).result.current.side.job?.jobId).toBe(JOB_ID);
  });

  it('вид из адреса берётся вместе с явным заданием; у листа нет такого вида - первый', () => {
    recognized();
    const withView = mount({ jobParam: JOB_ID, viewParam: 2 });
    expect(withView.result.current.bar?.view).toBe(2);
    expect(mocks.view.mock.calls.at(-1)?.[0]).toMatchObject({ view: 2, attempt: 1, pageIndex: 0 });
    expect(mount({ jobParam: JOB_ID, viewParam: 9 }).result.current.bar?.view).toBe(1);
  });

  it('вид без явного задания игнорируется', () => {
    recognized();
    expect(mount({ viewParam: 2 }).result.current.bar?.view).toBe(1);
  });

  it('переключение вида пишет задание и вид в адрес', () => {
    recognized();
    const { result } = mount();
    act(() => result.current.bar?.onViewChange(2));
    expect(navigate).toHaveBeenCalledWith({ job: JOB_ID, view: '2' });
  });
});

describe('useWorkspaceCad: переходы', () => {
  it('клик по листу переводит рабочую область на его позицию и сбрасывает задание и вид', () => {
    const { result } = mount();
    act(() => result.current.left?.onOpenSheet(2));
    expect(navigate).toHaveBeenCalledWith({ page: '3', region: null, job: null, view: null });
  });

  it('листа нет в ревизии - адрес не меняется', () => {
    const { result } = mount();
    act(() => result.current.left?.onOpenSheet(77));
    expect(navigate).not.toHaveBeenCalled();
  });

  it('выбор задания, закрывающего лист: только задание в адресе', () => {
    mocks.jobsData.current = { items: [summary({ requested_pages: [0, 1] })] };
    const { result } = mount();
    act(() => result.current.left?.onSelectJob(JOB_ID));
    expect(navigate).toHaveBeenCalledWith({ job: JOB_ID, view: null });
  });

  it('выбор задания другого листа переводит рабочую область на первый его лист', () => {
    mocks.jobsData.current = { items: [summary({ requested_pages: [2, 1] })] };
    const { result } = mount();
    act(() => result.current.left?.onSelectJob(JOB_ID));
    expect(navigate).toHaveBeenCalledWith({ page: '2', region: null, job: JOB_ID, view: null });
  });

  it('созданное задание открывается на своём листе', () => {
    const { result } = mount();
    act(() => result.current.left?.onJobCreated(OTHER_JOB, [1]));
    expect(navigate).toHaveBeenCalledWith({ page: '2', region: null, job: OTHER_JOB, view: null });
  });

  it('другой PDF проекта открывает его ревизию с первого листа', () => {
    const { result } = mount();
    act(() => result.current.left?.onSourceSelect('r2'));
    expect(navigate).toHaveBeenCalledWith({
      revision: 'r2',
      page: '1',
      region: null,
      job: null,
      view: null,
    });
  });

  it('выбор вида в ходе задания: лист, задание и вид в адресе', () => {
    recognized();
    const { result } = mount();
    act(() => result.current.side.job?.onSelectView(1, 3));
    expect(navigate).toHaveBeenCalledWith({
      page: '2',
      region: null,
      job: JOB_ID,
      view: '3',
    });
  });

  it('ревизии нет - левой панели нет', () => {
    expect(mount({ revisionId: null }).result.current.left).toBeNull();
  });
});

describe('useWorkspaceCad: режимы PDF / CAD / Наложение и непрозрачность PDF', () => {
  it('наложение: PDF с непрозрачностью ползунка (40 % по умолчанию), DXF рисуется', () => {
    recognized();
    const { result } = mount();
    expect(result.current.pageOpacity).toBe(0.4);
    expect(result.current.painter).not.toBeNull();
    expect(result.current.side.view?.layers.pdfOpacity).toBe(0.4);
    expect(result.current.side.view?.layers.pdfOpacityActive).toBe(true);
  });

  it('CAD: PDF скрыт, ползунок не тронут, DXF рисуется', () => {
    recognized();
    const { result } = mount();
    act(() => result.current.bar?.onModeChange('cad'));
    expect(useWorkspaceStore.getState().cadMode).toBe('cad');
    expect(result.current.bar?.mode).toBe('cad');
    expect(result.current.pageOpacity).toBe(0);
    expect(result.current.side.view?.layers.pdfOpacity).toBe(0.4);
    expect(result.current.side.view?.layers.pdfOpacityActive).toBe(false);
    expect(result.current.painter).not.toBeNull();
  });

  it('PDF: подложка целиком, DXF скрыт', () => {
    recognized();
    const { result } = mount();
    act(() => result.current.bar?.onModeChange('pdf'));
    expect(result.current.pageOpacity).toBe(1);
    expect(result.current.painter).toBeNull();
    expect(result.current.side.view?.layers.cadShown).toBe(false);
  });

  it('ползунок меняет прозрачность PDF и хранится в localStorage', () => {
    recognized();
    const { result } = mount();
    act(() => result.current.side.view?.layers.onPdfOpacityChange(0.7));
    expect(result.current.pageOpacity).toBe(0.7);
    expect(window.localStorage.getItem('quantor.cad.pdf-opacity')).toBe('0.7');
    // вне допустимого отрезка значение зажимается
    act(() => result.current.side.view?.layers.onPdfOpacityChange(0));
    expect(result.current.pageOpacity).toBe(0.1);
  });

  it('сохранённое значение читается при открытии', () => {
    window.localStorage.setItem('quantor.cad.pdf-opacity', '0.25');
    recognized();
    expect(mount().result.current.pageOpacity).toBe(0.25);
  });

  it('вне вкладки CAD подложка целиком, а DXF остаётся', () => {
    recognized();
    const hook = mount();
    hook.rerender(inputs({ active: false }));
    expect(hook.result.current.pageOpacity).toBe(1);
    expect(hook.result.current.painter).not.toBeNull();
  });

  it('кадр координат не подтверждён: DXF не накладывается, режимы CAD и наложение закрыты', () => {
    mocks.diagnosticsPatch.current = { frame: FRAME_NO };
    recognized();
    const { result } = mount();
    expect(result.current.bar?.dxfAvailable).toBe(false);
    expect(result.current.bar?.dxfReason).toContain('Кадр координат не подтверждён');
    expect(result.current.bar?.mode).toBe('pdf');
    expect(result.current.pageOpacity).toBe(1);
    expect(result.current.painter).toBeNull();
  });

  it('режим живёт в хранилище и переживает смену листа', () => {
    recognized();
    const hook = mount();
    act(() => hook.result.current.bar?.onModeChange('cad'));
    hook.rerender(inputs({ sheet: { page_index: 1, page_label: '2' } }));
    expect(useWorkspaceStore.getState().cadMode).toBe('cad');
  });
});

describe('useWorkspaceCad: слои и область проверки масштаба', () => {
  it('слой выключается и включается', () => {
    recognized();
    const { result } = mount();
    expect([...(result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([0, 1]);
    act(() => result.current.side.view?.layers.onToggleLayer(1));
    expect([...(result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([0]);
    act(() => result.current.side.view?.layers.onToggleLayer(1));
    expect([...(result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([0, 1]);
  });

  it('выбор слоёв принадлежит виду: на другом виде все слои снова видны', () => {
    recognized();
    const hook = mount({ jobParam: JOB_ID, viewParam: 1 });
    act(() => hook.result.current.side.view?.layers.onToggleLayer(0));
    expect([...(hook.result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([1]);
    hook.rerender(inputs({ jobParam: JOB_ID, viewParam: 2 }));
    expect([...(hook.result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([0, 1]);
  });

  it('область проверки масштаба: доступна в PDF и наложении, в CAD нет; рисуется и без DXF', () => {
    recognized();
    const { result } = mount();
    expect(result.current.side.view?.layers.cropAvailable).toBe(true);

    act(() => result.current.bar?.onModeChange('pdf'));
    expect(result.current.painter).toBeNull();
    act(() => result.current.side.view?.layers.onCropChange(true));
    // DXF скрыт, но рамка области на PDF нарисована
    expect(result.current.painter).not.toBeNull();

    act(() => result.current.bar?.onModeChange('cad'));
    expect(result.current.side.view?.layers.cropAvailable).toBe(false);
  });
});

describe('useWorkspaceCad: отметка участка', () => {
  it('захват включается кнопкой, Esc отменяет', () => {
    recognized();
    const { result } = mount();
    expect(result.current.capture).toBeNull();

    act(() => result.current.side.view?.remarks?.onMarkingChange(true));
    expect(result.current.capture).not.toBeNull();
    expect(result.current.capture?.camera).toBe(camera);
    expect(result.current.capture?.page).toEqual({ width: 842, height: 595 });

    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(result.current.capture).toBeNull();
  });

  it('нарисованный участок становится черновиком, а режим гаснет', () => {
    recognized();
    const { result } = mount();
    act(() => result.current.side.view?.remarks?.onMarkingChange(true));
    act(() => result.current.capture?.onDrawn([10, 20, 110, 220]));
    expect(result.current.capture).toBeNull();
    expect(result.current.side.view?.remarks?.draft).toEqual([10, 20, 110, 220]);
    expect(result.current.painter).not.toBeNull();
  });

  it('в режиме CAD (PDF скрыт) отметка по-прежнему возможна: координаты те же', () => {
    recognized();
    const { result } = mount();
    act(() => result.current.bar?.onModeChange('cad'));
    act(() => result.current.side.view?.remarks?.onMarkingChange(true));
    expect(result.current.capture).not.toBeNull();
  });

  it('размер листа неизвестен - отметка недоступна', () => {
    recognized();
    const { result } = mount({ page: null });
    expect(result.current.capture).toBeNull();
    expect(result.current.side.view?.remarks?.markDisabledReason).toContain('загрузится страница');
  });

  it('смена вида сбрасывает черновик и режим отметки', () => {
    recognized();
    const hook = mount({ jobParam: JOB_ID, viewParam: 1 });
    act(() => hook.result.current.side.view?.remarks?.onMarkingChange(true));
    act(() => hook.result.current.capture?.onDrawn([10, 20, 110, 220]));
    hook.rerender(inputs({ jobParam: JOB_ID, viewParam: 2 }));
    expect(hook.result.current.side.view?.remarks?.draft).toBeNull();
  });

  it('закрытая вкладка гасит режим отметки и убирает рамки', () => {
    recognized();
    const hook = mount();
    act(() => hook.result.current.side.view?.remarks?.onMarkingChange(true));
    hook.rerender(inputs({ active: false }));
    expect(hook.result.current.capture).toBeNull();
  });
});
