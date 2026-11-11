import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type * as ApiClient from '@quantor/api-client';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { construction, constructionsRead } from '@/lib/cad/constructions-fixtures';
import { coverage, vorDocument } from '@/lib/cad/vor-fixtures';
import { resetStoredNumbers } from '@/lib/cad/useStoredNumber';
import { Camera } from '@/lib/viewer/camera';

const mocks = vi.hoisted(() => ({
  read: vi.fn(),
  bulk: vi.fn(),
  put: vi.fn(),
  recompute: vi.fn(),
  levels: vi.fn(),
  vorDocs: vi.fn(),
  vorCoverage: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readCadConstructions: mocks.read,
  bulkCadConstructionProps: mocks.bulk,
  putCadConstructionProps: mocks.put,
  recomputeCadWalls: mocks.recompute,
  putCadSheetLevels: mocks.levels,
  listCadVorDocuments: mocks.vorDocs,
  readCadVorCoverage: mocks.vorCoverage,
}));

import { useWorkspaceCadConstructions } from './useWorkspaceCadConstructions';

const PARAMS = { projectId: 'p1', revisionId: 'r1', jobId: 'j1', attempt: 1, pageIndex: 0, view: 1 };
const FRAME = { originX: 100, originY: 500, mmPerPt: 10 };
const PAGE = { width: 1000, height: 1000 };

const A = construction({ id: 'a' });
const B = construction({ id: 'b' });
const OTHER = construction({
  id: 'o',
  thickness_nominal_mm: 200,
  computed: { ...A.computed, thickness_mm: 200 },
});
const DATA = constructionsRead({ constructions: [A, B, OTHER] });

const camera = new Camera();

const wrapper = ({ children }: { children: ReactNode }) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

type Input = Parameters<typeof useWorkspaceCadConstructions>[0];
const input = (patch: Partial<Input> = {}): Input => ({
  params: PARAMS,
  frame: FRAME,
  pageSize: PAGE,
  camera,
  load: true,
  active: true,
  blocked: false,
  ...patch,
});

const mount = (patch: Partial<Input> = {}) =>
  renderHook((props: Input) => useWorkspaceCadConstructions(props), {
    wrapper,
    initialProps: input(patch),
  });

describe('useWorkspaceCadConstructions', () => {
  beforeEach(() => {
    resetStoredNumbers();
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.read.mockResolvedValue({ data: DATA });
    mocks.vorDocs.mockResolvedValue({ data: [] });
    mocks.vorCoverage.mockResolvedValue({ data: coverage({ has_vor: false, not_in_vor_keys: ['a'] }) });
  });

  it('данные листа: слой, выбор и свод', async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.side?.status).toBe('ready'));
    expect(result.current.paintData?.shapes.map((shape) => shape.id)).toEqual(['a', 'b', 'o']);
    expect(result.current.picker).not.toBeNull();
    expect(result.current.paintData?.showAll).toBe(false);
    expect(result.current.layers?.visible).toBe(false);
    expect(mocks.read.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1', job_id: 'j1', page_index: 0, view: 1 },
    });
  });

  it('ВОР не загружен: «не в ВОР» не рисуется, блок ВОР без документа', async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.side?.vor?.coverage).toBeTruthy());
    expect(result.current.side?.vor?.document).toBeNull();
    expect(result.current.paintData?.notInVor).toBeUndefined();
  });

  it('ВОР загружен: в подсветку идут not_in_vor_keys, переключатель выключает её', async () => {
    mocks.vorDocs.mockResolvedValue({ data: [vorDocument()] });
    mocks.vorCoverage.mockResolvedValue({ data: coverage({ not_in_vor_keys: ['a', 'b'] }) });
    const { result } = mount();
    await waitFor(() => expect([...(result.current.paintData?.notInVor ?? [])]).toEqual(['a', 'b']));
    expect(result.current.side?.vor?.document?.file_name).toBe('ВОР.xlsx');
    act(() => result.current.side?.vor?.onShowNotInVorChange(false));
    await waitFor(() => expect(result.current.paintData?.notInVor).toBeUndefined());
  });

  it('«применить ко всем»: ключи - все конструкции того же вида и номинала на листе', async () => {
    mocks.bulk.mockResolvedValue({ data: { changed: 2 } });
    const { result } = mount();
    await waitFor(() => expect(result.current.picker).not.toBeNull());
    act(() => result.current.picker?.onPick('a', { x: 10, y: 20 }));
    expect(result.current.picker?.popover?.groupCount).toBe(2);
    expect(result.current.picker?.popover?.anchor).toEqual({ x: 10, y: 20 });
    act(() => result.current.picker?.popover?.onBulk({ purpose: 'interior' }));
    await waitFor(() => expect(mocks.bulk).toHaveBeenCalled());
    expect(mocks.bulk.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1', job_id: 'j1', page_index: 0, view: 1 },
      body: { keys: ['a', 'b'], props_patch: { purpose: 'interior' } },
    });
  });

  it('сохранение и принятие идут в PUT props с ключом конструкции', async () => {
    mocks.put.mockResolvedValue({ data: A });
    const { result } = mount();
    await waitFor(() => expect(result.current.picker).not.toBeNull());
    act(() => result.current.picker?.onPick('a', { x: 0, y: 0 }));
    act(() => result.current.picker?.popover?.onSave({ material: 'aerated_concrete' }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    expect(mocks.put.mock.calls[0]?.[0]).toMatchObject({
      path: { construction_key: 'a' },
      body: { props: { material: 'aerated_concrete' } },
    });
    act(() => result.current.picker?.popover?.onAccept(true));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(2));
    expect(mocks.put.mock.calls[1]?.[0]).toMatchObject({ body: { props: {}, accepted: true } });
  });

  it('клик по пустому месту снимает выделение, закрытие карточки выделение оставляет', async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.picker).not.toBeNull());
    act(() => result.current.picker?.onPick('a', { x: 0, y: 0 }));
    expect([...(result.current.paintData?.selected ?? [])]).toEqual(['a']);
    act(() => result.current.picker?.onDismiss());
    expect(result.current.picker?.popover).toBeNull();
    expect([...(result.current.paintData?.selected ?? [])]).toEqual(['a']);
    act(() => result.current.picker?.onPick(null, { x: 0, y: 0 }));
    expect(result.current.paintData?.selected.size).toBe(0);
  });

  it('строка свода выделяет набор, повторный выбор той же строки снимает его', async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.side?.status).toBe('ready'));
    act(() => result.current.side?.onSelectGroup('masonry|120|', ['a', 'b']));
    expect([...(result.current.paintData?.selected ?? [])]).toEqual(['a', 'b']);
    expect(result.current.side?.activeGroup).toBe('masonry|120|');
    act(() => result.current.side?.onSelectGroup('masonry|120|', ['a', 'b']));
    expect(result.current.paintData?.selected.size).toBe(0);
    expect(result.current.side?.activeGroup).toBeNull();
  });

  it('галка слоя меняет только полный показ: выбор и данные отрисовки остаются', async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.picker).not.toBeNull());
    expect(result.current.paintData?.showAll).toBe(false);
    act(() => result.current.layers?.onVisibleChange(true));
    expect(result.current.paintData?.showAll).toBe(true);
    expect(result.current.picker).not.toBeNull();
    act(() => result.current.layers?.onVisibleChange(false));
    expect(result.current.paintData?.showAll).toBe(false);
    expect(result.current.picker).not.toBeNull();
  });

  it('выбор группы из свода попадает в selected при выключенном полном показе', async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.side?.status).toBe('ready'));
    act(() => result.current.side?.onSelectGroup('g', ['a', 'b']));
    expect(result.current.paintData?.showAll).toBe(false);
    expect([...(result.current.paintData?.selected ?? [])]).toEqual(['a', 'b']);
  });

  it('вкладка закрыта или идёт другое рисование: нет ни слоя, ни выбора', async () => {
    const { result, rerender } = mount();
    await waitFor(() => expect(result.current.picker).not.toBeNull());
    rerender(input({ blocked: true }));
    expect(result.current.picker).toBeNull();
    expect(result.current.paintData).not.toBeNull();
    rerender(input({ active: false }));
    expect(result.current.paintData).toBeNull();
  });

  it('без вида или до открытия вкладки запросов нет', () => {
    mount({ params: null });
    mount({ load: false });
    expect(mocks.read).not.toHaveBeenCalled();
  });
});

describe('useWorkspaceCadConstructions: нет результата и пересчёт', () => {
  beforeEach(() => {
    resetStoredNumbers();
    for (const mock of Object.values(mocks)) mock.mockReset();
  });

  const notReady = (issue: Record<string, string> | null) =>
    mocks.read.mockRejectedValue({ detail: { code: 'CAD_WALLS_NOT_READY', issue } });

  it('не считалось: 404 без задания - подсказка и кнопка', async () => {
    notReady(null);
    const { result } = mount();
    await waitFor(() => expect(result.current.side?.status).toBe('not-ready'));
    expect(result.current.side?.notReadyText).toBe('Конструкции этого листа ещё не считались.');
    expect(result.current.side?.calculating).toBe(false);
    expect(result.current.layers).toBeNull();
    expect(result.current.paintData).toBeNull();
  });

  it('задание упало - текст про ошибку; идёт - считается', async () => {
    notReady({ job_status: 'failed' });
    const failed = mount();
    await waitFor(() => expect(failed.result.current.side?.status).toBe('not-ready'));
    expect(failed.result.current.side?.notReadyText).toMatch(/не удался/);
    expect(failed.result.current.side?.calculating).toBe(false);

    notReady({ job_status: 'running' });
    const running = mount();
    await waitFor(() => expect(running.result.current.side?.status).toBe('not-ready'));
    expect(running.result.current.side?.calculating).toBe(true);
    expect(running.result.current.side?.notReadyText).toMatch(/считаются/);
  });

  const latest = (status: 'queued' | 'running' | 'succeeded' | 'failed', extra = {}) =>
    constructionsRead({
      constructions: [construction({ id: 'a' })],
      latest_walls_job: {
        id: 'w2',
        status,
        error_code: null,
        error_message: null,
        created_at: '2026-11-11T10:00:00Z',
        ...extra,
      },
    });

  it('поверх готового результата идёт пересчёт: данные на месте, считается, опрос раз в 5 с', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mocks.vorDocs.mockResolvedValue({ data: [] });
      mocks.vorCoverage.mockResolvedValue({ data: coverage({ has_vor: false }) });
      mocks.read.mockResolvedValue({ data: latest('running') });
      const { result } = mount();
      await waitFor(() => expect(result.current.side?.status).toBe('ready'));
      expect(result.current.side?.calculating).toBe(true);
      expect(result.current.side?.recomputeFailure).toBeNull();
      const before = mocks.read.mock.calls.length;
      mocks.read.mockResolvedValue({ data: latest('failed', { error_message: 'скрипт упал' }) });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5100);
      });
      await waitFor(() => expect(mocks.read.mock.calls.length).toBeGreaterThan(before));
      await waitFor(() => expect(result.current.side?.recomputeFailure).toBe('скрипт упал'));
      expect(result.current.side?.calculating).toBe(false);
      expect(result.current.side?.status).toBe('ready');
      // Упавшее задание не опрашивается дальше.
      const after = mocks.read.mock.calls.length;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(11000);
      });
      expect(mocks.read.mock.calls.length).toBe(after);
    } finally {
      vi.useRealTimers();
    }
  });

  it('«Посчитать»: POST /walls, затем состояние «считается»', async () => {
    notReady(null);
    mocks.recompute.mockResolvedValue({ data: { job_id: 'w9' } });
    const { result } = mount();
    await waitFor(() => expect(result.current.side?.status).toBe('not-ready'));
    // После постановки сервер уже знает о задании: следующее чтение отдаёт его статус.
    notReady({ job_status: 'queued' });
    act(() => result.current.side?.onCompute());
    await waitFor(() => expect(mocks.recompute).toHaveBeenCalled());
    expect(mocks.recompute.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1', job_id: 'j1', page_index: 0, view: 1 },
    });
    await waitFor(() => expect(result.current.side?.calculating).toBe(true));
  });

  it('409 CAD_WALLS_BUSY: «уже считается» вместо отказа', async () => {
    notReady(null);
    mocks.recompute.mockRejectedValue({ detail: { code: 'CAD_WALLS_BUSY' } });
    const { result } = mount();
    await waitFor(() => expect(result.current.side?.status).toBe('not-ready'));
    act(() => result.current.side?.onCompute());
    await waitFor(() => expect(result.current.side?.actionError).toMatch(/уже считаются/));
  });

  it('высоты листа уходят в PUT /levels', async () => {
    mocks.read.mockResolvedValue({ data: DATA });
    mocks.levels.mockResolvedValue({ data: DATA });
    const { result } = mount();
    await waitFor(() => expect(result.current.side?.status).toBe('ready'));
    act(() => result.current.side?.onSaveLevels({ floor_height_mm: 3200 }));
    await waitFor(() => expect(mocks.levels).toHaveBeenCalled());
    expect(mocks.levels.mock.calls[0]?.[0]).toMatchObject({ body: { floor_height_mm: 3200 } });
  });
});
