import type {
  CalcConfidence,
  CalcDiscipline,
  CalcDocumentStage,
  CalcFactSubject,
  CalcFactTypeRead,
  CalcFactUsage,
  CalcReadinessStatus,
  CalcRequirementLevel,
  CalcReviewStatus,
  CalcSourceClass,
  CalcTableKind,
  CalcFactRead,
} from '@quantor/api-client';

import type { StatusView } from '@/lib/format';

/**
 * Подписи экрана «Исходные данные». Единственное место, где решается, как называется
 * состояние факта или требования: компоненты берут подписи отсюда и не считают сами.
 */

export const READINESS_STATUS: Readonly<Record<CalcReadinessStatus, StatusView>> = {
  FOUND: { label: 'найдено', tone: 'success' },
  DERIVABLE: { label: 'выводимо', tone: 'accent' },
  CONFLICTED: { label: 'расходится', tone: 'danger' },
  MANUAL_REQUIRED: { label: 'нужен ввод', tone: 'warning' },
  UNKNOWN: { label: 'не определено', tone: 'warning' },
  MISSING: { label: 'не найдено', tone: 'warning' },
  NOT_INSPECTED: { label: 'не проверено', tone: 'neutral' },
};

export const LEVEL_TITLES: Readonly<Record<CalcRequirementLevel, string>> = {
  REQUIRED: 'обязательные',
  DESIRABLE: 'желательные',
  OPTIONAL: 'дополнительные',
  DERIVABLE: 'выводимые',
};

export const LEVEL_SHORT: Readonly<Record<CalcRequirementLevel, string>> = {
  REQUIRED: 'обязательно',
  DESIRABLE: 'желательно',
  OPTIONAL: 'дополнительно',
  DERIVABLE: 'выводится',
};

export const USAGE: Readonly<Record<CalcFactUsage, StatusView>> = {
  USED: { label: 'да', tone: 'success' },
  AGREES: { label: 'согласуется', tone: 'success' },
  NOT_CHOSEN: { label: 'нет — выбрано другое', tone: 'neutral' },
  CONFLICT: { label: 'нет — расхождение', tone: 'danger' },
  EXCLUDED_VOR: { label: 'нет — ВОР, только сверка', tone: 'warning' },
  REJECTED: { label: 'нет — отклонено', tone: 'neutral' },
};

export const CONFIDENCE_TITLES: Readonly<Record<CalcConfidence, string>> = {
  HIGH: 'высокая',
  MEDIUM: 'средняя',
  LOW: 'низкая',
};

export const REVIEW_TITLES: Readonly<Record<CalcReviewStatus, string>> = {
  UNREVIEWED: 'не проверено',
  CONFIRMED: 'подтверждено',
  REJECTED: 'отклонено',
};

export const STAGE_TITLES: Readonly<Record<CalcDocumentStage, string>> = {
  P: 'П',
  RD: 'РД',
  UNKNOWN: 'не указана',
};

export const DISCIPLINE_TITLES: Readonly<Record<CalcDiscipline, string>> = {
  VK: 'ВК',
  OV: 'ОВ',
  EOM: 'ЭОМ',
  SS: 'СС',
  APT: 'АПТ',
};

export const SOURCE_CLASS_TITLES: Readonly<Record<CalcSourceClass, string>> = {
  ARCHITECTURE: 'АР',
  APARTMENT_SCHEDULE: 'Квартирография',
  ROOM_SCHEDULE: 'Экспликация помещений',
  MEP_DESIGN: 'Инженерный раздел',
  CONSUMER_TABLE: 'Таблица потребителей',
  AIR_EXCHANGE_TABLE: 'Таблица воздухообменов',
  FIXTURE_TABLE: 'Таблица санприборов',
  EXPLANATORY_NOTE: 'Пояснительная записка',
  TECHNICAL_CONDITIONS: 'ТУ',
  ADJACENT_TASK: 'Задание смежного раздела',
  BRAND_LIST: 'Бренд-лист',
  TECHNICAL_REQUIREMENTS: 'Технические требования',
  CUSTOMER_VOR: 'ВОР Заказчика',
  MANUAL: 'Ручной ввод',
};

/** Классы, которые можно заявить документу перед сбором: ручной ввод — не документ. */
export const DOCUMENT_CLASSES: readonly CalcSourceClass[] = (
  Object.keys(SOURCE_CLASS_TITLES) as CalcSourceClass[]
).filter((item) => item !== 'MANUAL');

export const TABLE_KIND_TITLES: Readonly<Record<CalcTableKind, string>> = {
  APARTMENT_EXPLICATION: 'экспликации квартир',
  ROOM_EXPLICATION: 'экспликации помещений',
  PARKING_STORAGE: 'машиноместа и кладовые',
  APARTMENT_SUMMARY: 'квартирография',
  SANITARY_FIXTURES: 'санитарные приборы',
  WATER_CONSUMERS: 'потребители воды',
  LOADS: 'нагрузки',
  AIR_EXCHANGE: 'воздухообмены',
  EQUIPMENT_SPEC: 'спецификации',
  UNKNOWN: 'не определены',
};

const UNIT_TITLES: Readonly<Record<string, string>> = {
  m: 'м',
  cm: 'см',
  mm: 'мм',
  m2: 'м²',
  kPa: 'кПа',
  MPa: 'МПа',
  bar: 'бар',
  m_h2o: 'м вод. ст.',
  m3_h: 'м³/ч',
  l_s: 'л/с',
  m3_day: 'м³/сут',
  l_day: 'л/сут',
  degC: '°C',
};

export const unitTitle = (unit: string | null | undefined): string =>
  unit ? (UNIT_TITLES[unit] ?? unit) : '';

/** Десятичная запятая, как в документах. Строка остаётся строкой: число не пересчитывается. */
const decimal = (text: string): string => text.replace('.', ',');

const floorTitle = (floor: string): string => floor.replace('..', '–');

export const formatSubject = (subject: CalcFactSubject, qualifierTitle?: string): string => {
  const parts: string[] = [];
  if (subject.building) parts.push(`корп. ${subject.building}`);
  if (subject.section) parts.push(`секц. ${subject.section}`);
  if (subject.floor) parts.push(`эт. ${floorTitle(subject.floor)}`);
  if (subject.room) parts.push(`пом. ${subject.room}`);
  if (subject.qualifier) parts.push(qualifierTitle ?? subject.qualifier);
  return parts.length > 0 ? parts.join(' · ') : 'проект';
};

export const formatSystem = (subject: CalcFactSubject): string =>
  subject.system_code && subject.discipline
    ? `${DISCIPLINE_TITLES[subject.discipline]} · ${subject.system_code}`
    : '—';

type FactValue = CalcFactRead['value'];

/** Значение без единицы: единица — отдельная колонка. «Не определено» никогда не 0. */
export const formatValue = (
  value: FactValue | null | undefined,
  type?: CalcFactTypeRead,
): string => {
  if (!value) return '—';
  switch (value.kind) {
    case 'NUMBER':
      return decimal(value.value);
    case 'COUNT':
      return String(value.value);
    case 'BOOLEAN':
      return value.value ? 'да' : 'нет';
    case 'ENUM':
      return type?.options.find((option) => option.value === value.value)?.title ?? value.value;
    case 'TEXT':
      return value.value;
    case 'RANGE': {
      const low = value.low ? `от ${decimal(value.low)}` : '';
      const high = value.high ? `до ${decimal(value.high)}` : '';
      return [low, high].filter(Boolean).join(' ');
    }
    default:
      return '—';
  }
};

/** Как значение записано в документе, если оно отличается от канонического. */
export const statedNote = (fact: CalcFactRead): string | null => {
  const stated = fact.stated_value;
  if (stated.kind !== 'NUMBER' || fact.value.kind !== 'NUMBER') return null;
  if (stated.value === fact.value.value && stated.unit === fact.value.unit) return null;
  return `в документе: ${decimal(stated.value)} ${unitTitle(stated.unit)}`.trim();
};
