import * as client from '@quantor/api-client';
import type { VorFillItemRead, VorFillRead, VorObjectRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { vorItem } from '@/lib/cad/vor-fixtures';
import * as queries from '@/lib/queries';

import { VorFillScreen } from './VorFillScreen';

vi.mock('@/lib/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof queries>()),
  useMeta: vi.fn(),
  useFeatures: vi.fn(),
  useProject: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readVorFill: vi.fn(),
  readVorAiMap: vi.fn(),
  exportVorFill: vi.fn(),
  listCadVorLinks: vi.fn(),
  suggestCadVorItems: vi.fn(),
  listCadVorItems: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const fillItem = (patch: Partial<VorFillItemRead> & { id: string }): VorFillItemRead => {
  const { id, ...rest } = patch;
  return {
    item: vorItem({ id, name: `Позиция ${id}`, quantity: 10, unit: 'м3' }),
    status: 'match',
    customer_quantity: 10,
    unit: 'm3',
    quantor_quantity: 10,
    difference: 0,
    difference_percent: 0,
    group_keys: ['masonry|200|'],
    missing_group_keys: [],
    sources: ['План 1 · лист 1'],
    ...rest,
  };
};

const object = (patch: Partial<VorObjectRead> = {}): VorObjectRead => ({
  group_key: 'door||900x2100',
  kind: 'door',
  title: 'Дверь 900 x 2100 мм',
  quantities: [{ unit: 'pcs', value: 12 }],
  incomplete: false,
  sources: [{ label: 'План 1 · лист 1', job_id: 'j1', page_index: 0, view: 1, note: null }],
  ...patch,
});

const fill = (patch: Partial<VorFillRead> = {}): VorFillRead => ({
  document_id: 'd1',
  has_vor: true,
  items: [
    fillItem({ id: 'a' }),
    fillItem({
      id: 'b',
      status: 'differs',
      quantor_quantity: 14,
      difference: 4,
      difference_percent: 40,
    }),
    fillItem({
      id: 'c',
      status: 'unit_mismatch',
      quantor_quantity: null,
      difference: null,
      difference_percent: null,
    }),
  ],
  unlinked: [object()],
  objects: [object()],
  unavailable: [{ kind: 'finish', reason: 'зон МОП в проекте нет' }],
  warnings: ['Типовых листов: 1. Количество одного этажа на число этажей не умножалось.'],
  skipped_sheets: [],
  ...patch,
});

const mount = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <VorFillScreen projectId="p1" />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(queries.useMeta).mockReturnValue({ isSuccess: true } as never);
  vi.mocked(queries.useFeatures).mockReturnValue({ 'cad.export': true });
  vi.mocked(queries.useProject).mockReturnValue({ data: { name: 'Объект' } } as never);
  vi.mocked(client.readVorAiMap).mockReturnValue(
    ok({
      available: false,
      job_id: null,
      status: null,
      error_message: null,
      stale: false,
      model: null,
      prompt_version: null,
      suggestions: [],
      unmatched: [],
      limitations: [],
    }),
  );
  vi.mocked(client.listCadVorLinks).mockReturnValue(ok([]));
  vi.mocked(client.suggestCadVorItems).mockReturnValue(ok([]));
  vi.mocked(client.listCadVorItems).mockReturnValue(ok({ total: 0, items: [] }));
});

describe('заполнение ВОР', () => {
  it('показывает таблицу с количествами, разницей и статусами', async () => {
    vi.mocked(client.readVorFill).mockReturnValue(ok(fill()));
    mount();
    const table = await screen.findByRole('table');
    expect(within(table).getByText('Совпало')).toBeInTheDocument();
    expect(within(table).getByText('Расходится')).toHaveClass('text-warning');
    expect(within(table).getByText('Единицы не совпали')).toHaveClass('text-danger');
    expect(within(table).getByText('+4 (+40 %)')).toBeInTheDocument();
    expect(screen.getByText(/Типовых листов: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Отделка МОП: зон МОП в проекте нет/)).toBeInTheDocument();
  });

  it('список «нет в ВОР» с количеством объекта', async () => {
    vi.mocked(client.readVorFill).mockReturnValue(ok(fill()));
    mount();
    const section = await screen.findByRole('region', { name: 'Нет в ВОР' });
    expect(within(section).getByText('Дверь 900 x 2100 мм')).toBeInTheDocument();
    expect(within(section).getByText(/12 шт/)).toBeInTheDocument();
  });

  it('кнопка выгрузки зовёт сервер и показывает ссылку на скачивание', async () => {
    vi.mocked(client.readVorFill).mockReturnValue(ok(fill()));
    vi.mocked(client.exportVorFill).mockReturnValue(
      ok({
        file_name: 'ВОР_Quantor.xlsx',
        size: 10,
        created_at: '2026-11-25T10:00:00Z',
        download_url: '/api/v1/projects/p1/vor/fill/files/20261125T100000Z',
      }),
    );
    mount();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole('button', { name: 'Выгрузить заполненный ВОР (xlsx)' }),
    );
    const link = await screen.findByRole('link', { name: 'Скачать ВОР_Quantor.xlsx' });
    expect(link.getAttribute('href')).toContain(
      '/api/v1/projects/p1/vor/fill/files/20261125T100000Z',
    );
    expect(client.exportVorFill).toHaveBeenCalledTimes(1);
  });

  it('без ВОР выгрузка недоступна', async () => {
    vi.mocked(client.readVorFill).mockReturnValue(
      ok(fill({ has_vor: false, document_id: null, items: [] })),
    );
    mount();
    expect(
      await screen.findByRole('button', { name: 'Выгрузить заполненный ВОР (xlsx)' }),
    ).toBeDisabled();
    expect(screen.getByText(/ВОР Заказчика не загружен/)).toBeInTheDocument();
  });

  it('флаг выключен: страницы нет, запросов нет', () => {
    vi.mocked(queries.useFeatures).mockReturnValue({ 'cad.export': false });
    mount();
    expect(screen.getByText('Страница не найдена')).toBeInTheDocument();
    expect(client.readVorFill).not.toHaveBeenCalled();
  });

  it('«Связать с ВОР» открывает выбор строк', async () => {
    vi.mocked(client.readVorFill).mockReturnValue(ok(fill()));
    mount();
    const user = userEvent.setup();
    const section = await screen.findByRole('region', { name: 'Нет в ВОР' });
    await user.click(within(section).getByRole('button', { name: 'Связать с ВОР' }));
    expect(await screen.findByText('Связать со строками ВОР')).toBeInTheDocument();
    expect(client.suggestCadVorItems).toHaveBeenCalled();
  });
});
