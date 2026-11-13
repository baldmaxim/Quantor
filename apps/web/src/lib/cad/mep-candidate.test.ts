import { describe, expect, it } from 'vitest';

import {
  assumptionValueText,
  CANDIDATE_SCHEMA,
  formatMeters,
  mepSystemLabel,
  parseCandidate,
  viewFolder,
} from './mep-candidate';

/** Синтетический candidate.json: только поля, которые читает панель. */
const sample = (patch: Record<string, unknown> = {}) => ({
  schema: CANDIDATE_SCHEMA,
  status: 'candidate_requires_review',
  provenance: { generator_version: 'cad_mep.v1', extra: true },
  elevation: {
    floor_elevation_mm: { value: 10000, source: 'operator' },
    floor_height_mm: { value: 3000, source: 'operator' },
    sheet_marks_mm: [10000],
  },
  assumptions: [
    { name: 'z_heat_mm', value: 50, unit: 'мм', note: 'высота подводки' },
    { name: 'layer_offset_mm', value: { 'M-OV-T1': -50 }, unit: 'мм', note: '' },
  ],
  shafts: [{ id: 'S00' }],
  apartments: [
    {
      idx: 1,
      number: 'Кв 1',
      lengths_own_lines: { heating: { plan_m: 10.5, len3d_m: 11.25 } },
    },
  ],
  routes: {
    by_layer: { 'M-OV-T1': { plan_m: 5, len3d_m: 5.5, polylines: 3 } },
    by_system: { heating: { plan_m: 10.5, len3d_m: 11.25 } },
    totals: { plan_m: 10.5, len3d_m: 11.25 },
  },
  issues: [{ code: 'elevation_mismatch', message: 'отметка не найдена', apartment: null }],
  notes: ['квартира присоединена по марке'],
  ...patch,
});

describe('parseCandidate', () => {
  it('читает длины, проблемы и допущения, лишние поля пропускает', () => {
    const candidate = parseCandidate(sample());
    // Одна расчётная длина - длина по оси с вертикалями; проекция на план не читается.
    expect(candidate?.routes.totals).toEqual({ length_m: 11.25 });
    expect(candidate?.routes.by_system.heating).toEqual({ length_m: 11.25 });
    expect(candidate?.routes.by_layer['M-OV-T1']).toEqual({ length_m: 5.5 });
    expect(candidate?.apartments[0]?.lengths_own_lines.heating).toEqual({ length_m: 11.25 });
    expect(candidate?.apartments[0]?.number).toBe('Кв 1');
    expect(candidate?.issues[0]?.code).toBe('elevation_mismatch');
    expect(candidate?.assumptions).toHaveLength(2);
    expect(candidate?.elevation.floor_elevation_mm).toEqual({ value: 10000, source: 'operator' });
  });

  it('чужая схема, пустое тело и битая форма - null', () => {
    expect(parseCandidate(sample({ schema: 'quantor.cad_mep.candidate.v2' }))).toBeNull();
    expect(parseCandidate(null)).toBeNull();
    expect(parseCandidate('{}')).toBeNull();
    expect(parseCandidate(sample({ routes: { totals: { len3d_m: 'много' } } }))).toBeNull();
    expect(parseCandidate(sample({ routes: { totals: { plan_m: 10.5 } } }))).toBeNull();
  });

  it('списки без значения становятся пустыми', () => {
    const raw = sample() as Record<string, unknown>;
    delete raw.issues;
    delete raw.notes;
    const candidate = parseCandidate(raw);
    expect(candidate?.issues).toEqual([]);
    expect(candidate?.notes).toEqual([]);
  });
});

describe('подписи', () => {
  it('каталог вида: страница и вид с 1, три и две цифры', () => {
    expect(viewFolder(80, 1)).toBe('views/p081_v01');
    expect(viewFolder(0, 12)).toBe('views/p001_v12');
  });

  it('системы по-русски, незнакомая - как есть', () => {
    expect(mepSystemLabel('heating')).toBe('Отопление');
    expect(mepSystemLabel('sewer')).toBe('Канализация');
    expect(mepSystemLabel('vent')).toBe('Вентиляция');
    expect(mepSystemLabel('smoke')).toBe('Противодымная вентиляция');
    expect(mepSystemLabel('cooling')).toBe('Кондиционирование');
    expect(mepSystemLabel('drain')).toBe('Дренаж');
    expect(mepSystemLabel('storm')).toBe('Водосток');
    expect(mepSystemLabel('gas')).toBe('gas');
  });

  it('значение допущения и метры', () => {
    expect(assumptionValueText(50)).toBe('50');
    expect(assumptionValueText(['а', 'б'])).toBe('["а","б"]');
    expect(assumptionValueText('текст')).toBe('текст');
    expect(formatMeters(1234.5)).toMatch(/^1\s?234,50$/);
  });
});
