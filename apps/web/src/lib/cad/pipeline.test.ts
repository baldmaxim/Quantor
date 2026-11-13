import type {
  CadPipelineRead,
  CadPipelineSheetRead,
  CadPipelineStageRead,
  CadPipelineViewRead,
} from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  isUpdateActive,
  pipelineHasActive,
  sheetProgress,
  sheetSteps,
  sheetSummary,
  sheetUpdateBadge,
  type PipelineStepKey,
} from './pipeline';

const stage = (overrides: Partial<CadPipelineStageRead> = {}): CadPipelineStageRead => ({
  job_id: 'job-1',
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

const view = (overrides: Partial<CadPipelineViewRead> = {}): CadPipelineViewRead => ({
  page: 0,
  view: 1,
  has_dxf: true,
  walls: null,
  zones: null,
  zones_count: 0,
  approved: false,
  routes: null,
  routes_accepted: false,
  floor3d: null,
  ...overrides,
});

const sheet = (overrides: Partial<CadPipelineSheetRead> = {}): CadPipelineSheetRead => ({
  page_index: 0,
  page_label: null,
  title: null,
  is_plan: true,
  scale_source: 'calibration',
  calibrated: true,
  convert: stage(),
  views: [view()],
  ...overrides,
});

const state = (s: CadPipelineSheetRead, key: PipelineStepKey) =>
  sheetSteps(s).find((step) => step.key === key);

const walls = stage({ job_type: 'cad_walls', result_status: 'walls_ready' });
const zonesReady = stage({ job_type: 'cad_zones', result_status: 'zones_ready' });

describe('шаги листа', () => {
  it('порядок и подписи', () => {
    expect(sheetSteps(sheet()).map((step) => step.label)).toEqual([
      'Калибровка',
      'CAD',
      'Конструкции',
      'Зоны',
      'Одобрение',
      'Трассы',
      '3D DXF',
    ]);
  });

  it('нетронутый лист: калибровка и CAD не начаты, остальное заблокировано, итог «Не запущено»', () => {
    const s = sheet({ calibrated: false, scale_source: null, convert: null, views: [] });
    expect(sheetSteps(s).map((step) => step.state)).toEqual([
      'todo',
      'todo',
      'blocked',
      'blocked',
      'blocked',
      'blocked',
      'blocked',
    ]);
    expect(sheetSummary(s)).toEqual({ tone: 'neutral', label: 'Не запущено' });
    expect(sheetProgress(s)).toEqual({ done: 0, total: 6 });
  });

  it('масштаб авто: калибровка выполнена с подписью «Масштаб: авто»', () => {
    const s = sheet({ calibrated: false, scale_source: 'auto', views: [] });
    expect(state(s, 'calibration')).toMatchObject({ state: 'done', detail: 'Масштаб: авто' });
    expect(state(s, 'convert')?.state).toBe('done');
    expect(sheetSummary(s).label).not.toContain('откалибровать');
  });

  it('масштаб не подтверждён: ошибка CAD с причиной, калибровка нужна человеку', () => {
    const s = sheet({
      calibrated: false,
      scale_source: null,
      convert: stage({
        status: 'failed',
        result_status: null,
        error_code: 'CAD_AUTO_SCALE_UNCONFIRMED',
      }),
      views: [],
    });
    expect(state(s, 'calibration')).toMatchObject({
      state: 'todo',
      detail: 'нужна ручная калибровка',
    });
    expect(state(s, 'convert')).toMatchObject({
      state: 'failed',
      detail: expect.stringContaining('Масштаб листа не подтверждён') as string,
    });
    expect(sheetSummary(s)).toEqual({ tone: 'danger', label: 'Ошибка: CAD' });
  });

  it('калиброван, задания нет: CAD ждёт запуска', () => {
    const s = sheet({ convert: null, views: [] });
    expect(state(s, 'calibration')?.state).toBe('done');
    expect(state(s, 'convert')?.state).toBe('todo');
    expect(state(s, 'walls')?.state).toBe('blocked');
    expect(sheetSummary(s)).toEqual({ tone: 'warning', label: 'Не запущено: CAD' });
  });

  it('преобразование идёт: процент в подписи, дальше заблокировано', () => {
    const s = sheet({ convert: stage({ status: 'running', progress: 0.4 }), views: [] });
    expect(state(s, 'convert')).toMatchObject({ state: 'running', detail: '40 %' });
    expect(state(s, 'walls')?.state).toBe('blocked');
    expect(sheetSummary(s)).toEqual({ tone: 'accent', label: 'Идёт: CAD · 40 %' });
  });

  it('преобразование без хода: идёт, но без процента', () => {
    const s = sheet({ convert: stage({ status: 'running', progress: null }), views: [] });
    expect(sheetSummary(s)).toEqual({ tone: 'accent', label: 'Идёт: CAD' });
  });

  it('задание в очереди: состояние «в очереди» с номером задания, итог «В очереди»', () => {
    const s = sheet({ convert: stage({ job_id: 'job-q', status: 'queued', progress: null }), views: [] });
    expect(state(s, 'convert')).toMatchObject({ state: 'queued', detail: null, jobId: 'job-q' });
    expect(state(s, 'walls')?.state).toBe('blocked');
    expect(sheetSummary(s)).toEqual({ tone: 'accent', label: 'В очереди' });
  });

  it('этап вида в очереди: шаг «в очереди», идущий этап важнее в итоге', () => {
    const queued = sheet({
      views: [view({ walls: stage({ job_type: 'cad_walls', job_id: 'w-q', status: 'queued' }) })],
    });
    expect(state(queued, 'walls')).toMatchObject({ state: 'queued', jobId: 'w-q' });
    expect(sheetSummary(queued)).toEqual({ tone: 'accent', label: 'В очереди' });
    const mixed = sheet({
      views: [
        view({
          walls: stage({ job_type: 'cad_walls', status: 'queued' }),
          zones: stage({ job_type: 'cad_zones', status: 'running', progress: null }),
        }),
      ],
    });
    expect(sheetSummary(mixed)).toEqual({ tone: 'accent', label: 'Идёт: Зоны' });
  });

  it('отказ преобразования: код ошибки в подписи, итог - ошибка CAD', () => {
    const s = sheet({
      convert: stage({ status: 'failed', error_code: 'CAD_ENGINE_FAILED', result_status: null }),
      views: [],
    });
    expect(state(s, 'convert')).toMatchObject({
      state: 'failed',
      detail: 'Движок CAD не выдал проверенный результат.',
    });
    expect(state(s, 'walls')?.state).toBe('blocked');
    expect(sheetSummary(s)).toEqual({ tone: 'danger', label: 'Ошибка: CAD' });
  });

  it('итог failed у успешного задания - тоже отказ', () => {
    const s = sheet({ convert: stage({ result_status: 'failed' }), views: [] });
    expect(state(s, 'convert')?.state).toBe('failed');
  });

  it('DXF не выпущен: шаги после CAD пропущены', () => {
    const s = sheet({
      convert: stage({ result_status: 'no_cad_review_required' }),
      views: [view({ has_dxf: false })],
    });
    expect(state(s, 'convert')).toMatchObject({ state: 'done', detail: 'DXF не выпущен' });
    expect(sheetSteps(s).slice(2).map((step) => step.state)).toEqual([
      'skipped',
      'skipped',
      'skipped',
      'skipped',
      'skipped',
    ]);
    expect(sheetSummary(s)).toEqual({ tone: 'neutral', label: 'CAD: DXF не выпущен' });
  });

  it('CAD готов, видов нет: шаги пропущены', () => {
    const s = sheet({ views: [] });
    expect(state(s, 'zones')?.state).toBe('skipped');
  });

  it('конструкции не запущены: «Не запущено», зоны тоже todo', () => {
    expect(state(sheet(), 'walls')?.state).toBe('todo');
    expect(state(sheet(), 'zones')?.state).toBe('todo');
    expect(state(sheet(), 'approval')?.state).toBe('blocked');
    expect(sheetSummary(sheet())).toEqual({ tone: 'warning', label: 'Не запущено: Конструкции' });
  });

  it('конструкции идут: «Идёт» с процентом', () => {
    const running = sheet({
      views: [view({ walls: stage({ status: 'running', progress: 0.5 }), zones: zonesReady })],
    });
    expect(state(running, 'walls')).toMatchObject({ state: 'running', detail: '50 %' });
    expect(sheetSummary(running)).toEqual({ tone: 'accent', label: 'Идёт: Конструкции · 50 %' });
  });

  it('конструкции готовы, зоны не запускались (лист старше автозон): «Не запущено: Зоны»', () => {
    const s = sheet({ views: [view({ walls, zones: null, zones_count: 0 })] });
    expect(state(s, 'walls')?.state).toBe('done');
    expect(state(s, 'zones')?.state).toBe('todo');
    expect(sheetSummary(s)).toEqual({ tone: 'warning', label: 'Не запущено: Зоны' });
  });

  it('зоны идут, трассы ждут принятия: «Идёт» важнее «Нужно»', () => {
    const s = sheet({
      views: [
        view({
          walls,
          zones: stage({ job_type: 'cad_zones', status: 'running', progress: null }),
          approved: true,
          routes: stage({ job_type: 'cad_mep_route' }),
        }),
      ],
    });
    expect(state(s, 'routes')?.state).toBe('review');
    expect(sheetSummary(s)).toEqual({ tone: 'accent', label: 'Идёт: Зоны' });
  });

  it('отказ конструкций: ошибка, одобрение заблокировано', () => {
    const s = sheet({
      views: [
        view({
          walls: stage({ status: 'failed', error_code: 'CAD_WALLS_NOT_READY', result_status: null }),
          zones: zonesReady,
          zones_count: 5,
        }),
      ],
    });
    expect(state(s, 'walls')?.state).toBe('failed');
    expect(state(s, 'zones')?.state).toBe('done');
    expect(state(s, 'approval')?.state).toBe('blocked');
    expect(sheetSummary(s)).toEqual({ tone: 'danger', label: 'Ошибка: Конструкции' });
  });

  it('зоны разложены: число зон с правильным склонением', () => {
    const forms = (count: number) =>
      state(sheet({ views: [view({ walls, zones: zonesReady, zones_count: count })] }), 'zones');
    expect(forms(1)?.detail).toBe('1 зона');
    expect(forms(3)?.detail).toBe('3 зоны');
    expect(forms(12)?.detail).toBe('12 зон');
    expect(forms(42)?.detail).toBe('42 зоны');
  });

  it('зоны не созданы, так как на листе они уже были', () => {
    const s = sheet({
      views: [
        view({
          walls,
          zones: stage({ job_type: 'cad_zones', result_status: 'zones_skipped_existing' }),
          zones_count: 7,
        }),
      ],
    });
    expect(state(s, 'zones')).toMatchObject({ state: 'done', detail: 'на листе уже были зоны' });
  });

  it('зоны, размеченные вручную без задания, считаются выполненными', () => {
    const s = sheet({ views: [view({ walls, zones: null, zones_count: 4 })] });
    expect(state(s, 'zones')).toMatchObject({ state: 'done', detail: '4 зоны' });
  });

  it('конструкции и зоны готовы: ждёт одобрения человеком', () => {
    const s = sheet({ views: [view({ walls, zones: zonesReady, zones_count: 3 })] });
    expect(state(s, 'approval')?.state).toBe('review');
    expect(state(s, 'routes')?.state).toBe('blocked');
    expect(sheetSummary(s)).toEqual({ tone: 'warning', label: 'Нужно: одобрить вид' });
  });

  it('одобрен, трасс нет: трассы можно строить', () => {
    const s = sheet({ views: [view({ walls, zones: zonesReady, approved: true })] });
    expect(state(s, 'approval')?.state).toBe('done');
    expect(state(s, 'routes')?.state).toBe('todo');
    expect(sheetSummary(s).label).toBe('Не запущено: Трассы');
  });

  it('трассы идут: процент', () => {
    const s = sheet({
      views: [
        view({
          walls,
          zones: zonesReady,
          approved: true,
          routes: stage({ job_type: 'cad_mep_route', status: 'running', progress: 0.6 }),
        }),
      ],
    });
    expect(state(s, 'routes')).toMatchObject({ state: 'running', detail: '60 %' });
    expect(sheetSummary(s)).toEqual({ tone: 'accent', label: 'Идёт: Трассы · 60 %' });
  });

  it('трассы построены, но не приняты: ждут человека', () => {
    const s = sheet({
      views: [
        view({
          walls,
          zones: zonesReady,
          approved: true,
          routes: stage({ job_type: 'cad_mep_route' }),
        }),
      ],
    });
    expect(state(s, 'routes')?.state).toBe('review');
    expect(sheetSummary(s)).toEqual({ tone: 'warning', label: 'Нужно: принять трассы' });
  });

  it('трассы приняты: готово, 3D DXF необязателен', () => {
    const s = sheet({
      views: [
        view({
          walls,
          zones: zonesReady,
          approved: true,
          routes: stage({ job_type: 'cad_mep_route' }),
          routes_accepted: true,
        }),
      ],
    });
    expect(state(s, 'routes')).toMatchObject({ state: 'done', detail: 'приняты' });
    expect(state(s, 'floor3d')?.state).toBe('todo');
    expect(sheetSummary(s)).toEqual({ tone: 'success', label: 'Готово' });
  });

  it('3D DXF не входит в итог листа: идёт или готов - итог «Готово»', () => {
    const base = {
      walls,
      zones: zonesReady,
      approved: true,
      routes: stage({ job_type: 'cad_mep_route' }),
      routes_accepted: true,
    };
    const running = sheet({
      views: [
        view({ ...base, floor3d: stage({ job_type: 'cad_floor3d_dxf', status: 'running', progress: 0.2 }) }),
      ],
    });
    expect(state(running, 'floor3d')).toMatchObject({ state: 'running', detail: '20 %' });
    expect(sheetSummary(running)).toEqual({ tone: 'success', label: 'Готово' });

    const done = sheet({
      views: [view({ ...base, floor3d: stage({ job_type: 'cad_floor3d_dxf' }) })],
    });
    expect(state(done, 'floor3d')?.state).toBe('done');
    expect(sheetSummary(done).label).toBe('Готово');
  });

  it('отказ 3D DXF виден в шаге, но итог листа не меняет', () => {
    const s = sheet({
      views: [
        view({
          walls,
          zones: zonesReady,
          approved: true,
          routes: stage({ job_type: 'cad_mep_route' }),
          routes_accepted: true,
          floor3d: stage({ status: 'failed', error_code: 'CAD_ELEVATION_NOT_FOUND', result_status: null }),
        }),
      ],
    });
    expect(state(s, 'floor3d')?.state).toBe('failed');
    expect(sheetSummary(s)).toEqual({ tone: 'success', label: 'Готово' });
  });

  it('несколько видов: побеждает худшее состояние, виды без DXF не считаются', () => {
    const ready = view({ walls, zones: zonesReady, zones_count: 2, approved: true });
    const failedWalls = view({
      view: 2,
      walls: stage({ status: 'failed', result_status: null }),
      zones: zonesReady,
    });
    const noDxf = view({ view: 3, has_dxf: false });
    const s = sheet({ views: [ready, failedWalls, noDxf] });

    expect(state(s, 'walls')?.state).toBe('failed');
    // approved у первого вида, у второго - заблокировано: хуже побеждает.
    expect(state(s, 'approval')?.state).toBe('blocked');

    const done = sheet({ views: [ready, { ...ready, view: 2 }, noDxf] });
    expect(state(done, 'walls')?.state).toBe('done');
    expect(state(done, 'approval')?.state).toBe('done');
  });
});

describe('sheetProgress', () => {
  it('считает готовые и пропущенные из шести основных шагов, 3D DXF не в счёт', () => {
    expect(sheetProgress(sheet({ calibrated: false, convert: null, views: [] }))).toEqual({
      done: 0,
      total: 6,
    });
    expect(sheetProgress(sheet())).toEqual({ done: 2, total: 6 });
    expect(
      sheetProgress(sheet({ views: [view({ walls, zones: zonesReady, zones_count: 2 })] })),
    ).toEqual({ done: 4, total: 6 });
    expect(sheetProgress(sheet({ views: [] }))).toEqual({ done: 6, total: 6 });
    const all = sheet({
      views: [
        view({
          walls,
          zones: zonesReady,
          approved: true,
          routes: stage({ job_type: 'cad_mep_route' }),
          routes_accepted: true,
        }),
      ],
    });
    expect(sheetProgress(all)).toEqual({ done: 6, total: 6 });
  });
});

describe('pipelineHasActive', () => {
  const pipeline = (sheets: CadPipelineSheetRead[]): CadPipelineRead => ({
    revision_id: 'r1',
    server_time: '2026-11-11T10:00:00Z',
    sheets,
  });

  it('нет данных и нет листов: ничего не идёт', () => {
    expect(pipelineHasActive(undefined)).toBe(false);
    expect(pipelineHasActive(pipeline([]))).toBe(false);
  });

  it('завершённые этапы не активны', () => {
    expect(pipelineHasActive(pipeline([sheet({ views: [view({ walls, zones: zonesReady })] })]))).toBe(
      false,
    );
  });

  it('идёт преобразование листа', () => {
    expect(
      pipelineHasActive(pipeline([sheet({ convert: stage({ status: 'queued' }) })])),
    ).toBe(true);
  });

  it('идёт этап вида', () => {
    const running = stage({ status: 'running' });
    for (const key of ['walls', 'zones', 'routes', 'floor3d'] as const) {
      expect(pipelineHasActive(pipeline([sheet({ views: [view({ [key]: running })] })]))).toBe(true);
    }
  });
});

describe('обновление CAD листа', () => {
  const running = stage({ job_id: 'new', status: 'running', result_status: null, progress: 0.3 });
  const failed = stage({
    job_id: 'new',
    status: 'failed',
    result_status: null,
    error_code: 'CAD_AUTO_SCALE_UNCONFIRMED',
  });

  it('лист остаётся готовым по показанному прогону, метка - «обновляется»', () => {
    const s = sheet({
      update: running,
      views: [view({ walls, zones: zonesReady, approved: true })],
    });
    expect(sheetSummary(s)).not.toMatchObject({ tone: 'danger' });
    expect(sheetUpdateBadge(s)).toMatchObject({ tone: 'accent', label: 'обновляется' });
    expect(isUpdateActive(s)).toBe(true);
  });

  it('упавшее обновление - метка с причиной, активным не считается', () => {
    const s = sheet({ update: failed });
    expect(sheetUpdateBadge(s)).toMatchObject({ tone: 'danger', label: 'обновление не удалось' });
    expect(sheetUpdateBadge(s)?.hint).toContain('Показан прежний готовый результат');
    expect(isUpdateActive(s)).toBe(false);
  });

  it('без обновления метки нет', () => {
    expect(sheetUpdateBadge(sheet())).toBeNull();
    expect(sheetUpdateBadge(sheet({ update: null }))).toBeNull();
  });

  it('идущее обновление держит опрос конвейера', () => {
    const pipeline = (sheets: CadPipelineSheetRead[]): CadPipelineRead => ({
      revision_id: 'r1',
      server_time: '2026-11-11T10:00:00Z',
      sheets,
    });
    expect(pipelineHasActive(pipeline([sheet({ update: running })]))).toBe(true);
    expect(pipelineHasActive(pipeline([sheet({ update: failed })]))).toBe(false);
  });
});
