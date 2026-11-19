import * as client from '@quantor/api-client';
import type {
  PersonalTokenCreated,
  TenderBaseCandidatesRead,
  TenderBaseReleaseRead,
  TenderCalcRead,
  TenderCalcVersionRead,
  TenderCalcVersionSummaryRead,
} from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as queries from '@/lib/queries';
import * as session from '@/lib/session';

import { BaseTab } from './BaseTab';
import { CalcsTab } from './CalcsTab';
import { TenderCalcsScreen } from './TenderCalcsScreen';
import { TokensTab } from './TokensTab';

const push = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => '/projects/p-1/calcs',
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock('@/lib/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof queries>()),
  useMeta: vi.fn(),
  useFeatures: vi.fn(),
  useProject: vi.fn(),
}));

vi.mock('@/lib/session', async (importOriginal) => ({
  ...(await importOriginal<typeof session>()),
  useHasPermission: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  listTenderCalcs: vi.fn(),
  listTenderCalcVersions: vi.fn(),
  readTenderCalcVersion: vi.fn(),
  withdrawTenderCalcVersion: vi.fn(),
  listTenderBaseReleases: vi.fn(),
  listTenderBaseCandidates: vi.fn(),
  createTenderBaseRelease: vi.fn(),
  revokeTenderBaseRelease: vi.fn(),
  listPersonalTokens: vi.fn(),
  createPersonalToken: vi.fn(),
  revokePersonalToken: vi.fn(),
  listRevisionSheets: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const summary = (
  patch: Partial<TenderCalcVersionSummaryRead> = {},
): TenderCalcVersionSummaryRead => ({
  id: 'v-2',
  calc_id: 'calc-1',
  number: 2,
  label: 'v2',
  message: 'Перестроены лучи',
  author: 'Кузьмин А.А.',
  uploaded_at: '2026-11-16T12:00:00Z',
  uploaded_by_name: 'Кузьмин',
  base_release_id: 'rel-1',
  base_release_number: 1,
  quantity_rows: 2,
  question_count: 1,
  view_count: 1,
  warning_count: 2,
  status: 'active',
  ...patch,
});

const calc: TenderCalcRead = {
  id: 'calc-1',
  project_id: 'p-1',
  discipline: 'mech',
  system: 'heating',
  title: 'Отопление жилой части',
  created_at: '2026-11-15T10:00:00Z',
  version_count: 2,
  active_version: summary(),
};

const version: TenderCalcVersionRead = {
  ...summary(),
  discipline: 'mech',
  system: 'heating',
  title: 'Отопление жилой части',
  package_sha256: 'abcdef0123456789',
  prev_version_id: 'v-1',
  producer: { skill: 'raschet-otopleniya' },
  fit: [{ view_key: 'rev:81:0', method: 'axes_affine', axes: ['1', 'А'], rms_mm: 12, max_mm: 31 }],
  quantities: [
    {
      code: 'OV-1',
      name: 'Труба PE-Xa 16',
      unit: 'м',
      qty: 120,
      group: 'Трубы',
      basis: 'geometry',
      note: null,
      view_keys: [],
      per_floor: [
        { floor: '4', qty: 60 },
        { floor: '5', qty: 60 },
      ],
    },
    {
      code: 'OV-2',
      name: 'Конвектор',
      unit: 'шт',
      qty: 8,
      group: 'Приборы',
      basis: 'schedule',
      note: null,
      view_keys: [],
      per_floor: [],
    },
  ],
  diff: [
    {
      code: 'OV-1',
      name: 'Труба PE-Xa 16',
      unit: 'м',
      qty: 120,
      qty_prev: 100,
      delta: 20,
      status: 'changed',
    },
    { code: 'OV-2', name: 'Конвектор', unit: 'шт', qty: 8, qty_prev: 8, delta: 0, status: 'same' },
    {
      code: 'OV-3',
      name: 'Клапан',
      unit: 'шт',
      qty: null,
      qty_prev: 4,
      delta: -4,
      status: 'removed',
    },
  ],
  questions: [{ text: 'Шаг конвекторов не задан', ref: 'АР1.1 л.82', ids: ['KV-1'] }],
  warnings: [{ code: 'FIT_WARN', message: 'Привязка 31 мм', view_key: 'rev:81:0' }],
  views: [
    {
      view_key: 'rev:81:0',
      revision_id: 'rev-81',
      page_index: 81,
      view: 0,
      floors: ['4', '5'],
      dxf_sha256: 'x',
      polylines: 10,
      elements: 3,
      base_stale: true,
    },
  ],
};

const release = (patch: Partial<TenderBaseReleaseRead> = {}): TenderBaseReleaseRead => ({
  id: 'rel-1',
  project_id: 'p-1',
  number: 3,
  released_at: '2026-11-16T10:00:00Z',
  released_by_name: 'Координатор',
  comment: 'Корп. 9',
  include_dxf: true,
  manifest_sha256: 'm',
  package_sha256: 'p',
  size_bytes: 2048,
  revoked_at: null,
  revoked_by_name: null,
  views: [],
  ...patch,
});

const candidates: TenderBaseCandidatesRead = {
  warnings: [],
  candidates: [
    {
      alignment: 'reference',
      base_z_mm: 0,
      corps: '9',
      dir: 'd1',
      document_id: null,
      document_title: 'АР1.1',
      dxf_sha256: null,
      floors: ['1'],
      group_key: '9|3',
      group_label: 'К9',
      label: 'План 1',
      offset_mm: [0, 0],
      page_index: 0,
      problems: [],
      ready: true,
      revision_id: 'r',
      section: '3',
      view: 0,
      view_key: 'r:0:0',
    },
    {
      alignment: 'none',
      base_z_mm: 3000,
      corps: '9',
      dir: 'd2',
      document_id: null,
      document_title: 'АР1.2',
      dxf_sha256: null,
      floors: ['2'],
      group_key: '9|3',
      group_label: 'К9',
      label: 'План 2',
      offset_mm: [0, 0],
      page_index: 1,
      problems: [],
      ready: true,
      revision_id: 'r',
      section: '3',
      view: 0,
      view_key: 'r:1:0',
    },
    {
      alignment: 'none',
      base_z_mm: 6000,
      corps: '9',
      dir: 'd3',
      document_id: null,
      document_title: 'АР1.3',
      dxf_sha256: null,
      floors: ['3'],
      group_key: '9|3',
      group_label: 'К9',
      label: 'План 3',
      offset_mm: [0, 0],
      page_index: 2,
      problems: ['кадр вида не подтверждён'],
      ready: false,
      revision_id: 'r',
      section: '3',
      view: 0,
      view_key: 'r:2:0',
    },
  ],
};

const permissions = (granted: readonly string[]) =>
  vi.mocked(session.useHasPermission).mockImplementation((name) => granted.includes(name));

const mountWith = (ui: React.ReactElement) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(queries.useMeta).mockReturnValue({ isSuccess: true } as never);
  vi.mocked(queries.useFeatures).mockReturnValue({ 'tender.exchange': true });
  vi.mocked(queries.useProject).mockReturnValue({ data: { name: 'Объект' } } as never);
  vi.mocked(client.listTenderCalcs).mockImplementation(() => ok({ calcs: [calc] }));
  vi.mocked(client.listTenderCalcVersions).mockImplementation(() =>
    ok({
      versions: [summary(), summary({ id: 'v-1', number: 1, label: 'v1', status: 'withdrawn' })],
    }),
  );
  vi.mocked(client.readTenderCalcVersion).mockImplementation(() => ok(version));
  vi.mocked(client.listTenderBaseReleases).mockImplementation(() => ok([release()]));
  vi.mocked(client.listTenderBaseCandidates).mockImplementation(() => ok(candidates));
  vi.mocked(client.listPersonalTokens).mockImplementation(() => ok([]));
});

describe('страница «Расчёты»', () => {
  it('флаг закрыт — заглушка, запросов нет', () => {
    vi.mocked(queries.useFeatures).mockReturnValue({});
    permissions(['tender.calc.read']);
    mountWith(<TenderCalcsScreen projectId="p-1" />);
    expect(screen.getByText('Страница не найдена')).toBeInTheDocument();
    expect(client.listTenderCalcs).not.toHaveBeenCalled();
  });

  it('без права чтения остаётся только раздел токенов', async () => {
    permissions([]);
    mountWith(<TenderCalcsScreen projectId="p-1" />);
    expect(await screen.findByText(/Токенов пока нет/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'База объекта' })).not.toBeInTheDocument();
    expect(client.listTenderCalcs).not.toHaveBeenCalled();
  });
});

describe('раздел «Расчёты»', () => {
  it('карточка: раздел, система по-русски, версия, автор, база, предупреждения, новая база', async () => {
    permissions(['tender.calc.read']);
    vi.mocked(client.listTenderBaseReleases).mockImplementation(() => ok([release({ number: 4 })]));
    const onNavigate = vi.fn();
    mountWith(<CalcsTab projectId="p-1" calcId={null} versionId={null} onNavigate={onNavigate} />);
    const card = await screen.findByRole('button', { name: /Отопление жилой части/ });
    expect(screen.getByText('Механика')).toBeInTheDocument();
    expect(within(card).getByText('Отопление')).toBeInTheDocument();
    expect(within(card).getByText(/№2 · v2/)).toBeInTheDocument();
    expect(within(card).getByText(/Кузьмин А\.А\./)).toBeInTheDocument();
    expect(within(card).getByText('база #1')).toBeInTheDocument();
    expect(within(card).getByText(/предупреждений: 2/)).toBeInTheDocument();
    await waitFor(() => expect(within(card).getByText('новая база #4')).toBeInTheDocument());
    await userEvent.click(card);
    expect(onNavigate).toHaveBeenCalledWith({ calc: 'calc-1', version: null });
  });

  it('история: отозванная версия зачёркнута, клик открывает версию', async () => {
    permissions(['tender.calc.read']);
    const onNavigate = vi.fn();
    mountWith(
      <CalcsTab projectId="p-1" calcId="calc-1" versionId={null} onNavigate={onNavigate} />,
    );
    const withdrawn = await screen.findByRole('button', { name: 'Открыть версию №1' });
    expect(withdrawn.closest('td')).toHaveClass('line-through');
    await userEvent.click(screen.getByRole('button', { name: 'Открыть версию №2' }));
    expect(onNavigate).toHaveBeenCalledWith({ version: 'v-2' });
  });

  it('версия: объёмы с разницей, этажи, вопросы, привязка, виды, отзыв по праву', async () => {
    permissions(['tender.calc.read', 'tender.calc.withdraw']);
    vi.mocked(client.withdrawTenderCalcVersion).mockImplementation(() =>
      ok(summary({ status: 'withdrawn' })),
    );
    mountWith(<CalcsTab projectId="p-1" calcId="calc-1" versionId="v-2" onNavigate={vi.fn()} />);
    expect(await screen.findByText(/Труба PE-Xa 16/)).toBeInTheDocument();
    expect(screen.getByText('+20')).toBeInTheDocument();
    expect(screen.getByText('−4')).toBeInTheDocument();
    expect(screen.getByText('Удалено относительно прошлой версии')).toBeInTheDocument();
    expect(screen.getAllByText('база устарела').length).toBeGreaterThan(0);
    expect(screen.getByText('Шаг конвекторов не задан')).toBeInTheDocument();
    expect(screen.getByText(/rms 12 мм/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Скачать пакет' })).toHaveAttribute(
      'href',
      expect.stringContaining('/tender/calc-versions/v-2/package'),
    );

    // «только изменения»: строка без разницы уходит
    expect(screen.getByText('Конвектор')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: /Только изменения/ }));
    expect(screen.queryByText('Конвектор')).not.toBeInTheDocument();

    // раскрытие по этажам
    await userEvent.click(screen.getByRole('button', { name: /Труба PE-Xa 16/ }));
    expect(screen.getByText('Этаж 4')).toBeInTheDocument();

    // отзыв с подтверждением
    await userEvent.click(screen.getByRole('button', { name: 'Отозвать версию' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Отозвать' }));
    await waitFor(() =>
      expect(client.withdrawTenderCalcVersion).toHaveBeenCalledWith(
        expect.objectContaining({ path: { project_id: 'p-1', version_id: 'v-2' } }),
      ),
    );
  });

  it('открыть на листе: переход с параметром tender', async () => {
    permissions(['tender.calc.read']);
    vi.mocked(client.listRevisionSheets).mockImplementation(() =>
      ok({ items: [{ page_index: 81 }] }),
    );
    mountWith(<CalcsTab projectId="p-1" calcId="calc-1" versionId="v-2" onNavigate={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Открыть на листе' }));
    await waitFor(() => expect(push).toHaveBeenCalled());
    const href = new URL(String(push.mock.calls[0]?.[0]), 'http://x');
    expect(href.pathname).toBe('/projects/p-1/workspace');
    expect(href.searchParams.get('tender')).toBe('calc-1');
    expect(href.searchParams.get('revision')).toBe('rev-81');
  });

  it('без права отзыва кнопки нет', async () => {
    permissions(['tender.calc.read']);
    mountWith(<CalcsTab projectId="p-1" calcId="calc-1" versionId="v-2" onNavigate={vi.fn()} />);
    await screen.findByText(/Труба PE-Xa 16/);
    expect(screen.queryByRole('button', { name: 'Отозвать версию' })).not.toBeInTheDocument();
  });
});

describe('раздел «База объекта»', () => {
  it('выпуски и кнопки по праву; без права «Выпустить» нет', async () => {
    permissions(['tender.calc.read']);
    mountWith(<BaseTab projectId="p-1" />);
    expect(await screen.findByText('#3')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Скачать' })).toHaveAttribute(
      'href',
      expect.stringContaining('/tender/base/releases/rel-1/download'),
    );
    expect(screen.queryByRole('button', { name: 'Выпустить базу' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отозвать' })).not.toBeInTheDocument();
  });

  it('окно выпуска: по умолчанию готовые и совмещённые, неготовый отключён', async () => {
    permissions(['tender.calc.read', 'tender.base.release']);
    vi.mocked(client.createTenderBaseRelease).mockImplementation(() => ok(release({ number: 4 })));
    mountWith(<BaseTab projectId="p-1" />);
    await userEvent.click(await screen.findByRole('button', { name: 'Выпустить базу' }));
    const dialog = await screen.findByRole('dialog');
    const first = await within(dialog).findByRole('checkbox', { name: 'Включить: Этажи 1' });
    expect(first).toBeChecked();
    expect(within(dialog).getByRole('checkbox', { name: 'Включить: Этажи 2' })).not.toBeChecked();
    expect(within(dialog).getByRole('checkbox', { name: 'Включить: Этажи 3' })).toBeDisabled();
    expect(within(dialog).getByText('не совмещён с осями здания')).toBeInTheDocument();
    expect(within(dialog).getByText('кадр вида не подтверждён')).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'С DXF планов' }));
    await userEvent.type(within(dialog).getByRole('textbox', { name: 'Комментарий' }), 'Корп. 9');
    await userEvent.click(within(dialog).getByRole('button', { name: /Выпустить \(1\)/ }));
    await waitFor(() =>
      expect(client.createTenderBaseRelease).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { view_keys: ['r:0:0'], include_dxf: true, comment: 'Корп. 9' },
        }),
      ),
    );
  });
});

describe('раздел «Доступ (токены)»', () => {
  it('токен показывается один раз после создания', async () => {
    const created: PersonalTokenCreated = {
      id: 't-1',
      name: 'Ноутбук',
      prefix: 'qtr_ab',
      token: 'qtr_abcdef-секрет',
      active: true,
      created_at: '2026-11-16T10:00:00Z',
      expires_at: null,
      last_used_at: null,
      revoked_at: null,
      scopes: ['tender'],
    };
    vi.mocked(client.createPersonalToken).mockImplementation(() => ok(created));
    mountWith(<TokensTab />);
    await userEvent.click(await screen.findByRole('button', { name: 'Создать токен' }));
    const dialog = await screen.findByRole('dialog');
    await userEvent.type(
      within(dialog).getByRole('textbox', { name: 'Название токена' }),
      'Ноутбук',
    );
    await userEvent.click(within(dialog).getByRole('button', { name: 'Создать' }));
    expect(await within(dialog).findByDisplayValue('qtr_abcdef-секрет')).toBeInTheDocument();
    expect(within(dialog).getByRole('alert')).toBeInTheDocument();
    expect(client.createPersonalToken).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { name: 'Ноутбук', expires_in_days: 90, scopes: ['tender'] },
      }),
    );
    await userEvent.click(within(dialog).getByRole('button', { name: 'Готово' }));
    await waitFor(() =>
      expect(screen.queryByDisplayValue('qtr_abcdef-секрет')).not.toBeInTheDocument(),
    );
  });

  it('список токенов и отзыв', async () => {
    vi.mocked(client.listPersonalTokens).mockImplementation(() =>
      ok([
        {
          id: 't-1',
          name: 'Ноутбук',
          prefix: 'qtr_ab',
          scopes: ['read', 'upload'],
          active: true,
          created_at: '2026-11-16T10:00:00Z',
          expires_at: null,
          last_used_at: null,
          revoked_at: null,
        },
      ]),
    );
    vi.mocked(client.revokePersonalToken).mockImplementation(() => ok(undefined));
    mountWith(<TokensTab />);
    expect(await screen.findByText('Ноутбук')).toBeInTheDocument();
    expect(screen.getByText('не использовался')).toBeInTheDocument();
    expect(
      screen.getByText('Только чтение (агенты), Загрузка документов и модели'),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Отозвать' }));
    await waitFor(() =>
      expect(client.revokePersonalToken).toHaveBeenCalledWith(
        expect.objectContaining({ path: { token_id: 't-1' } }),
      ),
    );
  });
});
