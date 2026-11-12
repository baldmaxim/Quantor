import type { CadPipelineSheetRead, CadPipelineStageRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { FC, ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ run: vi.fn() }));

vi.mock('@/lib/cad/runPipelineAction', () => ({ runPipelineAction: mocks.run }));

import { BULK_CAD_CONCURRENCY, useBulkPipelineRun } from './useBulkPipelineRun';

const stage = (overrides: Partial<CadPipelineStageRead> = {}): CadPipelineStageRead => ({
  job_id: 'job-1',
  job_type: 'cad_pdf_convert',
  status: 'succeeded',
  progress: 1,
  stage: null,
  result_status: 'completed_requires_review',
  error_code: null,
  created_at: '2026-11-11T10:00:00Z',
  finished_at: '2026-11-11T10:01:00Z',
  ...overrides,
});

const fresh = (pageIndex: number): CadPipelineSheetRead => ({
  page_index: pageIndex,
  page_label: null,
  title: null,
  is_plan: true,
  scale_source: null,
  calibrated: false,
  convert: null,
  views: [],
});

/** Лист с готовым преобразованием и одним видом без других шагов. */
const converted = (pageIndex: number, walls: CadPipelineStageRead | null = null) => ({
  ...fresh(pageIndex),
  calibrated: true,
  convert: stage(),
  views: [
    {
      page: pageIndex,
      view: 1,
      has_dxf: true,
      walls,
      zones: null,
      zones_count: 0,
      approved: false,
      routes: null,
      routes_accepted: false,
      floor3d: null,
    },
  ],
});

interface IProps {
  readonly sheets: readonly CadPipelineSheetRead[];
  readonly at: number;
}

const setup = (initial: IProps) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper: FC<{ children: ReactNode }> = ({ children }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(
    ({ sheets, at }: IProps) => useBulkPipelineRun('p-1', 'rev-1', sheets, at, (page) => page + 1),
    { wrapper: Wrapper, initialProps: initial },
  );
};

const calls = () =>
  mocks.run.mock.calls.map(
    (call) => (call[0] as { action: { kind: string; pageIndex: number } }).action,
  );

describe('useBulkPipelineRun', () => {
  beforeEach(() => {
    mocks.run.mockReset();
    mocks.run.mockResolvedValue({ alreadyCurrent: false });
  });

  it('не больше трёх запросов одновременно, convert по листам партии', async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const releases: Array<() => void> = [];
    mocks.run.mockImplementation(
      () =>
        new Promise((resolve) => {
          inFlight += 1;
          maxInFlight = Math.max(maxInFlight, inFlight);
          releases.push(() => {
            inFlight -= 1;
            resolve({ alreadyCurrent: false });
          });
        }),
    );
    const sheets = [0, 1, 2, 3, 4].map(fresh);
    const { result, rerender } = setup({ sheets, at: 1 });

    act(() => result.current.start([0, 1, 2, 3, 4]));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(BULK_CAD_CONCURRENCY));
    expect(result.current.running).toBe(true);
    expect(result.current.total).toBe(5);
    expect(maxInFlight).toBe(BULK_CAD_CONCURRENCY);

    // Освобождаем запрос и отдаём конвейеру новые данные: освободившееся место занимает следующий лист.
    await act(async () => releases.shift()?.());
    rerender({
      sheets: [0, 1, 2, 3, 4].map((page) =>
        page === 0 ? converted(0, stage({ status: 'running' })) : fresh(page),
      ),
      at: 2,
    });
    await waitFor(() => expect(mocks.run.mock.calls.length).toBeGreaterThan(BULK_CAD_CONCURRENCY));
    expect(maxInFlight).toBe(BULK_CAD_CONCURRENCY);
    expect(calls().every((action) => action.kind === 'convert')).toBe(true);
  });

  it('идущий шаг ждётся, затем запускается следующий и лист завершается', async () => {
    const { result, rerender } = setup({ sheets: [fresh(0)], at: 1 });
    act(() => result.current.start([0]));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(1));
    expect(calls()[0]).toMatchObject({ kind: 'convert', pageIndex: 0 });

    // Данные не новее запуска или шаг идёт - новых запусков нет.
    rerender({ sheets: [{ ...fresh(0), convert: stage({ status: 'running' }) }], at: 2 });
    await act(async () => Promise.resolve());
    expect(mocks.run).toHaveBeenCalledTimes(1);
    expect(result.current.running).toBe(true);

    // Преобразование готово, конструкции не начаты - следующий шаг.
    rerender({ sheets: [converted(0)], at: 3 });
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(2));
    expect(calls()[1]).toMatchObject({ kind: 'walls' });

    // Конструкции готовы, зоны не начаты.
    rerender({
      sheets: [converted(0, stage({ job_type: 'cad_walls', result_status: 'walls_ready' }))],
      at: 4,
    });
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(3));
    expect(calls()[2]).toMatchObject({ kind: 'zones-auto' });
  });

  it('лист, ждущий человека, завершается без запуска', async () => {
    const wallsDone = stage({ job_type: 'cad_walls', result_status: 'walls_ready' });
    const zonesDone = stage({ job_type: 'cad_zones', result_status: 'zones_ready' });
    const base = converted(0, wallsDone);
    const review: CadPipelineSheetRead = {
      ...base,
      views: base.views.map((view) => ({ ...view, zones: zonesDone })),
    };
    const { result } = setup({ sheets: [review], at: 1 });
    act(() => result.current.start([0]));
    await waitFor(() => expect(result.current.running).toBe(false));
    expect(mocks.run).not.toHaveBeenCalled();
    expect(result.current.finished).toBe(1);
    expect(result.current.failures).toEqual([]);
  });

  it('отказ запроса: лист в ошибках, остальные продолжают', async () => {
    mocks.run.mockImplementation(({ action }: { action: { pageIndex: number } }) =>
      action.pageIndex === 1
        ? Promise.reject({ status: 409, code: 'CAD_CALIBRATION_REQUIRED', message: 'x' })
        : Promise.resolve({ alreadyCurrent: false }),
    );
    const { result } = setup({ sheets: [0, 1, 2].map(fresh), at: 1 });
    act(() => result.current.start([0, 1, 2]));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(result.current.failures).toHaveLength(1));
    expect(result.current.failures[0]?.pageIndex).toBe(1);
    expect(result.current.failures[0]?.message).not.toBe('');
    expect(result.current.finished).toBe(1);
  });

  it('шаг снова упал после повтора: лист завершается с ошибкой, без зацикливания', async () => {
    const failedConvert = (at: number) => ({
      sheets: [
        {
          ...fresh(0),
          convert: stage({ job_id: 'c-f', status: 'failed', result_status: null, error_code: 'X' }),
        },
      ],
      at,
    });
    const { result, rerender } = setup(failedConvert(1));
    act(() => result.current.start([0]));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(1));
    expect(calls()[0]).toMatchObject({ kind: 'retry' });

    rerender(failedConvert(2));
    await waitFor(() => expect(result.current.running).toBe(false));
    expect(mocks.run).toHaveBeenCalledTimes(1);
    expect(result.current.failures).toHaveLength(1);
    expect(result.current.failures[0]?.message).toContain('снова не выполнился');
  });

  it('«Остановить»: новые запуски прекращаются, партия завершается', async () => {
    const releases: Array<() => void> = [];
    mocks.run.mockImplementation(
      () => new Promise((resolve) => releases.push(() => resolve({ alreadyCurrent: false }))),
    );
    const { result, rerender } = setup({ sheets: [0, 1, 2, 3].map(fresh), at: 1 });
    act(() => result.current.start([0, 1, 2, 3]));
    await waitFor(() => expect(mocks.run).toHaveBeenCalledTimes(3));

    act(() => result.current.stop());
    expect(result.current.running).toBe(true);
    await act(async () => releases.forEach((release) => release()));
    rerender({ sheets: [0, 1, 2, 3].map(fresh), at: 2 });
    await waitFor(() => expect(result.current.running).toBe(false));
    expect(mocks.run).toHaveBeenCalledTimes(3);
  });

  it('пустой список ничего не запускает', () => {
    const { result } = setup({ sheets: [fresh(0)], at: 1 });
    act(() => result.current.start([]));
    expect(mocks.run).not.toHaveBeenCalled();
    expect(result.current.running).toBe(false);
  });
});
