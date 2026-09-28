import type {
  CalcAmount,
  CalcCompleteness,
  CalcPassportStatus,
  CalcQuantityCategory,
  CalcQuantityDerivation,
  CalcRuleReadiness,
  CalcSemanticsStatus,
} from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';

/**
 * Подписи рабочего калькулятора ВК (ADR-0030, PROMPT 06). Значения, статусы и полнота — ответ
 * сервера; экран не складывает и не округляет: диапазон показывается диапазоном, «не
 * определено» — словами, а не нулём.
 */

export const PASSPORT_STATUS: Record<CalcPassportStatus, { label: string; tone: BadgeTone }> = {
  READY: { label: 'готово', tone: 'success' },
  PARTIAL: { label: 'частично', tone: 'accent' },
  BLOCKED: { label: 'заблокировано', tone: 'warning' },
};

export const COMPLETENESS: Record<CalcCompleteness, { label: string; tone: BadgeTone }> = {
  COMPLETE: { label: 'определено', tone: 'success' },
  RANGE: { label: 'диапазон', tone: 'accent' },
  PARTIAL: { label: 'частично', tone: 'accent' },
  UNRESOLVED_BREAKDOWN: { label: 'без разбивки по диаметрам', tone: 'neutral' },
  BLOCKED: { label: 'не определено', tone: 'warning' },
};

export const DERIVATION_TITLES: Record<CalcQuantityDerivation, string> = {
  OBSERVED: 'по документации',
  CALCULATED: 'расчёт',
  TOPOLOGY: 'топология графа',
  RULE: 'утверждённое правило',
  FALLBACK: 'резервный метод',
  AGGREGATE: 'итог составляющих',
  NOT_DETERMINED: '—',
};

export const CATEGORY_TITLES: Record<CalcQuantityCategory, string> = {
  PIPE: 'Трубопроводы',
  INSULATION: 'Изоляция',
  FITTING: 'Фитинги',
  VALVE: 'Арматура',
  EQUIPMENT: 'Оборудование',
  SUPPORT: 'Крепления',
  SLEEVE: 'Проходки и гильзы',
  CONNECTION: 'Подключения',
  OTHER: 'Прочее',
};

export const RULE_READINESS: Record<CalcRuleReadiness, { label: string; tone: BadgeTone }> = {
  READY: { label: 'утверждено', tone: 'success' },
  DRAFT: { label: 'черновик — ждёт инженера', tone: 'accent' },
  SOURCE_REQUIRED: { label: 'нужен источник', tone: 'warning' },
  IMPLEMENTATION_REQUIRED: { label: 'методика не реализована', tone: 'neutral' },
};

export const SEMANTICS: Record<CalcSemanticsStatus, { label: string; tone: BadgeTone }> = {
  CONFIRMED: { label: 'назначение подтверждено', tone: 'success' },
  MISSING: { label: 'назначение не подтверждено', tone: 'warning' },
  MISMATCH: { label: 'назначение другое', tone: 'danger' },
  CONFLICT: { label: 'назначение спорное', tone: 'warning' },
};

export const LAYER_TITLES: Record<string, string> = {
  A: 'Потребность',
  B: 'Структура',
  C: 'Сверка',
  D: 'Параметры количеств',
  T: 'Тендер',
};

const UNIT_TITLES: Record<string, string> = {
  m: 'м',
  piece: 'шт.',
  set: 'компл.',
  riser: 'ст.',
  floor: 'эт.',
  apartment: 'кв.',
  slab: 'перекр.',
  zone: 'зон',
  shaft: 'шахт',
  fixture: 'приб.',
};

export const unitTitle = (unit: string | null | undefined): string =>
  unit ? (UNIT_TITLES[unit] ?? unit) : '';

const number = (value: string): string => value.replace('.', ',');

/** «144,4–216,6 м», «45 м», «не определено». Середина диапазона не показывается никогда. */
export const amountText = (amount: CalcAmount, unit?: string | null): string => {
  const suffix = unitTitle(unit);
  if (amount.value != null) {
    return `${number(amount.value)} ${suffix}`.trim();
  }
  if (amount.low != null && amount.high != null) {
    return `${number(amount.low)}–${number(amount.high)} ${suffix}`.trim();
  }
  return 'не определено';
};

export type VkTab =
  'overview' | 'inputs' | 'calculation' | 'structure' | 'volumes' | 'assumptions' | 'unresolved';

export const VK_TABS: readonly { value: VkTab; label: string }[] = [
  { value: 'overview', label: 'Обзор' },
  { value: 'inputs', label: 'Исходные данные' },
  { value: 'calculation', label: 'Расчёт' },
  { value: 'structure', label: 'Структура' },
  { value: 'volumes', label: 'Объёмы' },
  { value: 'assumptions', label: 'Допущения' },
  { value: 'unresolved', label: 'Неопределённости' },
];
