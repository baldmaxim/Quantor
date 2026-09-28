import type { CalcRunStatus, CalcScenario, CalcStepStatus } from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';

/**
 * Подписи запусков расчётного ядра (ADR-0030, PROMPT 04). Значения, статусы и причины — ответ
 * сервера; здесь только слова, тона и отображение чисел.
 */

export const RUN_STATUS: Record<CalcRunStatus, { label: string; tone: BadgeTone }> = {
  SUCCEEDED: { label: 'рассчитано', tone: 'success' },
  BLOCKED: { label: 'заблокировано', tone: 'warning' },
  FAILED: { label: 'ошибка', tone: 'danger' },
};

export const SCENARIO_TITLES: Record<CalcScenario, string> = {
  MINIMUM: 'Минимум',
  EXPECTED: 'Ожидаемый',
  TENDER_SAFE: 'Тендерный запас',
};

export const STEP_STATUS_TITLES: Record<CalcStepStatus, string> = {
  EXECUTED: 'посчитано',
  REUSED: 'взято из прежнего запуска',
  NOT_APPLIED: 'не применено',
};

/** Точное число сервера для чтения: запятая вместо точки, значение не меняется. */
export const formatExact = (value: string): string => value.replace('.', ',');
