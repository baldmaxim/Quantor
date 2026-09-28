import { describe, expect, it } from 'vitest';

import { fact, factType } from '@/components/calc/__fixtures__/calc';
import {
  DOCUMENT_CLASSES,
  READINESS_STATUS,
  USAGE,
  formatSubject,
  formatSystem,
  formatValue,
  statedNote,
} from './format';

describe('подписи экрана «Исходные данные»', () => {
  it('«не найдено» и «не проверено» звучат по-разному', () => {
    expect(READINESS_STATUS.MISSING.label).not.toBe(READINESS_STATUS.NOT_INSPECTED.label);
    expect(READINESS_STATUS.NOT_INSPECTED.tone).toBe('neutral');
  });

  it('ВОР Заказчика подписан как только сверка', () => {
    expect(USAGE.EXCLUDED_VOR.label).toMatch(/ВОР/);
    expect(USAGE.EXCLUDED_VOR.label).toMatch(/сверка/);
  });

  it('ручной ввод не заявляется как документ', () => {
    expect(DOCUMENT_CLASSES).not.toContain('MANUAL');
    expect(DOCUMENT_CLASSES).toContain('CUSTOMER_VOR');
  });
});

describe('форматирование', () => {
  it('место читается по-человечески, диапазон этажей — через тире', () => {
    expect(formatSubject({ building: '1', section: '2', floor: '2..24' })).toBe(
      'корп. 1 · секц. 2 · эт. 2–24',
    );
    expect(formatSubject({})).toBe('проект');
    expect(formatSubject({ building: '1', qualifier: 'R2' }, '2-комнатная')).toBe(
      'корп. 1 · 2-комнатная',
    );
  });

  it('система — раздел и обозначение, у места без системы прочерк', () => {
    expect(formatSystem({ discipline: 'VK', system_code: 'В1' })).toBe('ВК · В1');
    expect(formatSystem({ building: '1' })).toBe('—');
  });

  it('число — с десятичной запятой и без пересчёта', () => {
    expect(formatValue({ kind: 'NUMBER', value: '3.3', unit: 'm' })).toBe('3,3');
    expect(formatValue({ kind: 'COUNT', value: 9, unit: 'apartment' })).toBe('9');
  });

  it('нет значения — прочерк, а не ноль', () => {
    expect(formatValue(null)).toBe('—');
    expect(formatValue(undefined)).toBe('—');
  });

  it('значение перечня показывается его названием', () => {
    const type = factType({
      value_kind: 'ENUM',
      options: [{ value: 'RESIDENTIAL', title: 'жилой' }],
    });
    expect(formatValue({ kind: 'ENUM', value: 'RESIDENTIAL' }, type)).toBe('жилой');
  });

  it('запись документа видна, если она отличается от канонической', () => {
    const height = fact({
      value: { kind: 'NUMBER', value: '3.3', unit: 'm' },
      stated_value: { kind: 'NUMBER', value: '3300', unit: 'mm' },
    });
    expect(statedNote(height)).toBe('в документе: 3300 мм');
    expect(statedNote(fact())).toBeNull();
  });
});
