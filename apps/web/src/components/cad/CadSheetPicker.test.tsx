import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  calibrations: vi.fn(),
  features: { 'takeoff.manual': true } as Record<string, boolean>,
  jobs: [] as unknown[],
}));

vi.mock('@/lib/queries', () => ({
  useSheets: () => ({
    isPending: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
    data: {
      total: 2,
      items: [
        { id: 's0', page_index: 0, page_label: '1' },
        { id: 's1', page_index: 1, page_label: '2' },
      ],
    },
  }),
  useFeatures: () => mocks.features,
}));
vi.mock('@/lib/cad/sheet-queries', () => ({
  useSheetCalibrationStates: (sheets: readonly { page_index: number }[], enabled: boolean) => {
    mocks.calibrations(sheets, enabled);
    return new Map(sheets.map((sheet) => [sheet.page_index, 'missing']));
  },
}));
vi.mock('@/lib/cad/queries', () => ({
  useCadJobs: () => ({ data: { items: mocks.jobs, server_time: '' } }),
}));

import { CadSheetPicker } from './CadSheetPicker';

const mount = (
  onOpenSheet = vi.fn(),
  activePage: number | null = null,
  onWideChange?: (wide: boolean) => void,
) =>
  render(
    <CadSheetPicker
      projectId="p"
      revisionId="r"
      activePage={activePage}
      onOpenSheet={onOpenSheet}
      onWideChange={onWideChange}
    />,
  );

const job = (patch: Record<string, unknown>) => ({
  job_id: 'j1',
  status: 'succeeded',
  result_status: 'completed_requires_review',
  requested_pages: [0],
  created_at: '2026-11-10T10:00:00Z',
  ...patch,
});

beforeEach(() => {
  mocks.calibrations.mockReset();
  mocks.jobs = [];
  mocks.features = { 'takeoff.manual': true };
});

describe('CadSheetPicker', () => {
  it('нет чекбоксов и запуска по выбранным: строки - только кнопки открытия', () => {
    mount();
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.queryByRole('button', { name: /Запустить/ })).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(2);
  });

  it('распознанный лист: бейдж результата, строка открывает лист', () => {
    mocks.jobs = [job({})];
    const onOpenSheet = vi.fn();
    mount(onOpenSheet);
    expect(screen.getByText('DXF есть · проверка')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Стр. 1/ }));
    expect(onOpenSheet).toHaveBeenCalledWith(0);
  });

  it('идущее и упавшее задание: бейджи; строка открывает лист', () => {
    mocks.jobs = [
      job({ job_id: 'run', status: 'running', result_status: null, requested_pages: [0] }),
      job({ job_id: 'bad', status: 'failed', result_status: 'failed', requested_pages: [1] }),
    ];
    const onOpenSheet = vi.fn();
    mount(onOpenSheet);
    expect(screen.getByText('Выполняется')).toBeInTheDocument();
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Стр. 2/ }));
    expect(onOpenSheet).toHaveBeenCalledWith(1);
  });

  it('лист без задания тоже открывается по строке', () => {
    const onOpenSheet = vi.fn();
    mount(onOpenSheet);
    fireEvent.click(screen.getByRole('button', { name: /Стр. 1/ }));
    expect(onOpenSheet).toHaveBeenCalledWith(0);
  });

  it('открытый сейчас лист помечен aria-current', () => {
    mount(vi.fn(), 0);
    expect(screen.getByRole('button', { name: /Стр. 1/ })).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('button', { name: /Стр. 2/ })).not.toHaveAttribute('aria-current');
  });

  it('калибровка читается только у открытого листа', () => {
    mount(vi.fn(), 1);
    const [sheets, enabled] = mocks.calibrations.mock.calls.at(-1) as [{ page_index: number }[], boolean];
    expect(sheets.map((sheet) => sheet.page_index)).toEqual([1]);
    expect(enabled).toBe(true);
    // Лист без калибровки: бейдж только у открытой строки, ссылки калибровки нет.
    expect(screen.getAllByText('Нет калибровки')).toHaveLength(1);
    expect(screen.queryByText('Откалибровать')).toBeNull();
  });

  it('нет бейджей: колонка узкая', () => {
    const onWideChange = vi.fn();
    mount(vi.fn(), null, onWideChange);
    expect(onWideChange).toHaveBeenLastCalledWith(false);
    expect(onWideChange).not.toHaveBeenCalledWith(true);
  });

  it('есть бейдж результата: колонка широкая', () => {
    mocks.jobs = [job({})];
    const onWideChange = vi.fn();
    mount(vi.fn(), null, onWideChange);
    expect(onWideChange).toHaveBeenLastCalledWith(true);
  });

  it('есть бейдж калибровки у открытого листа: колонка широкая', () => {
    const onWideChange = vi.fn();
    mount(vi.fn(), 1, onWideChange);
    expect(onWideChange).toHaveBeenLastCalledWith(true);
  });

  it('открытого листа нет: калибровка не читается ни у одного', () => {
    mount();
    const [sheets] = mocks.calibrations.mock.calls.at(-1) as [unknown[]];
    expect(sheets).toEqual([]);
    expect(screen.queryByText('Нет калибровки')).toBeNull();
  });
});
