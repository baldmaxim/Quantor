import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  readCadSheetRisers: vi.fn(),
  putCadSheetRisers: vi.fn(),
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
  shaft_id: null,
  source: 'ИОС2.1 л.2',
  note: null,
};

const out = (risers: object[], updatedAt: string | null = null) => ({
  revision_id: 'r1',
  page_index: 81,
  view: 1,
  risers,
  updated_at: updatedAt,
});

const renderPanel = () =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CadRisersPanel parent={PARENT} />
    </QueryClientProvider>,
  );

describe('раздел «Стояки»', () => {
  beforeEach(() => vi.clearAllMocks());

  it('пустой реестр: подсказка про подписи шахт АР и напоминание про перестроение трасс', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([]) });
    renderPanel();
    expect(await screen.findByTestId('cad-risers-empty')).toHaveTextContent(
      'Реестр не задан: стояки по подписям шахт АР.',
    );
    expect(screen.getByRole('note')).toHaveTextContent('перестройте трассы');
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled();
  });

  it('показывает записи сервера, добавляет строку и сохраняет списком', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    api.putCadSheetRisers.mockImplementation(async ({ body }: { body: { risers: object[] } }) => ({
      data: out(body.risers, '2026-11-11T10:00:00Z'),
    }));
    renderPanel();

    const [first] = await screen.findAllByTestId('cad-riser-row');
    expect(within(first as HTMLElement).getByLabelText('Марка, Стояк 1')).toHaveValue('В1.1.1');
    expect(within(first as HTMLElement).getByLabelText('Диаметр, мм, Стояк 1')).toHaveValue('50');

    fireEvent.click(screen.getByRole('button', { name: 'Добавить строку' }));
    expect(screen.getAllByTestId('cad-riser-row')).toHaveLength(2);
    fireEvent.change(screen.getByLabelText('Марка, Стояк 2'), { target: { value: 'В2.1' } });
    fireEvent.change(screen.getAllByLabelText('Система')[1] as HTMLElement, {
      target: { value: 'VPV' },
    });
    fireEvent.change(screen.getByLabelText('Количество, Стояк 2'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Шахта, Стояк 2'), { target: { value: 'S12' } });

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(api.putCadSheetRisers).toHaveBeenCalledTimes(1));
    expect(api.putCadSheetRisers.mock.calls[0]?.[0]).toMatchObject({
      path: { project_id: 'p1' },
      query: { revision_id: 'r1', page_index: 81, view: 1 },
      body: {
        risers: [
          ENTRY,
          {
            system: 'VPV',
            mark: 'В2.1',
            dn_mm: null,
            role: 'own',
            count: 2,
            shaft_id: 'S12',
            source: null,
            note: null,
          },
        ],
      },
    });
    expect(await screen.findByText(/Реестр сохранён/)).toBeInTheDocument();
  });

  it('неверные поля не уходят на сервер и подсвечиваются', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    fireEvent.change(screen.getByLabelText('Диаметр, мм, Стояк 1'), { target: { value: '5' } });
    fireEvent.change(screen.getByLabelText('Шахта, Стояк 1'), { target: { value: 'шахта' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText('От 10 до 400 мм.')).toBeInTheDocument();
    expect(screen.getByText('Вид S12 или S123.')).toBeInTheDocument();
    expect(api.putCadSheetRisers).not.toHaveBeenCalled();
  });

  it('выбор воздушной системы показывает «Сечение» вместо Ø и сохраняет канал и подробности', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    api.putCadSheetRisers.mockImplementation(async ({ body }: { body: { risers: object[] } }) => ({
      data: out(body.risers, '2026-11-12T10:00:00Z'),
    }));
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    expect(screen.queryByLabelText('Сечение a, мм, Стояк 1')).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Система'), { target: { value: 'DU' } });
    expect(screen.queryByLabelText('Диаметр, мм, Стояк 1')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Сечение a, мм, Стояк 1')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Сечение a, мм, Стояк 1'), { target: { value: '400' } });
    fireEvent.change(screen.getByLabelText('Сечение b, мм, Стояк 1'), { target: { value: '600' } });
    fireEvent.change(screen.getByLabelText('Этаж от, Стояк 1'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Этаж до, Стояк 1'), { target: { value: '25' } });
    fireEvent.change(screen.getByLabelText('Клапан'), { target: { value: 'NO' } });

    fireEvent.change(screen.getByLabelText('Канал'), { target: { value: 'round' } });
    expect(screen.getByLabelText('Ø канала, мм, Стояк 1')).toHaveValue('');
    fireEvent.change(screen.getByLabelText('Ø канала, мм, Стояк 1'), { target: { value: '315' } });

    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() => expect(api.putCadSheetRisers).toHaveBeenCalledTimes(1));
    const [entry] = (api.putCadSheetRisers.mock.calls[0]?.[0] as { body: { risers: object[] } })
      .body.risers;
    expect(entry).toMatchObject({
      system: 'DU',
      dn_mm: null,
      d_mm: 315,
      floors: [2, 25],
      valve: 'NO',
    });
    expect(entry).not.toHaveProperty('section_mm');
  });

  it('Ø трубы у воздушной системы - ошибка, на сервер не уходит', async () => {
    const wrong = { ...ENTRY, system: 'VZH' as const, dn_mm: 50 };
    api.readCadSheetRisers.mockResolvedValue({ data: out([wrong]) });
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    fireEvent.change(screen.getByLabelText('Марка, Стояк 1'), { target: { value: 'ВЕ1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText(/У воздушной системы нет Ø трубы/)).toBeInTheDocument();
    expect(api.putCadSheetRisers).not.toHaveBeenCalled();
  });

  it('этажи: неполная пара - ошибка в раскрытом блоке «Подробнее»', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    fireEvent.change(screen.getByLabelText('Этаж от, Стояк 1'), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByText(/Оба этажа/)).toBeInTheDocument();
    expect(api.putCadSheetRisers).not.toHaveBeenCalled();
  });

  it('удаление строки возвращает «реестр не задан» и разрешает сохранить пустой список', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    api.putCadSheetRisers.mockResolvedValue({ data: out([], '2026-11-11T10:00:00Z') });
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    fireEvent.click(screen.getByRole('button', { name: 'Удалить: Стояк 1' }));
    expect(screen.getByTestId('cad-risers-empty')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    await waitFor(() =>
      expect(api.putCadSheetRisers.mock.calls[0]?.[0]).toMatchObject({ body: { risers: [] } }),
    );
  });

  it('крестик очищает поле марки', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    fireEvent.click(screen.getByRole('button', { name: 'Очистить: Марка, Стояк 1' }));
    expect(screen.getByLabelText('Марка, Стояк 1')).toHaveValue('');
  });

  it('отказ записи показывается текстом', async () => {
    api.readCadSheetRisers.mockResolvedValue({ data: out([ENTRY]) });
    api.putCadSheetRisers.mockRejectedValue({ detail: { code: 'FEATURE_DISABLED' } });
    renderPanel();
    await screen.findByTestId('cad-riser-row');
    fireEvent.change(screen.getByLabelText('Диаметр, мм, Стояк 1'), { target: { value: '65' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('ошибка чтения: текст и «Повторить»', async () => {
    api.readCadSheetRisers.mockRejectedValueOnce({ detail: { code: 'NOT_FOUND' } });
    api.readCadSheetRisers.mockResolvedValue({ data: out([]) });
    renderPanel();
    expect(await screen.findByText(/Не удалось загрузить реестр/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByTestId('cad-risers-empty')).toBeInTheDocument();
  });
});
