import type * as ApiClient from '@quantor/api-client';
import type { CadPipelineSheetRead, CadPipelineStageRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ pipeline: vi.fn(), sheets: vi.fn(), createJob: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readCadPipeline: mocks.pipeline,
  listRevisionSheets: mocks.sheets,
  createCadJob: mocks.createJob,
}));

import { DocumentCadPipeline } from './DocumentCadPipeline';

const stage = (overrides: Partial<CadPipelineStageRead> = {}): CadPipelineStageRead => ({
  job_id: 'job-9',
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

const sheet = (pageIndex: number, overrides: Partial<CadPipelineSheetRead> = {}): CadPipelineSheetRead => ({
  page_index: pageIndex,
  page_label: String(pageIndex + 1),
  title: null,
  is_plan: true,
  scale_source: null,
  calibrated: false,
  convert: null,
  views: [],
  ...overrides,
});

const unconfirmed = stage({
  job_id: 'job-u',
  status: 'failed',
  result_status: null,
  error_code: 'CAD_AUTO_SCALE_UNCONFIRMED',
});

const respond = (sheets: CadPipelineSheetRead[]) =>
  mocks.pipeline.mockResolvedValue({
    data: { revision_id: 'rev-1', server_time: '2026-11-11T10:00:00Z', sheets },
  });

const renderList = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DocumentCadPipeline projectId="p-1" revisionId="rev-1" />
    </QueryClientProvider>,
  );
};

const checkbox = (page: string) =>
  screen.getByRole<HTMLInputElement>('checkbox', { name: `Выбрать лист ${page}` });

describe('конвейер CAD документа: массовый запуск', () => {
  beforeEach(() => {
    mocks.pipeline.mockReset();
    mocks.sheets.mockReset();
    mocks.createJob.mockReset();
    mocks.sheets.mockResolvedValue({ data: { items: [], total: 0 } });
  });

  it('листы по порядку страниц, название и бейдж «Масштаб: авто», сводка', async () => {
    respond([
      sheet(4, { title: 'План 5 этажа' }),
      sheet(1, { convert: stage(), scale_source: 'auto' }),
      sheet(0, { is_plan: false, convert: stage() }),
    ]);
    renderList();

    expect(await screen.findByText('Планов: 2 · без CAD: 1')).toBeInTheDocument();
    const labels = screen
      .getAllByRole('checkbox')
      .map((box) => box.getAttribute('aria-label'))
      .filter(Boolean);
    expect(labels).toEqual(['Выбрать лист 1', 'Выбрать лист 2', 'Выбрать лист 5']);
    expect(screen.getByText('План 5 этажа')).toBeInTheDocument();
    const autoRow = checkbox('2').closest('li') as HTMLElement;
    expect(within(autoRow).getByText('Масштаб: авто')).toBeInTheDocument();
  });

  it('недоступные листы: чекбокс неактивен (готово, масштаб не подтверждён)', async () => {
    respond([
      sheet(0),
      sheet(1, { convert: stage() }),
      sheet(2, { convert: unconfirmed }),
      sheet(3, { convert: unconfirmed, calibrated: true }),
    ]);
    renderList();

    await screen.findByText('Планов: 4 · без CAD: 1');
    expect(checkbox('1')).toBeEnabled();
    expect(checkbox('2')).toBeDisabled();
    expect(checkbox('3')).toBeDisabled();
    expect(checkbox('4')).toBeEnabled();
  });

  it('выбор листов обновляет кнопку; «Выбрать все» берёт только доступные', async () => {
    const user = userEvent.setup();
    respond([sheet(0), sheet(1, { convert: stage() }), sheet(2)]);
    renderList();

    await screen.findByText('Планов: 3 · без CAD: 2');
    const launch = screen.getByRole('button', { name: /Преобразовать выбранные/ });
    expect(launch).toBeDisabled();

    await user.click(checkbox('1'));
    expect(screen.getByRole('button', { name: 'Преобразовать выбранные (1)' })).toBeEnabled();
    expect(
      screen.getByRole<HTMLInputElement>('checkbox', { name: 'Выбрать все доступные' }).indeterminate,
    ).toBe(true);
    // Щелчок по чекбоксу не раскрывает строку.
    expect(screen.queryByRole('list', { name: 'Шаги листа' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: 'Выбрать все доступные' }));
    expect(screen.getByRole('button', { name: 'Преобразовать выбранные (2)' })).toBeEnabled();
    expect(checkbox('2').checked).toBe(false);
  });

  it('запуск: по заданию на лист с auto_scale, затем выбор сбрасывается', async () => {
    const user = userEvent.setup();
    respond([sheet(0), sheet(1), sheet(2, { convert: stage() })]);
    mocks.createJob.mockResolvedValue({ data: { job_id: 'job-new' } });
    renderList();

    await screen.findByText('Планов: 3 · без CAD: 2');
    await user.click(screen.getByRole('checkbox', { name: 'Выбрать все доступные' }));
    await user.click(screen.getByRole('button', { name: 'Преобразовать выбранные (2)' }));

    await waitFor(() => expect(mocks.createJob).toHaveBeenCalledTimes(2));
    const bodies = mocks.createJob.mock.calls.map((call) => (call[0] as { body: unknown }).body);
    expect(bodies).toEqual([
      { pages: [0], finishes: false, schedules: false, auto_scale: true },
      { pages: [1], finishes: false, schedules: false, auto_scale: true },
    ]);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Преобразовать выбранные (0)' })).toBeDisabled(),
    );
    expect(checkbox('1').checked).toBe(false);
  });

  it('отказ постановки: сводка по листу', async () => {
    const user = userEvent.setup();
    respond([sheet(0), sheet(1)]);
    mocks.createJob.mockImplementation(({ body }: { body: { pages: number[] } }) =>
      body.pages[0] === 1
        ? Promise.reject({ status: 409, code: 'CAD_CALIBRATION_REQUIRED', message: 'x' })
        : Promise.resolve({ data: { job_id: 'job-new' } }),
    );
    renderList();

    await screen.findByText('Планов: 2 · без CAD: 2');
    await user.click(screen.getByRole('checkbox', { name: 'Выбрать все доступные' }));
    await user.click(screen.getByRole('button', { name: 'Преобразовать выбранные (2)' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Поставлено 1 из 2; не поставлено: 1');
    expect(alert).toHaveTextContent('Лист 2:');
  });
});
