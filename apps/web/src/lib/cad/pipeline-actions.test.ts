import type {
  CadPipelineSheetRead,
  CadPipelineStageRead,
  CadPipelineViewRead,
} from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  isMachineAction,
  nextPipelineAction,
  sheetRows,
  type IPipelineRow,
} from './pipeline-actions';

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
  calibrated: true,
  convert: stage(),
  views: [view()],
  ...overrides,
});

const wallsDone = stage({ job_id: 'w-1', job_type: 'cad_walls', result_status: 'walls_ready' });
const zonesDone = stage({ job_id: 'z-1', job_type: 'cad_zones', result_status: 'zones_ready' });
const failedOf = (type: string, code = 'CAD_ENGINE_FAILED'): CadPipelineStageRead =>
  stage({
    job_id: `${type}-f`,
    job_type: type,
    status: 'failed',
    result_status: null,
    error_code: code,
  });

const rowsOf = (s: CadPipelineSheetRead): IPipelineRow[] => sheetRows('p-1', 'rev-1', 3, s);
const rowOf = (rows: IPipelineRow[], key: string, at: number | null = null) =>
  rows.find((row) => row.key === key && (at === null || row.view === at)) as IPipelineRow;
const labels = (row: IPipelineRow) => row.actions.map((item) => item.label);

describe('шаги: калибровка и преобразование', () => {
  it('не откалиброван: ссылка «Откалибровать» в рабочую область, запуска нет', () => {
    const rows = rowsOf(sheet({ calibrated: false, convert: null, views: [] }));
    const calibration = rowOf(rows, 'calibration');
    expect(calibration.actions).toHaveLength(1);
    expect(calibration.actions[0]).toMatchObject({ kind: 'link', label: 'Откалибровать' });
    expect(calibration.actions[0]?.href).toBe(
      '/projects/p-1/workspace?revision=rev-1&page=3&tab=cad',
    );
    // Преобразование заблокировано калибровкой, действий нет.
    expect(rowOf(rows, 'convert').actions).toEqual([]);
  });

  it('откалиброван: калибровка без действий', () => {
    expect(rowOf(rowsOf(sheet()), 'calibration').actions).toEqual([]);
  });

  it('преобразование не запускалось: «Запустить»', () => {
    const rows = rowsOf(sheet({ convert: null, views: [] }));
    expect(rowOf(rows, 'convert').actions[0]).toMatchObject({
      kind: 'convert',
      intent: 'start',
      label: 'Запустить',
      pageIndex: 0,
      confirm: false,
    });
  });

  it('преобразование идёт: действий нет (отмены нет)', () => {
    const rows = rowsOf(sheet({ convert: stage({ status: 'running', progress: 0.3 }), views: [] }));
    expect(rowOf(rows, 'convert').actions).toEqual([]);
  });

  it('преобразование упало: «Повторить» упавшего задания', () => {
    const rows = rowsOf(sheet({ convert: failedOf('cad_pdf_convert'), views: [] }));
    expect(rowOf(rows, 'convert').actions[0]).toMatchObject({
      kind: 'retry',
      intent: 'fix',
      label: 'Повторить',
      jobId: 'cad_pdf_convert-f',
    });
  });

  it('преобразование готово: «Преобразовать заново» с подтверждением', () => {
    expect(rowOf(rowsOf(sheet()), 'convert').actions[0]).toMatchObject({
      kind: 'convert',
      intent: 'redo',
      label: 'Преобразовать заново',
      confirm: true,
    });
  });

  it('шаги после непреобразованного листа - без действий и без вида', () => {
    const rows = rowsOf(sheet({ convert: null, views: [] }));
    for (const key of ['walls', 'zones', 'approval', 'routes', 'floor3d']) {
      expect(rowOf(rows, key).actions).toEqual([]);
      expect(rowOf(rows, key).view).toBeNull();
    }
  });

  it('DXF не выпущен: шаги пропущены, действий нет', () => {
    const rows = rowsOf(
      sheet({
        convert: stage({ result_status: 'no_cad_review_required' }),
        views: [view({ has_dxf: false })],
      }),
    );
    expect(rowOf(rows, 'walls').step.state).toBe('skipped');
    expect(rowOf(rows, 'walls').actions).toEqual([]);
  });
});

describe('конструкции', () => {
  it('не начаты: «Запустить» по родителю вида', () => {
    const action = rowOf(rowsOf(sheet()), 'walls').actions[0];
    expect(action).toMatchObject({
      kind: 'walls',
      intent: 'start',
      label: 'Запустить',
      jobId: 'job-1',
      view: 1,
    });
  });

  it('упали: «Пересчитать» как исправление', () => {
    const rows = rowsOf(sheet({ views: [view({ walls: failedOf('cad_walls') })] }));
    expect(rowOf(rows, 'walls').actions[0]).toMatchObject({
      kind: 'walls',
      intent: 'fix',
      label: 'Пересчитать',
    });
    expect(rowOf(rows, 'walls').stage?.job_id).toBe('cad_walls-f');
  });

  it('готовы: «Пересчитать» как повтор', () => {
    const rows = rowsOf(sheet({ views: [view({ walls: wallsDone })] }));
    expect(rowOf(rows, 'walls').actions[0]).toMatchObject({ intent: 'redo', label: 'Пересчитать' });
  });

  it('идут: действий нет', () => {
    const rows = rowsOf(
      sheet({ views: [view({ walls: stage({ status: 'running', job_type: 'cad_walls' }) })] }),
    );
    expect(rowOf(rows, 'walls').actions).toEqual([]);
  });
});

describe('зоны', () => {
  it('зон нет: «Разметить автоматически»', () => {
    const rows = rowsOf(sheet({ views: [view({ walls: wallsDone })] }));
    expect(rowOf(rows, 'zones').actions[0]).toMatchObject({
      kind: 'zones-auto',
      intent: 'start',
      label: 'Разметить автоматически',
      jobId: 'job-1',
    });
  });

  it('автоматическая разметка упала: исправление', () => {
    const rows = rowsOf(
      sheet({ views: [view({ walls: wallsDone, zones: failedOf('cad_zones') })] }),
    );
    expect(rowOf(rows, 'zones').actions[0]).toMatchObject({ kind: 'zones-auto', intent: 'fix' });
  });

  it('разметка готова, но зон ноль: повтор', () => {
    const rows = rowsOf(sheet({ views: [view({ walls: wallsDone, zones: zonesDone })] }));
    expect(rowOf(rows, 'zones').actions[0]).toMatchObject({ kind: 'zones-auto', intent: 'redo' });
  });

  it('зоны есть: только ссылка «Открыть зоны» (авторазметка ответила бы 409)', () => {
    const rows = rowsOf(sheet({ views: [view({ walls: wallsDone, zones_count: 5 })] }));
    const zones = rowOf(rows, 'zones');
    expect(labels(zones)).toEqual(['Открыть зоны']);
    expect(zones.actions[0]?.href).toBe(
      '/projects/p-1/workspace?revision=rev-1&page=3&tab=cad&job=job-1&view=1',
    );
  });

  it('идёт: действий нет', () => {
    const rows = rowsOf(
      sheet({ views: [view({ zones: stage({ status: 'running', job_type: 'cad_zones' }) })] }),
    );
    expect(rowOf(rows, 'zones').actions).toEqual([]);
  });
});

describe('одобрение и трассы', () => {
  const ready = { walls: wallsDone, zones: zonesDone, zones_count: 2 };

  it('одобрение ждёт человека: ссылка «Проверить вид»', () => {
    const rows = rowsOf(sheet({ views: [view(ready)] }));
    expect(labels(rowOf(rows, 'approval'))).toEqual(['Проверить вид']);
    expect(rowOf(rows, 'approval').actions[0]?.kind).toBe('link');
  });

  it('одобрение заблокировано или готово: действий нет', () => {
    expect(rowOf(rowsOf(sheet()), 'approval').actions).toEqual([]);
    expect(
      rowOf(rowsOf(sheet({ views: [view({ ...ready, approved: true })] })), 'approval').actions,
    ).toEqual([]);
  });

  it('трассы не построены после одобрения: ссылка «Открыть трассы»', () => {
    const rows = rowsOf(sheet({ views: [view({ ...ready, approved: true })] }));
    expect(labels(rowOf(rows, 'routes'))).toEqual(['Открыть трассы']);
  });

  it('трассы ждут принятия: ссылка «Открыть трассы»', () => {
    const routes = stage({ job_type: 'cad_mep_route', job_id: 'r-1' });
    const rows = rowsOf(sheet({ views: [view({ ...ready, approved: true, routes })] }));
    expect(rowOf(rows, 'routes').step.state).toBe('review');
    expect(labels(rowOf(rows, 'routes'))).toEqual(['Открыть трассы']);
  });

  it('трассы упали: повтор задания и ссылка, не пересчёт (пересчёт без новых параметров даёт 409)', () => {
    const rows = rowsOf(
      sheet({ views: [view({ ...ready, approved: true, routes: failedOf('cad_mep_route') })] }),
    );
    expect(rowOf(rows, 'routes').actions.map((item) => item.kind)).toEqual(['retry', 'link']);
    expect(rowOf(rows, 'routes').actions[0]?.jobId).toBe('cad_mep_route-f');
    expect(rowOf(rows, 'routes').stage?.job_id).toBe('cad_mep_route-f');
  });

  it('трассы приняты или идут: действий нет', () => {
    const routes = stage({ job_type: 'cad_mep_route', job_id: 'r-1' });
    const accepted = sheet({
      views: [view({ ...ready, approved: true, routes, routes_accepted: true })],
    });
    expect(rowOf(rowsOf(accepted), 'routes').actions).toEqual([]);
    const running = sheet({
      views: [
        view({
          ...ready,
          approved: true,
          routes: stage({ status: 'running', job_type: 'cad_mep_route' }),
        }),
      ],
    });
    expect(rowOf(rowsOf(running), 'routes').actions).toEqual([]);
  });
});

describe('3D DXF', () => {
  it('конструкции не готовы: действий нет', () => {
    expect(rowOf(rowsOf(sheet()), 'floor3d').actions).toEqual([]);
  });

  it('конструкции готовы, 3D не собирался: «Собрать 3D DXF»', () => {
    const rows = rowsOf(sheet({ views: [view({ walls: wallsDone })] }));
    expect(rowOf(rows, 'floor3d').step.state).toBe('todo');
    expect(rowOf(rows, 'floor3d').actions[0]).toMatchObject({
      kind: 'floor3d',
      intent: 'start',
      label: 'Собрать 3D DXF',
      jobId: 'job-1',
    });
  });

  it('упал: «Повторить»', () => {
    const rows = rowsOf(
      sheet({ views: [view({ walls: wallsDone, floor3d: failedOf('cad_floor3d_dxf') })] }),
    );
    expect(rowOf(rows, 'floor3d').actions[0]).toMatchObject({
      kind: 'floor3d',
      intent: 'fix',
      label: 'Повторить',
    });
  });

  it('готов: «Собрать заново» и «Скачать» по заданию выгрузки', () => {
    const floor3d = stage({ job_id: 'f-9', job_type: 'cad_floor3d_dxf', result_status: null });
    const rows = rowsOf(sheet({ views: [view({ walls: wallsDone, floor3d })] }));
    const floor = rowOf(rows, 'floor3d');
    expect(labels(floor)).toEqual(['Собрать заново', 'Скачать']);
    const download = floor.actions[1];
    expect(download?.kind).toBe('download');
    expect(download?.href).toContain('/cad/f-9/artifacts/');
    expect(download?.href).toContain('floor3d.dxf');
  });

  it('идёт: действий нет', () => {
    const rows = rowsOf(
      sheet({
        views: [
          view({
            walls: wallsDone,
            floor3d: stage({ status: 'running', job_type: 'cad_floor3d_dxf' }),
          }),
        ],
      }),
    );
    expect(rowOf(rows, 'floor3d').actions).toEqual([]);
  });
});

describe('виды', () => {
  it('один вид: подписи «Вид N» нет', () => {
    expect(rowOf(rowsOf(sheet()), 'walls').viewLabel).toBeNull();
  });

  it('несколько видов с DXF: строка на вид и подпись; вид без DXF не показан', () => {
    const rows = rowsOf(
      sheet({
        views: [
          view({ view: 1 }),
          view({ view: 2, walls: wallsDone }),
          view({ view: 3, has_dxf: false }),
        ],
      }),
    );
    const walls = rows.filter((row) => row.key === 'walls');
    expect(walls.map((row) => row.viewLabel)).toEqual(['Вид 1', 'Вид 2']);
    expect(walls.map((row) => row.actions[0]?.intent)).toEqual(['start', 'redo']);
    expect(walls.map((row) => row.actions[0]?.view)).toEqual([1, 2]);
    expect(new Set(rows.map((row) => row.id)).size).toBe(rows.length);
  });
});

describe('следующий шаг', () => {
  it('нет калибровки: переход к калибровке', () => {
    const next = nextPipelineAction(rowsOf(sheet({ calibrated: false, convert: null, views: [] })));
    expect(next?.row.key).toBe('calibration');
    expect(next?.action.kind).toBe('link');
  });

  it('есть калибровка, преобразования не было: запуск преобразования', () => {
    const next = nextPipelineAction(rowsOf(sheet({ convert: null, views: [] })));
    expect(next?.row.key).toBe('convert');
    expect(next?.action && isMachineAction(next.action)).toBe(true);
  });

  it('упавший шаг важнее не начатого раньше него', () => {
    const rows = rowsOf(
      sheet({ views: [view({ walls: wallsDone, zones: failedOf('cad_zones') })] }),
    );
    const next = nextPipelineAction(rows);
    expect(next?.row.key).toBe('zones');
    expect(next?.action.intent).toBe('fix');
  });

  it('конструкции не начаты: запуск конструкций', () => {
    expect(nextPipelineAction(rowsOf(sheet()))?.row.key).toBe('walls');
  });

  it('конструкции и зоны готовы: человек - одобрение', () => {
    const rows = rowsOf(
      sheet({ views: [view({ walls: wallsDone, zones: zonesDone, zones_count: 1 })] }),
    );
    const next = nextPipelineAction(rows);
    expect(next?.row.key).toBe('approval');
    expect(next?.action.kind).toBe('link');
  });

  it('упавшие трассы: повтор задания трасс', () => {
    const rows = rowsOf(
      sheet({
        views: [
          view({
            walls: wallsDone,
            zones: zonesDone,
            zones_count: 1,
            approved: true,
            routes: failedOf('cad_mep_route'),
          }),
        ],
      }),
    );
    const next = nextPipelineAction(rows);
    expect(next?.row.key).toBe('routes');
    expect(next?.action.kind).toBe('retry');
  });

  it('всё идёт или готово: следующего нет; 3D DXF в «следующие» не попадает', () => {
    const routes = stage({ job_type: 'cad_mep_route', job_id: 'r-1' });
    const done = sheet({
      views: [
        view({
          walls: wallsDone,
          zones: zonesDone,
          zones_count: 1,
          approved: true,
          routes,
          routes_accepted: true,
        }),
      ],
    });
    expect(nextPipelineAction(rowsOf(done))).toBeNull();
    const running = sheet({ convert: stage({ status: 'running' }), views: [] });
    expect(nextPipelineAction(rowsOf(running))).toBeNull();
  });
});
