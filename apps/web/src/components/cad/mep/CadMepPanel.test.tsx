import type { CadDecisionRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { IWorkspaceCadMep } from '@/components/workspace/cad/types';
import { CANDIDATE_SCHEMA } from '@/lib/cad/mep-candidate';

const api = vi.hoisted(() => ({
  approveCadView: vi.fn(),
  createCadMepRoutes: vi.fn(),
  acceptCadMepRoutes: vi.fn(),
  downloadCadArtifact: vi.fn(),
  revokeCadDecision: vi.fn(),
  recomputeCadMepRoutes: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { CadMepPanel } from './CadMepPanel';

const PARENT = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'job-parent',
  attempt: 2,
  pageIndex: 80,
  view: 1,
};
const ROUTE_PARAMS = { ...PARENT, jobId: 'job-route', attempt: 1 };

const decision = (kind: 'view_approval' | 'mep_acceptance'): CadDecisionRead => ({
  id: 'd1',
  kind,
  job_id: 'job',
  attempt: 1,
  page_index: 80,
  view: 1,
  artifact_sha256: 'x'.repeat(64),
  decided_by: 'u1',
  decided_by_name: 'Инженер Иванов',
  decided_at: '2026-11-10T10:00:00Z',
  comment: null,
  revoked_at: null,
  revoked_by: null,
  revoked_by_name: null,
  revoke_reason: null,
});

const candidate = {
  schema: CANDIDATE_SCHEMA,
  status: 'candidate_requires_review',
  elevation: {
    floor_elevation_mm: { value: 10000, source: 'operator' },
    floor_height_mm: { value: 3000, source: 'operator' },
    sheet_marks_mm: [],
  },
  assumptions: [{ name: 'z_heat_mm', value: 50, unit: 'мм', note: 'подводка' }],
  apartments: [
    { idx: 1, number: 'Кв 1', lengths_own_lines: { heating: { plan_m: 4, len3d_m: 5 } } },
  ],
  routes: {
    by_layer: { 'M-OV-T1': { plan_m: 2, len3d_m: 2.5, polylines: 1 } },
    by_system: { heating: { plan_m: 4, len3d_m: 5 } },
    totals: { plan_m: 4, len3d_m: 5 },
  },
  issues: [{ code: 'elevation_mismatch', message: 'отметка не найдена', apartment: null }],
  notes: [],
};

const mep = (patch: Partial<IWorkspaceCadMep> = {}): IWorkspaceCadMep => ({
  parent: PARENT,
  approval: null,
  revokedDecisions: [],
  routeJobs: [],
  route: null,
  openRemarks: 0,
  onSelectRoute: vi.fn(),
  ...patch,
});

const mount = (value: IWorkspaceCadMep) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CadMepPanel {...value} />
    </QueryClientProvider>,
  );
};

const routeState = (patch: Partial<NonNullable<IWorkspaceCadMep['route']>> = {}) => ({
  summaryId: 'job-route',
  job: {
    status: 'succeeded',
    attempt: 1,
    stage: null,
    error_code: null,
    error_message: null,
    floor_elevation_mm: 10000,
    floor_height_mm: 3000,
    generator_version: 'cad_mep.v2',
    floor_elevation_source: 'operator',
    floor_height_source: 'operator',
    approval_revoked: false,
    result_attempt: 1,
    route_attempts: [],
  } as unknown as NonNullable<IWorkspaceCadMep['route']>['job'],
  params: ROUTE_PARAMS,
  acceptance: null,
  revokedDecisions: [],
  error: null,
  ...patch,
});

const failure = (code: string) => ({ detail: { code } });

beforeEach(() => {
  vi.clearAllMocks();
  api.downloadCadArtifact.mockResolvedValue({ data: candidate });
});

describe('вкладка «Трассы»: одобрение вида', () => {
  it('открытых замечаний нет - вид можно одобрить', async () => {
    api.approveCadView.mockResolvedValue({ data: decision('view_approval') });
    mount(mep());
    const button = screen.getByRole('button', { name: 'Одобрить вид' });
    expect(button).toBeEnabled();
    fireEvent.click(button);
    await waitFor(() => expect(api.approveCadView).toHaveBeenCalledTimes(1));
    expect(api.approveCadView.mock.calls[0]?.[0]).toMatchObject({
      path: { job_id: 'job-parent', page_index: 80, view: 1 },
      body: { attempt: 2 },
    });
  });

  it('открытые замечания блокируют кнопку и называют причину', () => {
    mount(mep({ openRemarks: 3 }));
    expect(screen.getByRole('button', { name: 'Одобрить вид' })).toBeDisabled();
    expect(screen.getByText(/открытые замечания \(3\)/)).toBeInTheDocument();
  });

  it('замечания ещё не прочитаны - кнопка заблокирована', () => {
    mount(mep({ openRemarks: null }));
    expect(screen.getByRole('button', { name: 'Одобрить вид' })).toBeDisabled();
  });

  it('отказ 409 показывается русским текстом', async () => {
    api.approveCadView.mockRejectedValue(failure('CAD_OPEN_REMARKS'));
    mount(mep());
    fireEvent.click(screen.getByRole('button', { name: 'Одобрить вид' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Есть открытые замечания: закройте их или отметьте проверенными.',
    );
  });

  it('одобренный вид показывает, кто и когда, и кнопки одобрения нет', () => {
    mount(mep({ approval: decision('view_approval') }));
    expect(screen.queryByRole('button', { name: 'Одобрить вид' })).toBeNull();
    expect(screen.getByTestId('mep-decision')).toHaveTextContent('Вид одобрен');
    expect(screen.getByTestId('mep-decision')).toHaveTextContent('Инженер Иванов');
  });
});

describe('вкладка «Трассы»: построение', () => {
  it('без одобрения формы нет, есть подсказка', () => {
    mount(mep());
    expect(screen.queryByRole('form', { name: 'Построить трассы' })).toBeNull();
    expect(screen.getByText('Трассы строятся только по одобренному виду.')).toBeInTheDocument();
  });

  it('по умолчанию полей нет: отметка и высота определяются по документации', async () => {
    api.createCadMepRoutes.mockResolvedValue({ data: { job_id: 'job-route' } });
    const value = mep({ approval: decision('view_approval') });
    mount(value);
    expect(
      screen.getByText('Отметка и высота этажа будут определены по документации.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('textbox', { name: 'Отметка пола, мм' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Построить трассы' }));
    await waitFor(() => expect(value.onSelectRoute).toHaveBeenCalledWith('job-route'));
    expect(api.createCadMepRoutes.mock.calls[0]?.[0]).toMatchObject({
      body: { attempt: 2, floor_elevation_mm: null, floor_height_mm: null },
    });
  });

  it('предупреждение постановки о неоднозначной высоте по разрезам показывается текстом', async () => {
    api.createCadMepRoutes.mockResolvedValue({
      data: { job_id: 'job-route', warnings: ['section_level_ambiguous'] },
    });
    const value = mep({ approval: decision('view_approval') });
    mount(value);
    fireEvent.click(screen.getByRole('button', { name: 'Построить трассы' }));
    expect(
      await screen.findByText(/несколько принятых уровней с разной высотой — уточните в «Разрезах»/),
    ).toBeInTheDocument();
  });

  it('неверный ручной ввод не уходит на сервер', () => {
    mount(mep({ approval: decision('view_approval') }));
    fireEvent.click(screen.getByRole('button', { name: 'Задать вручную' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Высота этажа, мм' }), {
      target: { value: '1500' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Построить трассы' }));
    expect(api.createCadMepRoutes).not.toHaveBeenCalled();
    expect(screen.getByText(/Высота этажа вне пределов/)).toBeInTheDocument();
  });

  it('у полей есть крестик очистки', () => {
    mount(mep({ approval: decision('view_approval') }));
    fireEvent.click(screen.getByRole('button', { name: 'Задать вручную' }));
    const field = screen.getByRole('textbox', { name: 'Отметка пола, мм' });
    fireEvent.change(field, { target: { value: '47600' } });
    fireEvent.click(screen.getByRole('button', { name: 'Очистить: Отметка пола, мм' }));
    expect(field).toHaveValue('');
  });

  it('вводы уходят целыми мм, созданное задание открывается', async () => {
    api.createCadMepRoutes.mockResolvedValue({ data: { job_id: 'job-route' } });
    const value = mep({ approval: decision('view_approval') });
    mount(value);
    fireEvent.click(screen.getByRole('button', { name: 'Задать вручную' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Отметка пола, мм' }), {
      target: { value: '47600' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Высота этажа, мм' }), {
      target: { value: '3300' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Построить трассы' }));
    await waitFor(() => expect(value.onSelectRoute).toHaveBeenCalledWith('job-route'));
    expect(api.createCadMepRoutes.mock.calls[0]?.[0]).toMatchObject({
      path: { job_id: 'job-parent', page_index: 80, view: 1 },
      body: { attempt: 2, floor_elevation_mm: 47600, floor_height_mm: 3300 },
    });
  });

  it('отказ «вид не одобрен» (409) показан текстом', async () => {
    api.createCadMepRoutes.mockRejectedValue(failure('CAD_VIEW_NOT_APPROVED'));
    mount(mep({ approval: decision('view_approval') }));
    fireEvent.click(screen.getByRole('button', { name: 'Задать вручную' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Отметка пола, мм' }), {
      target: { value: '1000' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: 'Высота этажа, мм' }), {
      target: { value: '3000' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Построить трассы' }));
    expect(await screen.findByText('Вид не одобрен: сначала одобрите его.')).toBeInTheDocument();
  });
});

describe('вкладка «Трассы»: выбранные трассы', () => {
  const withRoute = (patch: Partial<IWorkspaceCadMep> = {}, route = routeState()) =>
    mep({
      approval: decision('view_approval'),
      routeJobs: [
        {
          job_id: 'job-route',
          status: 'succeeded',
          attempt: 1,
          created_at: '2026-11-10T10:00:00Z',
          finished_at: null,
          error_code: null,
          floor_elevation_mm: 10000,
          floor_height_mm: 3000,
          generator_version: 'cad_mep.v2',
          accepted: false,
          approval_id: 'd1',
          approval_revoked: false,
        },
      ],
      route,
      ...patch,
    });

  it('список трасс открывает выбранное задание', () => {
    const value = mep({
      approval: decision('view_approval'),
      routeJobs: withRoute().routeJobs,
    });
    mount(value);
    fireEvent.click(screen.getByRole('button', { name: /пол 10000/ }));
    expect(value.onSelectRoute).toHaveBeenCalledWith('job-route');
  });

  it('показывает длины по системам и квартирам, проблемы и допущения', async () => {
    mount(withRoute());
    expect(await screen.findByTestId('mep-candidate')).toBeInTheDocument();
    expect(screen.getByText('Итого по системам')).toBeInTheDocument();
    expect(screen.getByText('Квартира Кв 1')).toBeInTheDocument();
    expect(screen.getByText('elevation_mismatch')).toBeInTheDocument();
    expect(screen.getByText(/Допущения \(1\)/)).toBeInTheDocument();
    expect(api.downloadCadArtifact.mock.calls[0]?.[0]).toMatchObject({
      path: { job_id: 'job-route', name: 'views/p081_v01/candidate.json' },
    });
  });

  it('файл не по схеме - понятная ошибка вместо итогов', async () => {
    api.downloadCadArtifact.mockResolvedValue({ data: { schema: 'другая' } });
    mount(withRoute());
    expect(await screen.findByText(/не соответствует схеме/)).toBeInTheDocument();
  });

  it('принять можно без открытых замечаний; до принятия скачивания нет', () => {
    mount(withRoute({ openRemarks: 0 }));
    expect(screen.getByRole('button', { name: 'Принять трассы (этаж целиком)' })).toBeEnabled();
    expect(screen.queryByRole('link', { name: 'Скачать 3D DXF' })).toBeNull();
  });

  it('открытые замечания на трассах блокируют принятие', () => {
    mount(withRoute({ openRemarks: 2 }));
    expect(screen.getByRole('button', { name: 'Принять трассы (этаж целиком)' })).toBeDisabled();
    expect(screen.getByText(/открытые замечания \(2\)/)).toBeInTheDocument();
  });

  it('принятие отправляет попытку route-задания', async () => {
    api.acceptCadMepRoutes.mockResolvedValue({ data: decision('mep_acceptance') });
    mount(withRoute());
    fireEvent.click(screen.getByRole('button', { name: 'Принять трассы (этаж целиком)' }));
    await waitFor(() => expect(api.acceptCadMepRoutes).toHaveBeenCalledTimes(1));
    expect(api.acceptCadMepRoutes.mock.calls[0]?.[0]).toMatchObject({
      path: { job_id: 'job-route' },
      body: { attempt: 1 },
    });
  });

  it('отказ принятия (409) показан текстом', async () => {
    api.acceptCadMepRoutes.mockRejectedValue(failure('CAD_ALREADY_DECIDED'));
    mount(withRoute());
    fireEvent.click(screen.getByRole('button', { name: 'Принять трассы (этаж целиком)' }));
    expect(await screen.findByText('Решение по этому виду уже принято.')).toBeInTheDocument();
  });

  it('после принятия видно, кто принял, и есть ссылка «Скачать 3D DXF»', () => {
    mount(withRoute({}, routeState({ acceptance: decision('mep_acceptance') })));
    expect(screen.queryByRole('button', { name: 'Принять трассы (этаж целиком)' })).toBeNull();
    const link = screen.getByRole('link', { name: 'Скачать 3D DXF' });
    expect(link.getAttribute('href')).toContain(
      '/revisions/r1/cad/job-route/artifacts/views/p081_v01/mep_routes.dxf',
    );
    expect(link).toHaveAttribute('download');
    expect(screen.getByText('Трассы приняты (этаж целиком)')).toBeInTheDocument();
  });

  it('идущее задание: ход, без итогов и принятия', () => {
    mount(
      withRoute(
        {},
        routeState({
          params: null,
          job: { status: 'running', attempt: 1, stage: 'route' } as unknown as NonNullable<
            IWorkspaceCadMep['route']
          >['job'],
        }),
      ),
    );
    expect(screen.getByText(/Трассы строятся \(route\)/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Принять трассы/ })).toBeNull();
    expect(api.downloadCadArtifact).not.toHaveBeenCalled();
  });

  it('отказавшее задание показывает код ошибки', () => {
    mount(
      withRoute(
        {},
        routeState({
          params: null,
          job: {
            status: 'failed',
            attempt: 1,
            error_code: 'CAD_MEP_NOT_BUILT',
            error_message: null,
          } as unknown as NonNullable<IWorkspaceCadMep['route']>['job'],
        }),
      ),
    );
    expect(screen.getByRole('alert')).toHaveTextContent('не построены');
  });

  it('«Закрыть трассы» возвращает вид без трасс', () => {
    const value = withRoute();
    mount(value);
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть трассы' }));
    expect(value.onSelectRoute).toHaveBeenCalledWith(null);
  });
});

describe('вкладка «Трассы»: отзыв решений', () => {
  it('одобрение отзывается с подтверждением и причиной', async () => {
    api.revokeCadDecision.mockResolvedValue({ data: decision('view_approval') });
    mount(mep({ approval: decision('view_approval') }));
    fireEvent.click(screen.getByRole('button', { name: 'Отозвать одобрение' }));
    expect(api.revokeCadDecision).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(screen.getByRole('textbox', { name: 'Причина отзыва' }), {
      target: { value: 'Кликнул случайно' },
    });
    fireEvent.click(screen.getAllByRole('button', { name: 'Отозвать' }).at(-1) as HTMLElement);
    await waitFor(() => expect(api.revokeCadDecision).toHaveBeenCalledTimes(1));
    expect(api.revokeCadDecision.mock.calls[0]?.[0]).toMatchObject({
      path: { decision_id: 'd1' },
      body: { reason: 'Кликнул случайно' },
    });
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
  });

  it('причина необязательна', async () => {
    api.revokeCadDecision.mockResolvedValue({ data: decision('view_approval') });
    mount(mep({ approval: decision('view_approval') }));
    fireEvent.click(screen.getByRole('button', { name: 'Отозвать одобрение' }));
    await screen.findByRole('dialog');
    fireEvent.click(screen.getAllByRole('button', { name: 'Отозвать' }).at(-1) as HTMLElement);
    await waitFor(() => expect(api.revokeCadDecision).toHaveBeenCalledTimes(1));
    expect(api.revokeCadDecision.mock.calls[0]?.[0]).toMatchObject({ body: { reason: null } });
  });

  it('отказ сервера показан в окне', async () => {
    api.revokeCadDecision.mockRejectedValue(failure('CAD_ROUTES_ACCEPTED'));
    mount(mep({ approval: decision('view_approval') }));
    fireEvent.click(screen.getByRole('button', { name: 'Отозвать одобрение' }));
    await screen.findByRole('dialog');
    fireEvent.click(screen.getAllByRole('button', { name: 'Отозвать' }).at(-1) as HTMLElement);
    expect(await screen.findByText(/сначала отзовите принятие/)).toBeInTheDocument();
  });

  it('пока трассы приняты по этому одобрению, отзыв одобрения закрыт', () => {
    mount(
      mep({
        approval: decision('view_approval'),
        routeJobs: [
          {
            job_id: 'job-route',
            status: 'succeeded',
            attempt: 1,
            created_at: '2026-11-10T10:00:00Z',
            finished_at: null,
            error_code: null,
            floor_elevation_mm: null,
            floor_height_mm: null,
            generator_version: 'cad_mep.v2',
            accepted: true,
            approval_id: 'd1',
            approval_revoked: false,
          },
        ],
      }),
    );
    expect(screen.getByRole('button', { name: 'Отозвать одобрение' })).toBeDisabled();
    expect(screen.getByText(/сначала отзовите принятие/)).toBeInTheDocument();
  });

  it('после отзыва снова доступно «Одобрить вид», история отзывов видна', () => {
    const revoked = {
      ...decision('view_approval'),
      revoked_at: '2026-11-10T11:00:00Z',
      revoked_by_name: 'Инженер Петров',
      revoke_reason: 'Кликнул случайно',
    };
    mount(mep({ approval: null, revokedDecisions: [revoked] }));
    expect(screen.getByRole('button', { name: 'Одобрить вид' })).toBeEnabled();
    expect(screen.getByTestId('mep-revoked')).toHaveTextContent('Инженер Петров');
    expect(screen.getByTestId('mep-revoked')).toHaveTextContent('Кликнул случайно');
  });

  it('принятие отзывается кнопкой «Отозвать принятие»', async () => {
    api.revokeCadDecision.mockResolvedValue({ data: decision('mep_acceptance') });
    mount(
      mep({
        approval: decision('view_approval'),
        route: routeState({ acceptance: decision('mep_acceptance') }),
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Отозвать принятие' }));
    await screen.findByRole('dialog');
    fireEvent.click(screen.getAllByRole('button', { name: 'Отозвать' }).at(-1) as HTMLElement);
    await waitFor(() => expect(api.revokeCadDecision).toHaveBeenCalledTimes(1));
  });

  it('трассы с отозванным одобрением: пометка и «Принять» закрыто с причиной', () => {
    const route = routeState();
    mount(
      mep({
        approval: null,
        route: {
          ...route,
          job: { ...route.job, approval_revoked: true } as unknown as typeof route.job,
        },
      }),
    );
    expect(screen.getByTestId('mep-approval-revoked')).toHaveTextContent('Одобрение вида отозвано');
    expect(screen.getByRole('button', { name: 'Принять трассы (этаж целиком)' })).toBeDisabled();
    expect(screen.getAllByText(/принять эти трассы нельзя/).length).toBeGreaterThan(0);
  });
});

describe('вкладка «Трассы»: пересчёт и история', () => {
  const routeWith = (job: Record<string, unknown>, patch: Record<string, unknown> = {}) => {
    const base = routeState();
    return mep({
      approval: decision('view_approval'),
      route: {
        ...base,
        job: { ...base.job, ...job } as unknown as typeof base.job,
        ...patch,
      },
    });
  };

  it('форма показывает текущие значения с источником; пересчёт - с подтверждением', async () => {
    api.recomputeCadMepRoutes.mockResolvedValue({ data: { job_id: 'job-route' } });
    mount(
      routeWith({
        floor_elevation_mm: 47600,
        floor_elevation_source: 'observed',
        floor_height_mm: 3300,
        floor_height_source: 'derived',
        route_attempts: [
          { attempt: 1, status: 'succeeded', requested_elevation_mm: null, requested_height_mm: null },
        ],
      }),
    );
    expect(screen.getByText(/47600 мм \(из документации\)/)).toBeInTheDocument();
    expect(screen.getByText(/3300 мм \(по соседним этажам\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Пересчитать…' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Отметка пола, мм' }), {
      target: { value: '50900' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Пересчитать' }));
    expect(api.recomputeCadMepRoutes).not.toHaveBeenCalled();
    await screen.findByRole('dialog');
    fireEvent.click(screen.getAllByRole('button', { name: 'Пересчитать' }).at(-1) as HTMLElement);
    await waitFor(() => expect(api.recomputeCadMepRoutes).toHaveBeenCalledTimes(1));
    expect(api.recomputeCadMepRoutes.mock.calls[0]?.[0]).toMatchObject({
      path: { job_id: 'job-route' },
      body: { floor_elevation_mm: 50900, floor_height_mm: null },
    });
  });

  it('те же значения, что у текущей попытки: пересчёт доступен с подсказкой (решает сервер)', () => {
    mount(
      routeWith({
        route_attempts: [
          { attempt: 1, status: 'succeeded', requested_elevation_mm: 10000, requested_height_mm: 3000 },
        ],
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Пересчитать…' }));
    expect(screen.getByRole('button', { name: 'Пересчитать' })).toBeEnabled();
    expect(screen.getByText(/только если обновился/)).toBeInTheDocument();
  });

  it('приняты, считаются или одобрение отозвано - пересчёт закрыт с причиной', () => {
    mount(routeWith({}, { acceptance: decision('mep_acceptance') }));
    expect(screen.getByRole('button', { name: 'Пересчитать…' })).toBeDisabled();
    expect(screen.getByText(/сначала отзовите принятие/)).toBeInTheDocument();
  });

  it('«не найдено в документации»: подсказка и раскрытые поля', () => {
    mount(
      routeWith(
        { status: 'failed', error_code: 'CAD_ELEVATION_NOT_FOUND', route_attempts: [] },
        { params: null },
      ),
    );
    expect(screen.getByText(/задайте отметку и высоту вручную/, { selector: '[role="note"]' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Отметка пола, мм' })).toBeInTheDocument();
  });

  it('история расчётов: попытки с запросом и итогом, прошлую можно открыть', async () => {
    mount(
      routeWith({
        attempt: 2,
        result_attempt: 2,
        route_attempts: [
          {
            attempt: 1,
            status: 'succeeded',
            requested_elevation_mm: null,
            requested_height_mm: null,
            requested_at: '2026-11-10T10:00:00Z',
            error_code: null,
            floor_elevation_mm: 47600,
            floor_elevation_source: 'observed',
            floor_height_mm: 3300,
            floor_height_source: 'derived',
          },
          {
            attempt: 2,
            status: 'succeeded',
            requested_elevation_mm: 50900,
            requested_height_mm: null,
            requested_at: '2026-11-10T12:00:00Z',
            error_code: null,
            floor_elevation_mm: 50900,
            floor_elevation_source: 'operator',
            floor_height_mm: 3300,
            floor_height_source: 'derived',
          },
        ],
      }),
    );
    const history = screen.getByTestId('mep-history');
    expect(history).toHaveTextContent('История расчётов (2)');
    expect(history).toHaveTextContent('Запрос: по документации');
    expect(history).toHaveTextContent('пол 50900');
    api.downloadCadArtifact.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть на просмотр' }));
    await waitFor(() =>
      expect(api.downloadCadArtifact.mock.calls.some((c) => c[0]?.query?.attempt === 1)).toBe(true),
    );
  });

  it('итоги показывают источник и цитату, а расхождение с документацией выделено', async () => {
    api.downloadCadArtifact.mockResolvedValue({
      data: {
        ...candidate,
        provenance: {
          floor_elevation: {
            value_mm: 40000,
            source: 'operator',
            evidence: 'введено вручную',
          },
          floor_height: {
            value_mm: 3300,
            source: 'derived',
            evidence: 'стр. 81 +47,600 → стр. 82 +50,900',
          },
        },
      },
    });
    mount(routeWith({}));
    const values = await screen.findByRole('list', { name: 'Отметка и высота этажа' });
    expect(values).toHaveTextContent('40000 мм · введено вручную');
    expect(values).toHaveTextContent('стр. 81 +47,600 → стр. 82 +50,900');
    expect(screen.getByText('elevation_mismatch').closest('li')).toHaveClass('border-danger');
  });
});
