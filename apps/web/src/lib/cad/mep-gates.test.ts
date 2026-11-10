import type { CadDecisionRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  acceptBlock,
  approveBlock,
  elevationError,
  floorHeightError,
  mepErrorText,
  needsManualFloor,
  optionalMm,
  parseMm,
  recomputeBlock,
} from './mep-gates';

const decision = { id: 'd1' } as unknown as CadDecisionRead;

describe('вводы человека', () => {
  it('целое число миллиметров, пробелы и минус допустимы', () => {
    expect(parseMm('47600')).toBe(47600);
    expect(parseMm(' 47 600 ')).toBe(47600);
    expect(parseMm('-1200')).toBe(-1200);
    expect(parseMm('47,6')).toBeNull();
    expect(parseMm('3.3')).toBeNull();
    expect(parseMm('')).toBeNull();
    expect(parseMm('12345678')).toBeNull();
  });

  it('пустая отметка и высота - «по документации», а не ошибка', () => {
    expect(elevationError('')).toBeNull();
    expect(floorHeightError('  ')).toBeNull();
    expect(optionalMm('')).toBeNull();
    expect(optionalMm(' 3300 ')).toBe(3300);
    expect(elevationError('47600')).toBeNull();
    expect(floorHeightError('3300')).toBeNull();
  });

  it('границы контракта: высота 2000-6000, отметка -100000…1000000', () => {
    expect(floorHeightError('1999')).toMatch(/вне пределов/);
    expect(floorHeightError('6001')).toMatch(/вне пределов/);
    expect(floorHeightError('2000')).toBeNull();
    expect(floorHeightError('6000')).toBeNull();
    expect(elevationError('-100001')).toMatch(/вне пределов/);
    expect(elevationError('1000001')).toMatch(/вне пределов/);
    expect(elevationError('abc')).toMatch(/целое число/);
  });
});

describe('кнопки решений', () => {
  it('одобрение: открытые замечания блокируют, непрочитанные тоже', () => {
    expect(approveBlock(null, 0)).toBeNull();
    expect(approveBlock(null, 2)).toMatch(/открытые замечания \(2\)/);
    expect(approveBlock(null, null)).toMatch(/загружаются/);
  });

  it('одобренный вид повторно не одобряется', () => {
    expect(approveBlock(decision, 0)).toBe('Вид уже одобрен.');
  });

  it('принятие: то же правило на замечаниях трасс', () => {
    expect(acceptBlock(null, 0)).toBeNull();
    expect(acceptBlock(null, 1)).toMatch(/открытые замечания/);
    expect(acceptBlock(decision, 0)).toBe('Трассы уже приняты.');
    expect(acceptBlock(null, 0, true)).toMatch(/Одобрение вида отозвано/);
  });

  it('пересчёт: закрыт в работе, при принятии и отозванном одобрении', () => {
    const ok = { status: 'succeeded', accepted: false, approvalRevoked: false };
    expect(recomputeBlock(ok)).toBeNull();
    expect(recomputeBlock({ ...ok, status: 'failed' })).toBeNull();
    expect(recomputeBlock({ ...ok, status: 'running' })).toMatch(/считаются/);
    expect(recomputeBlock({ ...ok, status: 'queued' })).toMatch(/считаются/);
    expect(recomputeBlock({ ...ok, accepted: true })).toMatch(/отзовите принятие/);
    expect(recomputeBlock({ ...ok, approvalRevoked: true })).toMatch(/Одобрение вида отозвано/);
  });

  it('ручной ввод нужен после отказов «не найдено в документации»', () => {
    expect(needsManualFloor('CAD_ELEVATION_NOT_FOUND')).toBe(true);
    expect(needsManualFloor('CAD_FLOOR_HEIGHT_NOT_FOUND')).toBe(true);
    expect(needsManualFloor('CAD_MEP_NOT_BUILT')).toBe(false);
    expect(needsManualFloor(null)).toBe(false);
  });
});

describe('тексты отказов 409/422', () => {
  const failure = (code: string) => ({ detail: { code } });

  it.each([
    ['CAD_OPEN_REMARKS', /открытые замечания/],
    ['CAD_ALREADY_DECIDED', /уже принято/],
    ['CAD_VIEW_NOT_APPROVED', /сначала одобрите/],
    ['CAD_ROUTES_NOT_ACCEPTED', /после принятия/],
    ['CAD_MEP_NOT_BUILT', /не построены/],
    ['CAD_INPUT_INVALID', /построения трасс/],
  ])('%s говорит по-русски', (code, pattern) => {
    expect(mepErrorText(failure(code))).toMatch(pattern);
  });
});
