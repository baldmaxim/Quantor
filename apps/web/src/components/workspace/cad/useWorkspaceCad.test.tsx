import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { diagnostics, FRAME_NO, JOB_ID, preview } from '@/components/cad/viewer/fixtures';
import type * as ConstructionQueries from '@/lib/cad/constructions-queries';
import type * as VorQueries from '@/lib/cad/vor-queries';
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
vi.mock('@/lib/cad/finishes-queries', () => ({
  useCadFinishTemplates: () => ({ data: undefined }),
  useAssignCadFinishTemplate: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));
vi.mock('@/lib/cad/constructions-queries', async (importOriginal) => ({
  ...(await importOriginal<typeof ConstructionQueries>()),
  useCadConstructions: () => ({
    data: undefined,
    isPending: false,
    isError: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
  }),
  useRecomputeCadWalls: () => ({ mutate: vi.fn(), isPending: false }),
  useSaveConstructionProps: () => ({ mutate: vi.fn(), isPending: false }),
  useBulkConstructionProps: () => ({ mutate: vi.fn(), isPending: false }),
  useSaveSheetLevels: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock('@/lib/cad/vor-queries', async (importOriginal) => ({
  ...(await importOriginal<typeof VorQueries>()),
  useCadVorDocuments: () => ({ data: undefined, isPending: false, isError: false, error: null }),
  useCadVorCoverage: () => ({ data: undefined, isPending: false, isError: false, error: null }),
  useCadVorSources: () => ({ sources: [], loading: false, error: null }),
  useImportCadVorFromRevision: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  }),
  useDeleteCadVor: () => ({ mutate: vi.fn(), isPending: false, isError: false, error: null }),
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
  useWorkspaceStore.setState({ leftTab: 'documents', mode: 'sheets', tool: 'pointer' });
});

describe('useWorkspaceCad: запросы', () => {
  it('без флага cad.export ни одного запроса CAD не уходит', () => {
    mount({ enabled: false });
    expect(mocks.jobs).toHaveBeenCalledWith('p1', null);
    expect(mocks.job).toHaveBeenCalledWith('p1', null, null);
  });

  it('режим «Листы»: задания и вид читаются сразу, без захода в CAD; открытие CAD их не перезапускает', () => {
    recognized();
    const hook = mount({ active: false });
    expect(mocks.jobs).toHaveBeenLastCalledWith('p1', 'r1');
    // Первый вызов - вид самого задания (второй - трассы, их тут нет).
    expect(mocks.view.mock.calls[0]?.[1]).toBe(true);
    expect(mocks.preview.mock.calls[0]?.[1]).toBe(true);
    expect(hook.result.current.opened).toBe(false);
    // Наложение DXF готово к рисованию и вне вкладки CAD.
    expect(hook.result.current.painter).not.toBeNull();

    hook.rerender(inputs({ active: true }));
    expect(mocks.jobs).toHaveBeenLastCalledWith('p1', 'r1');
    expect(hook.result.current.opened).toBe(true);

    hook.rerender(inputs({ active: false }));
    expect(mocks.jobs).toHaveBeenLastCalledWith('p1', 'r1');
    expect(hook.result.current.opened).toBe(true);
  });

  it('завершённое задание: диагностика и предпросмотр идут по сводке, не дожидаясь полного задания', () => {
    mocks.jobsData.current = { items: [summary({ attempt: 1 })] };
    mocks.jobData.current = undefined;
    mount();
    const params = {
      projectId: 'p1',
      revisionId: 'r1',
      jobId: JOB_ID,
      attempt: 1,
      pageIndex: 0,
      view: 1,
    };
    expect(mocks.view).toHaveBeenCalledWith(params, true, 'succeeded');
    expect(mocks.preview).toHaveBeenCalledWith(params, true);
  });

  it('идущее задание: по сводке ничего не читается', () => {
    mocks.jobsData.current = {
      items: [summary({ attempt: 1, status: 'running', result_status: null })],
    };
    mocks.jobData.current = undefined;
    mount();
    expect(mocks.view.mock.calls.every((call) => call[1] === false)).toBe(true);
    expect(mocks.preview.mock.calls.every((call) => call[1] === false)).toBe(true);
  });

  it('?tab=cad открывает вкладку CAD в хранилище', () => {
    mount({ tabParam: 'cad' });
    expect(useWorkspaceStore.getState().mode).toBe('cad');
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
    expect(result.current.side.job?.failed).toBe(patch.status === 'failed');
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
    expect(result.current.side.view?.layers.cadShown).toBe(true);
    expect(result.current.side.view?.layers.pdfOpacityActive).toBe(true);
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
    expect(mocks.view.mock.calls[0]?.[0]).toMatchObject({ view: 2, attempt: 1, pageIndex: 0 });
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

  it('лист вне переданного списка не теряется молча: адресуется по индексу страницы', () => {
    const { result } = mount();
    act(() => result.current.left?.onOpenSheet(77));
    expect(navigate).toHaveBeenCalledWith({ page: '78', region: null, job: null, view: null });
  });

  it('позиция листа берётся из списка, а не из индекса страницы', () => {
    const { result } = mount({ sheets: [{ page_index: 5 }, { page_index: 9 }] });
    act(() => result.current.left?.onOpenSheet(9));
    expect(navigate).toHaveBeenCalledWith({ page: '2', region: null, job: null, view: null });
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

  it('преобразование открытого листа: запуск на его страницу, калибровка включает «Масштаб», задание открывается', () => {
    const { result } = mount();
    const convert = result.current.side.convert;
    expect(convert).toMatchObject({
      projectId: 'p1',
      revisionId: 'r1',
      sheetId: 's0',
      pageIndex: 0,
    });
    act(() => convert?.onCalibrate());
    expect(useWorkspaceStore.getState().tool).toBe('scale');
    act(() => convert?.onJobCreated(OTHER_JOB, [0]));
    // лист тот же - в адресе только задание
    expect(navigate).toHaveBeenCalledWith({ job: OTHER_JOB, view: null });
  });

  it('созданное задание другого листа открывается на своём листе', () => {
    const { result } = mount();
    act(() => result.current.side.convert?.onJobCreated(OTHER_JOB, [1]));
    expect(navigate).toHaveBeenCalledWith({ page: '2', region: null, job: OTHER_JOB, view: null });
  });

  it('листа или ревизии нет - запуска нет', () => {
    expect(mount({ sheet: null }).result.current.side.convert).toBeNull();
    expect(mount({ revisionId: null }).result.current.side.convert).toBeNull();
  });

  it('у левой панели нет ни запуска, ни выбора исходного PDF', () => {
    const { result } = mount();
    expect(Object.keys(result.current.left ?? {}).sort()).toEqual([
      'activePage',
      'onOpenSheet',
      'onSelectJob',
      'projectId',
      'revisionId',
      'selectedJobId',
    ]);
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

describe('useWorkspaceCad: наложение и непрозрачность PDF', () => {
  it('наложение: PDF с непрозрачностью ползунка (40 % по умолчанию), DXF рисуется', () => {
    recognized();
    const { result } = mount();
    expect(result.current.pageOpacity).toBe(0.4);
    expect(result.current.painter).not.toBeNull();
    expect(result.current.side.view?.layers.pdfOpacity).toBe(0.4);
    expect(result.current.side.view?.layers.pdfOpacityActive).toBe(true);
  });

  it('в строке над холстом нет ни режима наложения, ни кнопок масштаба: «Вписать» и «План | 3D»', () => {
    recognized();
    const { result } = mount();
    expect(Object.keys(result.current.bar ?? {}).sort()).toEqual([
      'diagnostics',
      'floor3d',
      'loading',
      'notices',
      'onFit',
      'onViewChange',
      'view',
      'views',
    ]);
  });

  it('«3D»: режим запоминается, вид открывается с параметрами листа; «План» его закрывает', () => {
    recognized();
    const { result } = mount();
    expect(result.current.bar?.floor3d?.mode).toBe('plan');
    expect(result.current.floor3d).toBeNull();
    act(() => result.current.bar?.floor3d?.onModeChange('3d'));
    expect(result.current.bar?.floor3d?.mode).toBe('3d');
    expect(result.current.floor3d?.params).toEqual(
      expect.objectContaining({ pageIndex: expect.any(Number), view: expect.any(Number) }),
    );
    expect(window.localStorage.getItem('quantor.cad.view-3d')).toBe('1');
    act(() => result.current.bar?.floor3d?.onModeChange('plan'));
    expect(result.current.floor3d).toBeNull();
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

  it('кадр координат не подтверждён: DXF не накладывается, виден один PDF, причина в строке', () => {
    mocks.diagnosticsPatch.current = { frame: FRAME_NO };
    recognized();
    const { result } = mount();
    expect(result.current.bar?.notices.map((notice) => notice.text).join(' ')).toContain(
      'Кадр координат не подтверждён',
    );
    expect(result.current.side.view?.layers.cadShown).toBe(false);
    expect(result.current.side.view?.layers.pdfOpacityActive).toBe(false);
    expect(result.current.pageOpacity).toBe(1);
    expect(result.current.painter).toBeNull();
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

  it('группа слоёв скрывается и показывается одним вызовом', () => {
    recognized();
    const { result } = mount();
    act(() => result.current.side.view?.layers.onSetLayersHidden([0, 1], true));
    expect([...(result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([]);
    act(() => result.current.side.view?.layers.onSetLayersHidden([1], false));
    expect([...(result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([1]);
    act(() => result.current.side.view?.layers.onSetLayersHidden([0, 1], false));
    expect([...(result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([0, 1]);
  });

  it('выбор слоёв принадлежит листу задания: на другом виде того же листа сохраняется', () => {
    recognized();
    const hook = mount({ jobParam: JOB_ID, viewParam: 1 });
    act(() => hook.result.current.side.view?.layers.onToggleLayer(0));
    expect([...(hook.result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([1]);
    hook.rerender(inputs({ jobParam: JOB_ID, viewParam: 2 }));
    expect([...(hook.result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([1]);
  });

  it('скрытые слои хранятся по именам в localStorage и восстанавливаются', () => {
    recognized();
    const first = mount({ jobParam: JOB_ID, viewParam: 1 });
    act(() => first.result.current.side.view?.layers.onToggleLayer(0));
    const stored = Object.entries(window.localStorage).filter(([key]) =>
      key.startsWith('quantor.cad.layers-hidden.v1:'),
    );
    expect(stored).toHaveLength(1);
    first.unmount();
    const second = mount({ jobParam: JOB_ID, viewParam: 1 });
    expect([...(second.result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([1]);
  });

  it('режим 3D не сбрасывает выбор слоёв, строки «Плита» и «Перемычки» общие', () => {
    recognized();
    const { result } = mount({ jobParam: JOB_ID, viewParam: 1 });
    act(() => result.current.side.view?.layers.onToggleLayer(1));
    act(() => result.current.side.view?.layers.categories?.onChange('slab', false));
    expect(result.current.side.view?.layers.categories).toMatchObject({ slab: false, lintel: true });
    act(() => result.current.bar?.floor3d?.onModeChange('3d'));
    expect(result.current.side.view?.layers.mode3d).toBe(true);
    expect([...(result.current.side.view?.layers.visibleLayers ?? [])]).toEqual([0]);
    expect(result.current.floor3d?.link.hiddenCategories?.has('slab')).toBe(true);
  });

  it('область проверки масштаба: доступна, рисуется на PDF и без DXF', () => {
    mocks.diagnosticsPatch.current = { frame: FRAME_NO };
    recognized();
    const { result } = mount();
    expect(result.current.side.view?.layers.cropAvailable).toBe(true);
    // DXF не наложен, виден один PDF
    expect(result.current.painter).toBeNull();
    act(() => result.current.side.view?.layers.onCropChange(true));
    // рамка области на PDF нарисована
    expect(result.current.painter).not.toBeNull();
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
