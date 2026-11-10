import type { CadDecisionRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  acceptBlock,
  approveBlock,
  elevationError,
  floorHeightError,
  mepErrorText,
  parseMm,
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

  it('пустая отметка и высота - ошибка, а не умолчание', () => {
    expect(elevationError('')).toMatch(/Введите отметку/);
    expect(floorHeightError('  ')).toMatch(/Введите высоту/);
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
