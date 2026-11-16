import type {
  CadPipelineSheetRead,
  CadPipelineStageRead,
  CadPipelineViewRead,
  CadZoneRead,
} from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  isSheetStale,
  sheetQualityBadge,
  sheetStaleTexts,
  sheetSteps,
  sheetSummary,
  staleText,
} from './pipeline';
import { sheetRows } from './pipeline-actions';
import { isStaleRecomputable, nextStaleStep, staleNextAction } from './pipeline-batch';
import { zonesOutOfTolerance } from './zone-quality';

/** Пороги качества и метка «устарел» в конвейере листа (ревью движка 2026-11-16). */

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

const wallsReview = stage({
  job_id: 'w-1',
  job_type: 'cad_walls',
  result_status: 'walls_ready',
  quality_status: 'review',
  quality_reasons: ['на плане нет конструкций', 'высота этажа не определена'],
});
const wallsOk = stage({
  job_id: 'w-2',
  job_type: 'cad_walls',
  result_status: 'walls_ready',
  quality_status: 'ok',
  quality_reasons: [],
});
const zonesDone = stage({ job_id: 'z-1', job_type: 'cad_zones', result_status: 'zones_ready' });
const routesDone = stage({
  job_id: 'r-1',
  job_type: 'cad_mep_route',
  result_status: 'routes_ready',
});

const view = (overrides: Partial<CadPipelineViewRead> = {}): CadPipelineViewRead => ({
  page: 0,
  view: 1,
  has_dxf: true,
  walls: wallsOk,
  zones: zonesDone,
  zones_count: 5,
  approved: true,
  routes: routesDone,
  routes_accepted: true,
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
  convert: stage({ job_id: 'c-1' }),
  views: [view()],
  ...overrides,
});

const rows = (s: CadPipelineSheetRead) => sheetRows('p-1', 'rev-1', 1, s);

describe('порог качества конструкций', () => {
  it('лист без замечаний - «Готово», метки нет', () => {
    expect(sheetSummary(sheet())).toEqual({ tone: 'success', label: 'Готово' });
    expect(sheetQualityBadge(sheet())).toBeNull();
    expect(sheetSteps(sheet()).find((step) => step.key === 'walls')?.review).toBeUndefined();
  });

  it('результат с замечаниями: шаг готов и доступен, но лист не «Готово»', () => {
    const s = sheet({ views: [view({ walls: wallsReview })] });
    const walls = sheetSteps(s).find((step) => step.key === 'walls');
    expect(walls?.state).toBe('done');
    expect(walls?.review).toEqual(['на плане нет конструкций', 'высота этажа не определена']);
    expect(sheetSummary(s)).toEqual({ tone: 'warning', label: 'На проверку: Конструкции' });
    expect(sheetQualityBadge(s)).toEqual({
      label: 'на проверку',
      reasons: ['на плане нет конструкций', 'высота этажа не определена'],
    });
  });

  it('замечания не блокируют одобрение вида и видны до конца конвейера', () => {
    const s = sheet({
      views: [view({ walls: wallsReview, approved: false, routes: null, routes_accepted: false })],
    });
    expect(sheetSteps(s).find((step) => step.key === 'approval')?.state).toBe('review');
    expect(sheetSummary(s).label).toBe('Нужно: одобрить вид');
    expect(sheetQualityBadge(s)?.label).toBe('на проверку');
  });

  it('несколько видов: причины собираются со всех, без повторов', () => {
    const other = {
      ...wallsReview,
      job_id: 'w-3',
      quality_reasons: ['высота этажа не определена'],
    };
    const s = sheet({ views: [view({ walls: wallsReview }), view({ view: 2, walls: other })] });
    expect(sheetQualityBadge(s)?.reasons).toEqual([
      'на плане нет конструкций',
      'высота этажа не определена',
    ]);
  });

  it('старый итог без оценки и упавшее задание меткой не помечаются', () => {
    const old = stage({ job_type: 'cad_walls', result_status: 'walls_ready' });
    expect(sheetQualityBadge(sheet({ views: [view({ walls: old })] }))).toBeNull();
    const failed = { ...wallsReview, status: 'failed' as const };
    expect(sheetQualityBadge(sheet({ views: [view({ walls: failed })] }))).toBeNull();
  });
});

describe('метка «устарел по версии»', () => {
  const stale = sheet({
    stale: [
      { stage: 'convert', view: null, was: '2026.11.13+aaa', now: '2026.11.16+bbb' },
      { stage: 'walls', view: 1, was: null, now: 'cad_walls.v1.15' },
      { stage: 'zones', view: null, was: 'cad_mep.v16.5', now: 'cad_mep.v16.6' },
    ],
  });

  it('текст: этап, было, стало; версии нет - «версия неизвестна»', () => {
    expect(sheetStaleTexts(stale)).toEqual([
      'CAD: было 2026.11.13+aaa, стало 2026.11.16+bbb',
      'Конструкции: было версия неизвестна, стало cad_walls.v1.15',
      'Зоны: было cad_mep.v16.5, стало cad_mep.v16.6',
    ]);
    expect(staleText({ stage: 'walls', view: 2, was: 'a', now: 'b' })).toBe(
      'Конструкции: было a, стало b',
    );
    expect(isSheetStale(stale)).toBe(true);
    expect(isSheetStale(sheet())).toBe(false);
    expect(sheetStaleTexts(sheet())).toEqual([]);
  });

  it('пересчёт идёт по одному этапу: сначала преобразование', () => {
    expect(staleNextAction(stale, rows(stale))).toMatchObject({ kind: 'convert' });
    expect(nextStaleStep(stale, rows(stale), new Set())).toMatchObject({
      kind: 'run',
      action: { kind: 'convert', id: 'convert:again' },
    });
    expect(isStaleRecomputable(stale, rows(stale))).toBe(true);
  });

  it('устарели только конструкции: пересчёт вида; повторный отказ - ошибка листа', () => {
    const s = sheet({ stale: [{ stage: 'walls', view: 1, was: 'v1', now: 'v2' }] });
    const decision = nextStaleStep(s, rows(s), new Set());
    expect(decision).toMatchObject({
      kind: 'run',
      action: { kind: 'walls', view: 1, jobId: 'c-1' },
    });
    const key = decision.kind === 'run' ? decision.key : '';
    expect(nextStaleStep(s, rows(s), new Set([key]))).toEqual({
      kind: 'failed',
      message: 'Шаг «Конструкции» снова не выполнился',
    });
  });

  it('устарели авто-зоны: повторная разметка только у листа с одним видом', () => {
    const item = { stage: 'zones' as const, view: null, was: 'v1', now: 'v2' };
    const one = sheet({ stale: [item], views: [view({ zones_recreatable: true })] });
    expect(nextStaleStep(one, rows(one), new Set())).toMatchObject({
      kind: 'run',
      action: { kind: 'zones-auto', intent: 'redo', confirm: true },
    });
    const two = sheet({
      stale: [item],
      views: [view({ zones_recreatable: true }), view({ view: 2, zones_recreatable: true })],
    });
    expect(staleNextAction(two, rows(two))).toBeNull();
    expect(isStaleRecomputable(two, rows(two))).toBe(false);
  });

  it('устаревших этапов нет - лист закончен; идущий шаг - ждём', () => {
    expect(nextStaleStep(sheet(), rows(sheet()), new Set())).toEqual({
      kind: 'done',
      outcome: 'ready',
    });
    const running = sheet({
      stale: [{ stage: 'walls', view: 1, was: 'v1', now: 'v2' }],
      views: [view({ walls: stage({ job_type: 'cad_walls', status: 'running' }) })],
    });
    expect(nextStaleStep(running, rows(running), new Set())).toEqual({ kind: 'wait' });
  });
});

describe('зоны: пересоздание и сверка', () => {
  it('лист с зонами человека - только переход; все зоны авто - «Разметить заново»', () => {
    const human = rows(sheet()).find((row) => row.key === 'zones');
    expect(human?.actions.map((item) => item.kind)).toEqual(['link']);
    const auto = rows(sheet({ views: [view({ zones_recreatable: true })] })).find(
      (row) => row.key === 'zones',
    );
    expect(auto?.actions.map((item) => item.label)).toEqual(['Открыть зоны', 'Разметить заново']);
  });

  it('зоны вне допуска: сначала отклонённые, зоны в допуске не входят', () => {
    const zone = (id: string, status: CadZoneRead['quality_status']) =>
      ({ id, quality_status: status }) as CadZoneRead;
    const list = [zone('a', 'ok'), zone('b', 'review'), zone('c', 'failed')];
    expect(zonesOutOfTolerance(list).map((item) => item.id)).toEqual(['c', 'b']);
  });
});
