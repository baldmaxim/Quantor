import type {
  CadPipelineSheetRead,
  CadPipelineStageRead,
  CadPipelineViewRead,
} from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { sheetRows } from './pipeline-actions';
import {
  batchActionKey,
  batchStepFailedAgain,
  isPipelineSelectable,
  nextBatchStep,
} from './pipeline-batch';

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

const wallsDone = stage({ job_id: 'w-1', job_type: 'cad_walls', result_status: 'walls_ready' });
const zonesDone = stage({ job_id: 'z-1', job_type: 'cad_zones', result_status: 'zones_ready' });
const failed = (type: string, id: string): CadPipelineStageRead =>
  stage({ job_id: id, job_type: type, status: 'failed', result_status: null, error_code: 'X' });

const step = (s: CadPipelineSheetRead, launched: ReadonlySet<string> = new Set()) =>
  nextBatchStep(sheetRows('p-1', 'rev-1', 1, s), launched);

describe('следующий шаг листа в массовом запуске', () => {
  it('новый лист без преобразования: convert', () => {
    const decision = step(sheet({ convert: null, views: [], calibrated: false }));
    expect(decision).toMatchObject({
      kind: 'run',
      action: { kind: 'convert', id: 'convert:start' },
    });
  });

  it('преобразование упало: retry с заданием', () => {
    const decision = step(sheet({ convert: failed('cad_pdf_convert', 'c-f'), views: [] }));
    expect(decision).toMatchObject({
      kind: 'run',
      action: { kind: 'retry', jobId: 'c-f' },
      key: 'convert:retry:c-f',
    });
  });

  it('преобразование готово, конструкции не начаты: walls', () => {
    expect(step(sheet())).toMatchObject({ kind: 'run', action: { kind: 'walls' } });
  });

  it('конструкции готовы, зон нет: автоматическая разметка зон', () => {
    expect(step(sheet({ views: [view({ walls: wallsDone })] }))).toMatchObject({
      kind: 'run',
      action: { kind: 'zones-auto' },
    });
  });

  it('упавший шаг важнее не начатого: повтор конструкций', () => {
    const decision = step(sheet({ views: [view({ walls: failed('cad_walls', 'w-f') })] }));
    expect(decision).toMatchObject({ kind: 'run', action: { kind: 'walls', intent: 'fix' } });
  });

  it('идёт шаг: ждём, ничего не запускаем', () => {
    expect(step(sheet({ convert: stage({ status: 'running' }), views: [] }))).toEqual({
      kind: 'wait',
    });
    expect(step(sheet({ views: [view({ walls: stage({ status: 'queued' }) })] }))).toEqual({
      kind: 'wait',
    });
  });

  it('идущий необязательный 3D DXF не задерживает лист', () => {
    const running = stage({ job_type: 'cad_floor3d', status: 'running' });
    const decision = step(
      sheet({
        views: [view({ walls: wallsDone, zones: zonesDone, approved: true, floor3d: running })],
      }),
    );
    expect(decision).not.toEqual({ kind: 'wait' });
  });

  it('ждёт решения человека (одобрение вида): лист завершён', () => {
    expect(step(sheet({ views: [view({ walls: wallsDone, zones: zonesDone })] }))).toEqual({
      kind: 'done',
      outcome: 'human',
    });
  });

  it('масштаб не подтверждён и калибровки нет: ждёт человека', () => {
    const unconfirmed = stage({
      status: 'failed',
      result_status: null,
      error_code: 'CAD_AUTO_SCALE_UNCONFIRMED',
    });
    expect(step(sheet({ calibrated: false, convert: unconfirmed, views: [] }))).toEqual({
      kind: 'done',
      outcome: 'human',
    });
  });

  it('всё готово: лист завершён как готовый', () => {
    const routes = stage({ job_id: 'r-1', job_type: 'cad_mep', result_status: 'routes_ready' });
    const decision = step(
      sheet({
        views: [
          view({
            walls: wallsDone,
            zones: zonesDone,
            approved: true,
            routes,
            routes_accepted: true,
          }),
        ],
      }),
    );
    expect(decision).toEqual({ kind: 'done', outcome: 'ready' });
  });

  it('DXF не выпущен: шагов нет, лист завершён', () => {
    const noCad = stage({ result_status: 'completed_no_cad' });
    const decision = step(sheet({ convert: noCad, views: [] }));
    expect(decision.kind).toBe('done');
  });

  it('защита от повтора: то же действие по тому же заданию уже запускалось', () => {
    const s = sheet({ convert: failed('cad_pdf_convert', 'c-f'), views: [] });
    const first = step(s);
    if (first.kind !== 'run') throw new Error('ожидался запуск');
    expect(step(s, new Set([first.key]))).toEqual({
      kind: 'failed',
      message: batchStepFailedAgain('CAD'),
    });
  });

  it('другое задание того же шага повтором не считается', () => {
    const action = (job: string) =>
      batchActionKey({
        id: 'convert:retry',
        kind: 'retry',
        intent: 'fix',
        label: 'Повторить',
        jobId: job,
        pageIndex: 0,
        view: null,
        href: null,
        confirm: false,
      });
    const s = sheet({ convert: failed('cad_pdf_convert', 'c-2'), views: [] });
    expect(step(s, new Set([action('c-1')])).kind).toBe('run');
  });
});

describe('выбор листа для запуска конвейера', () => {
  const selectable = (s: CadPipelineSheetRead) =>
    isPipelineSelectable(s, sheetRows('p-1', 'rev-1', 1, s));

  it('без преобразования и с машинным шагом - можно', () => {
    expect(selectable(sheet({ convert: null, views: [] }))).toBe(true);
    expect(selectable(sheet())).toBe(true);
  });

  it('готовый и ждущий человека, идущий - нельзя', () => {
    expect(selectable(sheet({ views: [view({ walls: wallsDone, zones: zonesDone })] }))).toBe(
      false,
    );
    expect(selectable(sheet({ convert: stage({ status: 'running' }), views: [] }))).toBe(false);
  });
});
