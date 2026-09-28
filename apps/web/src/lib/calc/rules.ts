import type {
  CalcLegacyAction,
  CalcLegacyCatalog,
  CalcLegacyClass,
  CalcLegacyHazard,
  CalcRuleStatus,
  CalcRuleType,
} from '@quantor/api-client';
import type { BadgeTone } from '@/components/ui';

/**
 * Подписи реестра правил (ADR-0030, PROMPT 03). «Разрешено в расчёте» интерфейс не вычисляет:
 * это ответ сервера, здесь — только слова и тона.
 */

export const RULE_TYPE_TITLES: Record<CalcRuleType, string> = {
  PHYSICS: 'Физика',
  GEOMETRY: 'Геометрия',
  NORMATIVE: 'Норматив',
  MANUFACTURER: 'Производитель',
  ENGINEERING: 'Инженерная методика',
  TENDER_ASSUMPTION: 'Тендерное допущение',
};

export const RULE_STATUS: Record<CalcRuleStatus, { label: string; tone: BadgeTone }> = {
  DRAFT: { label: 'черновик', tone: 'neutral' },
  UNVERIFIED_LEGACY: { label: 'не проверено', tone: 'warning' },
  APPROVED: { label: 'утверждено', tone: 'success' },
  DEPRECATED: { label: 'устарело', tone: 'neutral' },
  REJECTED: { label: 'отклонено', tone: 'danger' },
};

export const LEGACY_CATALOG_TITLES: Record<CalcLegacyCatalog, string> = {
  VK: 'ВК',
  K: 'Канализация',
  OV: 'ОВ',
  VRF: 'VRF',
  FIRE: 'Пожаротушение',
};

export const LEGACY_CLASS_TITLES: Record<CalcLegacyClass, string> = {
  PHYSICS: 'физика',
  NORMATIVE: 'норматив',
  MANUFACTURER: 'производитель',
  GEOMETRY: 'геометрия',
  HEURISTIC: 'эвристика',
  TENDER: 'тендерное',
  UNKNOWN_ORIGIN: 'происхождение неизвестно',
  ERROR: 'ошибочное',
  NONE: 'без правила',
};

export const LEGACY_HAZARD_TITLES: Record<CalcLegacyHazard, string> = {
  DOUBLE_MULTIPLICATION: 'двойное умножение',
  CONFLICTING_CONSTANTS: 'разные константы',
  HIDDEN_DEFAULT: 'скрытое умолчание',
  SUBSTITUTED_VALUES: 'подставленные значения',
  UNIT_ERROR: 'ошибка единиц',
  DEFECT: 'дефект',
};

export const LEGACY_ACTION_TITLES: Record<CalcLegacyAction, string> = {
  KEEP_AS_LEGACY: 'оставить как допущение',
  REPLACE: 'заменить методикой',
  MAKE_INPUT: 'сделать входом',
  REJECT: 'отказаться',
  OUT_OF_SCOPE: 'вне контура',
  IDEA: 'идея',
};
