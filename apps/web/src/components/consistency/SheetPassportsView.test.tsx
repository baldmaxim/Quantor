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
  listSheetPassportGroups: vi.fn(),
  groupSheetPassportStatus: vi.fn(),
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

// Значения фильтров всего проекта: КР и корпуса 9 нет среди строк загруженной страницы.
const FACETS = {
  section_marks: ['АР', 'КР'],
  sheet_kinds: ['floor_plan', 'scheme'],
  buildings: ['9'],
  sections: ['3'],
};

const GROUPS = [
  {
    section_mark: 'АР',
    sheet_kind: 'floor_plan',
    building: '9',
    section: '3',
    total: 29,
    candidate: 27,
    confirmed: 2,
    rejected: 0,
    without_levels: 0,
  },
  {
    section_mark: 'ИОС4',
    sheet_kind: 'floor_plan',
    building: null,
    section: null,
    total: 75,
    candidate: 75,
    confirmed: 0,
    rejected: 0,
    without_levels: 3,
  },
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
          ? ok({ items: [], total: 4, ...FACETS })
          : ok({ items: ROWS, total: 2, ...FACETS })) as never);
    vi.mocked(client.listSheetPassportGroups)
      .mockReset()
      .mockImplementation(() => ok({ groups: GROUPS }));
    vi.mocked(client.groupSheetPassportStatus).mockReset();
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

  it('в фильтре «Раздел» все разделы проекта, а не только загруженной страницы', async () => {
    mount();
    await screen.findAllByTestId('passport-row');
    const select = screen.getByRole('combobox', { name: 'Раздел' });
    const options = within(select)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(options).toEqual(['Все', 'Не указан', 'АР', 'КР']);
  });

  it('фильтры типа, корпуса и секции — значения проекта и пункт «Не указан»', async () => {
    mount();
    await screen.findAllByTestId('passport-row');
    const options = (name: string) =>
      within(screen.getByRole('combobox', { name }))
        .getAllByRole('option')
        .map((option) => option.textContent);
    expect(options('Тип листа')).toEqual(['Все', 'Не указан', 'План', 'Схема']);
    expect(options('Корпус')).toEqual(['Все', 'Не указан', '9']);
    expect(options('Секция')).toEqual(['Все', 'Не указан', '3']);

    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Корпус' }), '9');
    await waitFor(() =>
      expect(client.listSheetPassports).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: expect.objectContaining({ building: '9' }) }),
      ),
    );
  });

  it('«Показать» ставит фильтры группы: не указанное поле — пустая строка', async () => {
    mount();
    await screen.findAllByTestId('passport-group');
    await userEvent.click(
      screen.getByRole('button', {
        name: 'Показать: ИОС4 · План · корпус не указан · секция не указана',
      }),
    );
    await waitFor(() =>
      expect(client.listSheetPassports).toHaveBeenCalledWith(
        expect.objectContaining({
          query: expect.objectContaining({
            section_mark: 'ИОС4',
            sheet_kind: 'floor_plan',
            building: '',
            section: '',
            status: null,
          }),
        }),
      ),
    );
    expect(screen.getByRole('combobox', { name: 'Корпус' })).toHaveDisplayValue('Не указан');
  });

  it('«Подтвердить» отправляет ключ группы целиком, с null для не указанного', async () => {
    vi.mocked(client.groupSheetPassportStatus).mockImplementation(() => ok({ updated: 27 }));
    mount();
    const [built] = await screen.findAllByTestId('passport-group');
    expect(within(built!).getByText('2 из 29')).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole('button', {
        name: 'Подтвердить 75: ИОС4 · План · корпус не указан · секция не указана',
      }),
    );
    await waitFor(() => expect(client.groupSheetPassportStatus).toHaveBeenCalledTimes(1));
    expect(vi.mocked(client.groupSheetPassportStatus).mock.calls[0]?.[0]?.body).toEqual({
      section_mark: 'ИОС4',
      sheet_kind: 'floor_plan',
      building: null,
      section: null,
      status: 'confirmed',
    });
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
