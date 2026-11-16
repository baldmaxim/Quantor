import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  readCadSheetRisers: vi.fn(),
  putCadSheetRisers: vi.fn(),
  listCadRisersSheets: vi.fn(),
  draftCadRisersCopy: vi.fn(),
}));

const pipeline = vi.hoisted(() => ({
  sheets: [] as object[],
}));

vi.mock('@/lib/cad/pipeline-queries', () => ({
  useCadPipeline: () => ({ data: { revision_id: 'r1', sheets: pipeline.sheets } }),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { CadRisersPanel } from './CadRisersPanel';

const PARENT = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'job-parent',
  attempt: 1,
  pageIndex: 81,
  view: 1,
};

const ENTRY = {
  system: 'V1' as const,
  mark: 'В1.1.1',
  dn_mm: 50,
  role: 'own' as const,
  count: 1,
  shaft_id: 'S06',
  source: null,
  note: null,
};
const ENTRY2 = { ...ENTRY, mark: 'В1.2.1', shaft_id: null };

const out = (risers: object[], updatedAt: string | null = null) => ({
  revision_id: 'r1',
  page_index: 81,
  view: 1,
  risers,
  updated_at: updatedAt,
});

const sheetsOut = (sheets: object[]) => ({ revision_id: 'r1', sheets });
const SOURCE = { page_index: 80, view: 1, risers_count: 2, updated_at: '2026-11-10T10:00:00Z' };
const CURRENT = { page_index: 81, view: 1, risers_count: 1, updated_at: '2026-11-10T10:00:00Z' };

const copyOut = (over: object = {}) => ({
  revision_id: 'r1',
  page_index: 81,
  view: 1,
  source_page_index: 80,
  source_view: 1,
  risers: [{ ...ENTRY, shaft_id: 'S11' }, ENTRY2],
  shafts: 'matched',
  shift_mm: [120.4, -35.6],
  rows: [
    { index: 0, source_shaft_id: 'S06', shaft_id: 'S11', status: 'matched', distance_mm: 12 },
    { index: 1, source_shaft_id: 'S07', shaft_id: null, status: 'not_found', distance_mm: null },
  ],
  ...over,
});

const renderPanel = () =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CadRisersPanel parent={PARENT} />
    </QueryClientProvider>,
  );

describe('«Скопировать с другого листа»', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.readCadSheetRisers.mockResolvedValue({ data: out([]) });
    api.listCadRisersSheets.mockResolvedValue({ data: sheetsOut([CURRENT, SOURCE]) });
    pipeline.sheets = [
      { page_index: 80, floor_title: { corps: '9', section: '3', floors: ['15'], text: null } },
    ];
  });

  it('список без текущего листа, подпись этажом и числом стояков', async () => {
    renderPanel();
    const select = await screen.findByLabelText('Скопировать с другого листа');
    await waitFor(() =>
      expect(within(select).getByRole('option')).toHaveTextContent('К9 · С3 · 15 эт. (2)'),
    );
    expect(within(select).getAllByRole('option')).toHaveLength(1);
  });

  it('без заголовка плана - «Лист N»', async () => {
    pipeline.sheets = [];
    renderPanel();
    const select = await screen.findByLabelText('Скопировать с другого листа');
    await waitFor(() =>
      expect(within(select).getByRole('option')).toHaveTextContent('Лист 81 (2)'),
    );
  });

  it('нет листов-источников - блока нет', async () => {
    api.listCadRisersSheets.mockResolvedValue({ data: sheetsOut([CURRENT]) });
    renderPanel();
    await screen.findByTestId('cad-risers-empty');
    expect(screen.queryByTestId('cad-risers-copy')).not.toBeInTheDocument();
  });

  it('копирование в пустую форму: строки, активное «Сохранить», сообщение о совпадениях', async () => {
    api.draftCadRisersCopy.mockResolvedValue({ data: copyOut() });
    renderPanel();
    await screen.findByLabelText('Скопировать с другого листа');
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Скопировать' }));

    expect(await screen.findAllByTestId('cad-riser-row')).toHaveLength(2);
    expect(api.draftCadRisersCopy.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1' },
      query: {
        revision_id: 'r1',
        page_index: 81,
        view: 1,
        source_page_index: 80,
        source_view: 1,
      },
    });
    expect(screen.getByLabelText('Шахта, Стояк 1')).toHaveValue('S11');
    expect(screen.getByLabelText('Шахта, Стояк 2')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled();
    const status = screen.getByText(/Скопировано 2 строк/);
    expect(status).toHaveTextContent('сдвиг 120, -36 мм): совпало 1.');
    expect(status).toHaveTextContent('Не найдены на этом листе: В1.2.1');
    expect(status).toHaveTextContent('Проверьте и сохраните.');
    expect(api.putCadSheetRisers).not.toHaveBeenCalled();
  });

  it('шахты не сопоставлены - своё сообщение', async () => {
    api.draftCadRisersCopy.mockResolvedValue({
      data: copyOut({ shafts: 'unknown', shift_mm: null, rows: [] }),
    });
    renderPanel();
    await screen.findByLabelText('Скопировать с другого листа');
    fireEvent.click(screen.getByRole('button', { name: 'Скопировать' }));
    expect(await screen.findByText(/Шахты листов не сопоставлены/)).toHaveTextContent(
      'Номера шахт оставлены как на листе-источнике',
    );
  });

  it('непустая форма: подтверждение, «Отмена» ничего не меняет', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    api.draftCadRisersCopy.mockResolvedValue({ data: copyOut() });
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    await screen.findByLabelText('Скопировать с другого листа');
    fireEvent.click(screen.getByRole('button', { name: 'Скопировать' }));
    expect(await screen.findByText(/Строки формы заменятся/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(api.draftCadRisersCopy).not.toHaveBeenCalled();
    expect(screen.getAllByTestId('cad-riser-row')).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: 'Скопировать' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Заменить' }));
    await waitFor(() => expect(screen.getAllByTestId('cad-riser-row')).toHaveLength(2));
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeEnabled();
  });

  it('404 у источника - alert', async () => {
    api.draftCadRisersCopy.mockRejectedValue({ detail: { code: 'NOT_FOUND' } });
    renderPanel();
    await screen.findByLabelText('Скопировать с другого листа');
    fireEvent.click(screen.getByRole('button', { name: 'Скопировать' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('после сохранения список листов запрашивается заново', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    api.putCadSheetRisers.mockImplementation(async ({ body }: { body: { risers: object[] } }) => ({
      data: out(body.risers, '2026-11-12T10:00:00Z'),
    }));
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    await waitFor(() => expect(api.listCadRisersSheets).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByLabelText('Диаметр, мм, Стояк 1'), { target: { value: '65' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(api.putCadSheetRisers).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(api.listCadRisersSheets.mock.calls.length).toBeGreaterThanOrEqual(2),
    );
  });
});
