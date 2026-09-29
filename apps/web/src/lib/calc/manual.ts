import type { CalcFactCreate, CalcFactSubject, CalcFactTypeRead } from '@quantor/api-client';

/**
 * Ручной ввод факта (ADR-0030, PROMPT 01–02): поля места по типу факта и значение по виду.
 *
 * Последний путь после документов и вывода. Экран ничего не пересчитывает: единица —
 * каноническая единица типа, значение уходит строкой, проверяет и переводит сервер. Пустое
 * поле значением не становится — ноль вводится явно.
 */

export type SubjectField = 'building' | 'section' | 'floor' | 'room' | 'qualifier';
export type FactValue = CalcFactCreate['value'];

export interface ISubjectInput {
  building: string;
  section: string;
  floor: string;
  room: string;
  qualifier: string;
  discipline: CalcFactSubject['discipline'];
  systemCode: string;
}

export interface IValueInput {
  number: string;
  low: string;
  high: string;
  choice: string;
}

const ORDER: readonly SubjectField[] = ['building', 'section', 'floor', 'room'];

export const SUBJECT_TITLES: Readonly<Record<SubjectField, string>> = {
  building: 'Корпус',
  section: 'Секция',
  floor: 'Этаж или группа этажей',
  room: 'Помещение',
  qualifier: 'Вид',
};

/** Поля места, которые тип факта допускает; обязательные — отмечены. Система — отдельно. */
export const subjectFields = (
  type: CalcFactTypeRead,
): { field: SubjectField; required: boolean }[] => {
  const fields: { field: SubjectField; required: boolean }[] = ORDER.filter((field) =>
    type.allowed_subject.includes(field),
  ).map((field) => ({ field, required: type.required_subject.includes(field) }));
  if (type.qualifier_options.length > 0) fields.push({ field: 'qualifier', required: true });
  return fields;
};

export const needsSystem = (type: CalcFactTypeRead): boolean =>
  type.required_subject.includes('system_code');

const trimmed = (value: string): string | null => {
  const text = value.trim();
  return text.length > 0 ? text : null;
};

/** Место факта или текст ошибки. Обязательное поле пустым не уходит. */
export const buildSubject = (
  type: CalcFactTypeRead,
  input: ISubjectInput,
): CalcFactSubject | string => {
  const subject: CalcFactSubject = {};
  for (const { field, required } of subjectFields(type)) {
    const value = trimmed(input[field]);
    if (value === null) {
      if (required) return `Не заполнено: ${SUBJECT_TITLES[field].toLowerCase()}`;
      continue;
    }
    subject[field] = value;
  }
  if (needsSystem(type)) {
    const code = trimmed(input.systemCode);
    if (code === null || input.discipline == null) return 'Не указана система';
    subject.discipline = input.discipline;
    subject.system_code = code;
  }
  return subject;
};

const DECIMAL = /^-?\d+([.,]\d+)?$/;
const INTEGER = /^\d+$/;

const decimal = (text: string): string | null => {
  const value = text.trim().replace(',', '.');
  return DECIMAL.test(value) ? value : null;
};

/** Значение по виду типа факта или текст ошибки. */
export const buildValue = (type: CalcFactTypeRead, input: IValueInput): FactValue | string => {
  switch (type.value_kind) {
    case 'NUMBER': {
      const value = decimal(input.number);
      if (value === null) return 'Введите число, например 3,3';
      if (!type.unit) return 'У типа факта нет единицы';
      return { kind: 'NUMBER', value, unit: type.unit };
    }
    case 'COUNT': {
      const value = input.number.trim();
      if (!INTEGER.test(value)) return 'Введите целое число, 0 — тоже значение';
      return { kind: 'COUNT', value: Number(value) };
    }
    case 'RANGE': {
      const low = input.low.trim() ? decimal(input.low) : null;
      const high = input.high.trim() ? decimal(input.high) : null;
      if ((input.low.trim() && low === null) || (input.high.trim() && high === null)) {
        return 'Границы — числа';
      }
      if (low === null && high === null) return 'Укажите хотя бы одну границу';
      if (!type.unit) return 'У типа факта нет единицы';
      return { kind: 'RANGE', low, high, unit: type.unit };
    }
    case 'ENUM':
      return input.choice ? { kind: 'ENUM', value: input.choice } : 'Выберите значение';
    case 'BOOLEAN':
      return input.choice === 'true' || input.choice === 'false'
        ? { kind: 'BOOLEAN', value: input.choice === 'true' }
        : 'Выберите «да» или «нет»';
    case 'TEXT':
      return trimmed(input.number) ? { kind: 'TEXT', value: input.number.trim() } : 'Введите текст';
    default:
      return 'Неизвестный вид значения';
  }
};
