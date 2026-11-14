import * as client from '@quantor/api-client';
import type { FrameCheckOut, FrameNodeOut, FrameOut, SheetRegistersOut } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as queries from '@/lib/queries';

import { FrameScreen } from './FrameScreen';

vi.mock('@/lib/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof queries>()),
  useMeta: vi.fn(),
  useFeatures: vi.fn(),
  useProject: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  getBuildingFrame: vi.fn(),
  rebuildBuildingFrame: vi.fn(),
  bulkFrameStatus: vi.fn(),
  patchFrameNode: vi.fn(),
  createFrameNode: vi.fn(),
  deleteFrameNode: vi.fn(),
  getSheetRegisters: vi.fn(),
  startSheetRegisterExtract: vi.fn(),
  bulkSheetRegisterStatus: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const node = (overrides: Partial<FrameNodeOut>): FrameNodeOut => ({
  id: 'n',
  kind: 'level',
  parent_id: null,
  building: '1',
  section: null,
  code: null,
  ordinal: null,
  elevation_m: null,
  height_m: null,
  height_derived_m: null,
  status: 'candidate',
  origin: 'passports',
  passport_count: 1,
  passports: [],
  elevation_sources: [],
  elevation_values: [],
  manual_fields: [],
  confirmed_at: null,
  ...overrides,
});

const check = (overrides: Partial<FrameCheckOut>): FrameCheckOut => ({
  code: 'ar_plan_per_level',
  title: 'План АР на каждый уровень',
  status: 'match',
  message: 'План АР есть: 1 лист(ов).',
  building: '1',
  section: null,
  level: '1 этаж',
  refs: [],
  ...overrides,
});

const FRAME: FrameOut = {
  nodes: [
    node({ id: 'b', kind: 'building' }),
    node({ id: 's', kind: 'section', parent_id: 'b' }),
    node({
      id: 'l1',
      parent_id: 's',
      code: '1 этаж',
      ordinal: 1,
      elevation_m: 0,
      height_derived_m: 3.3,
      status: 'confirmed',
    }),
    node({
      id: 'l2',
      parent_id: 's',
      code: '2 этаж',
      ordinal: 2,
      elevation_values: [3.3, 3.6],
    }),
  ],
  checks: [
    check({}),
    check({
      status: 'mismatch',
      level: '2 этаж',
      message: 'Нет подтверждённого плана АР. Уровень есть на планах: ИОС2.',
      refs: [
        {
          kind: 'passport',
          id: 'p',
          label: 'ИОС2 · План 2 этажа',
          file_name: 'ИОС2.pdf',
          page_index: 4,
        },
      ],
    }),
    check({
      code: 'pz_storeys',
      title: 'ПЗ ↔ этажность',
      status: 'not_run',
      message: 'Нет подтверждённого ответа «Этажность» в вопросах к документации.',
      building: null,
      level: null,
    }),
  ],
  confirmed_plans: 3,
  candidate_plans: 2,
  versions: { frame: 'consistency.frame.v1', checks: 'consistency.checks.frame.v1' },
};

const REGISTERS: SheetRegistersOut = {
  registers: [
    {
      id: 'r-1',
      revision_id: 'rev-1',
      file_name: 'АР.pdf',
      page_index: 0,
      pages: [0, 1],
      heading: 'Ведомость рабочих чертежей основного комплекта',
      entries: [
        { number: '1', title: 'Общие данные', snippet: '1 Общие данные', page_index: 0 },
        { number: '2', title: 'План 1 этажа', snippet: '2 План 1 этажа', page_index: 1 },
      ],
      duplicates: [],
      status: 'candidate',
      confirmed_at: null,
    },
  ],
  last_extract: {
    job_id: 'j-1',
    status: 'succeeded',
    progress: 1,
    stage: null,
    error_code: null,
    created_at: '2026-11-14T10:00:00Z',
    finished_at: '2026-11-14T10:01:00Z',
    registers: 1,
    revisions_total: 3,
    revisions_scanned: 2,
    revisions_no_text: 1,
    no_text_files: ['ИОС2.pdf'],
    revisions_unreadable: 0,
    unreadable_files: [],
    versions: {},
  },
  versions: {},
};

const setup = (features: Record<string, boolean> = { 'project.consistency': true }) => {
  vi.mocked(queries.useMeta).mockReturnValue({ isSuccess: true } as never);
  vi.mocked(queries.useFeatures).mockReturnValue(features);
  vi.mocked(queries.useProject).mockReturnValue({ data: { name: 'Объект' } } as never);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <FrameScreen projectId="p-1" />
    </QueryClientProvider>,
  );
};

describe('экран «Каркас здания»', () => {
  beforeEach(() => {
    vi.mocked(client.getBuildingFrame)
      .mockReset()
      .mockImplementation(() => ok(FRAME));
    vi.mocked(client.bulkFrameStatus)
      .mockReset()
      .mockImplementation(() => ok({ updated: 3 }));
    vi.mocked(client.rebuildBuildingFrame)
      .mockReset()
      .mockImplementation(() => ok({ created: 1, updated: 2, removed: 0, kept_reviewed: 1 }));
    vi.mocked(client.getSheetRegisters)
      .mockReset()
      .mockImplementation(() => ok(REGISTERS));
    vi.mocked(client.bulkSheetRegisterStatus)
      .mockReset()
      .mockImplementation(() => ok({ updated: 1 }));
    vi.mocked(client.startSheetRegisterExtract)
      .mockReset()
      .mockImplementation(() => ok({ id: 'j-2' }));
  });

  it('флаг закрыт — заглушка, запроса нет', () => {
    setup({ 'project.consistency': false });
    expect(screen.getByText('Страница не найдена')).toBeInTheDocument();
    expect(client.getBuildingFrame).not.toHaveBeenCalled();
  });

  it('показывает уровни, разные отметки и только расхождения по умолчанию', async () => {
    setup();
    expect(await screen.findAllByTestId('frame-level')).toHaveLength(2);
    expect(screen.getByText('Разные: +3,300; +3,600')).toBeInTheDocument();
    expect(screen.getByText('3300 мм')).toBeInTheDocument();
    const shown = screen.getAllByTestId('frame-check');
    expect(shown).toHaveLength(1);
    expect(within(shown[0]!).getByText(/ИОС2\.pdf, стр\. 5/)).toBeInTheDocument();
    expect(screen.getByText('непроверенных:', { exact: false })).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText('Только расхождения'));
    expect(screen.getAllByTestId('frame-check')).toHaveLength(3);
    expect(screen.getByText('Не проверено', { selector: 'span' })).toBeInTheDocument();
  });

  it('«Подтвердить все кандидаты» отправляет только кандидатов', async () => {
    setup();
    await userEvent.click(await screen.findByRole('button', { name: /Подтвердить все кандидаты/ }));
    await waitFor(() => expect(client.bulkFrameStatus).toHaveBeenCalled());
    const options = vi.mocked(client.bulkFrameStatus).mock.calls[0]![0];
    expect(options.body).toEqual({ ids: ['b', 's', 'l2'], status: 'confirmed' });
  });

  it('пересборка показывает итог', async () => {
    setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Собрать из паспортов' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Создано: 1, обновлено: 2');
  });

  it('ведомость: строки, итог разбора и подтверждение ведомости целиком', async () => {
    setup();
    const item = await screen.findByTestId('sheet-register');
    expect(within(item).getByText('стр. 1–2 · строк: 2')).toBeInTheDocument();
    expect(within(item).getByText('План 1 этажа')).toBeInTheDocument();
    expect(screen.getByTestId('register-summary')).toHaveTextContent(
      'Найдено ведомостей: 1 · просмотрено ревизий: 2 из 3 · без текста страниц: 1',
    );
    await userEvent.click(within(item).getByRole('button', { name: 'Подтвердить' }));
    await waitFor(() => expect(client.bulkSheetRegisterStatus).toHaveBeenCalled());
    const options = vi.mocked(client.bulkSheetRegisterStatus).mock.calls[0]![0];
    expect(options.body).toEqual({ ids: ['r-1'], status: 'confirmed' });
  });

  it('«Разобрать ведомости» ставит задание', async () => {
    setup();
    await userEvent.click(await screen.findByRole('button', { name: 'Разобрать ведомости' }));
    await waitFor(() => expect(client.startSheetRegisterExtract).toHaveBeenCalled());
  });
});
