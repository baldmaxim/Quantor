import type { CalcFactTypeRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { buildSubject, buildValue, subjectFields } from './manual';

const type = (overrides: Partial<CalcFactTypeRead>): CalcFactTypeRead => ({
  key: 'floor.height',
  title: 'Высота этажа',
  description: '',
  value_kind: 'NUMBER',
  required_subject: ['building', 'floor'],
  allowed_subject: ['building', 'section', 'floor'],
  unit: 'm',
  unit_title: 'м',
  options: [],
  qualifier_options: [],
  customer_vor_admissible: false,
  ...overrides,
});

const subject = {
  building: '1',
  section: '',
  floor: '2..24',
  room: '',
  qualifier: '',
  discipline: null,
  systemCode: '',
};
const value = { number: '', low: '', high: '', choice: '' };

describe('ручной ввод факта', () => {
  it('поля места — по типу факта, обязательные отмечены', () => {
    expect(subjectFields(type({}))).toEqual([
      { field: 'building', required: true },
      { field: 'section', required: false },
      { field: 'floor', required: true },
    ]);
  });

  it('место без пустых полей; обязательное пустым не уходит', () => {
    expect(buildSubject(type({}), subject)).toEqual({ building: '1', floor: '2..24' });
    expect(buildSubject(type({}), { ...subject, floor: ' ' })).toMatch(/этаж/);
  });

  it('система берётся для системных типов', () => {
    const system = type({
      key: 'system.function',
      value_kind: 'ENUM',
      required_subject: ['discipline', 'system_code'],
      allowed_subject: ['building', 'section', 'discipline', 'system_code'],
    });
    expect(buildSubject(system, { ...subject, discipline: 'VK', systemCode: 'Т3' })).toEqual({
      building: '1',
      discipline: 'VK',
      system_code: 'Т3',
    });
    expect(buildSubject(system, subject)).toBe('Не указана система');
  });

  it('число с запятой, ноль — значение, пустое — ошибка, а не 0', () => {
    expect(buildValue(type({}), { ...value, number: '3,3' })).toEqual({
      kind: 'NUMBER',
      value: '3.3',
      unit: 'm',
    });
    const count = type({ value_kind: 'COUNT', unit: 'apartment' });
    expect(buildValue(count, { ...value, number: '0' })).toEqual({ kind: 'COUNT', value: 0 });
    expect(typeof buildValue(count, value)).toBe('string');
    expect(typeof buildValue(type({}), { ...value, number: '3.3 м' })).toBe('string');
  });

  it('перечень и да/нет — только выбранное', () => {
    expect(buildValue(type({ value_kind: 'ENUM' }), { ...value, choice: 'COLD_WATER' })).toEqual({
      kind: 'ENUM',
      value: 'COLD_WATER',
    });
    expect(buildValue(type({ value_kind: 'BOOLEAN' }), { ...value, choice: 'false' })).toEqual({
      kind: 'BOOLEAN',
      value: false,
    });
    expect(typeof buildValue(type({ value_kind: 'BOOLEAN' }), value)).toBe('string');
  });
});
