import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { passportRow } from './__fixtures__';
import { SheetPassportsView } from './SheetPassportsView';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  listSheetPassports: vi.fn(),
  getSheetPassportExtractSummary: vi.fn(),
  bulkSheetPassportStatus: vi.fn(),
  startSheetPassportExtract: vi.fn(),
  patchSheetPassport: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const ROWS = [
  passportRow(),
  passportRow({
    id: 'sp-2',
    page_index: 3,
    section_mark: null,
    sheet_kind: null,
    stage: null,
    building: null,
    section: null,
    level_from: null,
    level_to: null,
    elevation_m: null,
    code: null,
    sheet_number: null,
    title: 'Ведомость отделки',
    evidence: {},
  }),
];

const mount = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <SheetPassportsView projectId="p-1" />
    </QueryClientProvider>,
  );
};

describe('Листы комплекта', () => {
  beforeEach(() => {
    vi.mocked(client.getSheetPassportExtractSummary)
      .mockReset()
      .mockImplementation(() => ok(null));
    vi.mocked(client.bulkSheetPassportStatus).mockReset();
    vi.mocked(client.listSheetPassports)
      .mockReset()
      .mockImplementation(((options: { query?: { status?: string } }) =>
        options.query?.status === 'confirmed'
          ? ok({ items: [], total: 4 })
          : ok({ items: ROWS, total: 2 })) as never);
  });

  it('пустые значения — прочерк, не 0; у значения метка источника с цитатой', async () => {
    mount();
    const rows = await screen.findAllByTestId('passport-row');
    expect(rows).toHaveLength(2);

    const empty = within(rows[1]!);
    expect(empty.getAllByText('—').length).toBeGreaterThanOrEqual(8);
    expect(empty.queryByText('0')).toBeNull();

    const first = within(rows[0]!);
    expect(first.getByText('План')).toBeInTheDocument();
    expect(first.getByText('1–14')).toBeInTheDocument();
    expect(first.getByText('штамп')).toHaveAttribute('title', 'Раздел АР');
    expect(screen.getByText('2 листов, подтверждено 4')).toBeInTheDocument();
  });

  it('поиск по шифру и заголовку работает на клиенте и очищается крестиком', async () => {
    mount();
    await screen.findAllByTestId('passport-row');
    await userEvent.type(
      screen.getByRole('searchbox', { name: 'Поиск по шифру и заголовку' }),
      'отделки',
    );
    expect(screen.getAllByTestId('passport-row')).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: /Очистить: Поиск/ }));
    expect(screen.getAllByTestId('passport-row')).toHaveLength(2);
  });

  it('«Подтвердить выбранные» отправляет id выбранных строк', async () => {
    vi.mocked(client.bulkSheetPassportStatus).mockImplementation(() => ok({ updated: 2 }));
    mount();
    await screen.findAllByTestId('passport-row');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Выбрать все на странице' }));
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить выбранные' }));

    await waitFor(() => expect(client.bulkSheetPassportStatus).toHaveBeenCalledTimes(1));
    expect(client.bulkSheetPassportStatus).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { project_id: 'p-1' },
        body: { ids: ['sp-1', 'sp-2'], status: 'confirmed' },
      }),
    );
  });

  it('«Отклонить выбранные» шлёт только отмеченную строку', async () => {
    vi.mocked(client.bulkSheetPassportStatus).mockImplementation(() => ok({ updated: 1 }));
    mount();
    await screen.findAllByTestId('passport-row');
    await userEvent.click(screen.getByRole('checkbox', { name: 'Выбрать: АР.pdf, стр. 4' }));
    await userEvent.click(screen.getByRole('button', { name: 'Отклонить выбранные' }));
    await waitFor(() => expect(client.bulkSheetPassportStatus).toHaveBeenCalled());
    expect(vi.mocked(client.bulkSheetPassportStatus).mock.calls[0]?.[0]?.body).toEqual({
      ids: ['sp-2'],
      status: 'rejected',
    });
  });

  it('«Разобрать листы» ставит задание разбора', async () => {
    vi.mocked(client.startSheetPassportExtract).mockImplementation(() => ok({ id: 'j-1' }));
    mount();
    await screen.findAllByTestId('passport-row');
    await userEvent.click(screen.getByRole('button', { name: 'Разобрать листы' }));
    await waitFor(() => expect(client.startSheetPassportExtract).toHaveBeenCalledTimes(1));
  });
});
