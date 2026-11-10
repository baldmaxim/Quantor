import type { CadDecisionRead } from '@quantor/api-client';

import { extractCode } from '@/lib/errors';

import { cadErrorText } from './errors';

/**
 * Правила кнопок вкладки «Трассы»: что мешает действию. Сервер проверяет то же самое
 * (409 `CAD_OPEN_REMARKS` и др.), клиент лишь не предлагает заведомо невозможное.
 */

/** Границы вводов человека, как в контракте (`CadMepRoutesCreate`). */
export const ELEVATION_MIN_MM = -100_000;
export const ELEVATION_MAX_MM = 1_000_000;
export const FLOOR_HEIGHT_MIN_MM = 2000;
export const FLOOR_HEIGHT_MAX_MM = 6000;

/** Целое число миллиметров из текста («47600», «-1200»); иное - `null`. */
export const parseMm = (text: string): number | null => {
  const value = text.trim().replace(/\s/g, '');
  return /^-?\d{1,7}$/.test(value) ? Number(value) : null;
};

/** Пустое поле - «по документации»: ошибка только у заполненного неверно. */
export const elevationError = (text: string): string | null => {
  if (text.trim() === '') return null;
  const value = parseMm(text);
  if (value === null) return 'Отметка - целое число миллиметров.';
  if (value < ELEVATION_MIN_MM || value > ELEVATION_MAX_MM) {
    return `Отметка пола вне пределов ${ELEVATION_MIN_MM}…${ELEVATION_MAX_MM} мм.`;
  }
  return null;
};

export const floorHeightError = (text: string): string | null => {
  if (text.trim() === '') return null;
  const value = parseMm(text);
  if (value === null) return 'Высота - целое число миллиметров.';
  if (value < FLOOR_HEIGHT_MIN_MM || value > FLOOR_HEIGHT_MAX_MM) {
    return `Высота этажа вне пределов ${FLOOR_HEIGHT_MIN_MM}…${FLOOR_HEIGHT_MAX_MM} мм.`;
  }
  return null;
};

/** Число из поля: пусто - `null` («по документации»); неверное сюда не доходит (см. проверки). */
export const optionalMm = (text: string): number | null => (text.trim() === '' ? null : parseMm(text));

/** Замечания ещё не прочитаны (`null`) - действие отложено; открытые - блокируют. */
export const openRemarksBlock = (openRemarks: number | null): string | null => {
  if (openRemarks === null) return 'Замечания ещё загружаются.';
  if (openRemarks > 0) {
    return `Есть открытые замечания (${openRemarks}): закройте их или отметьте проверенными.`;
  }
  return null;
};

/** «Одобрить вид»: уже одобрен - решения нет; иначе только без открытых замечаний. */
export const approveBlock = (
  approval: CadDecisionRead | null | undefined,
  openRemarks: number | null,
): string | null => (approval ? 'Вид уже одобрен.' : openRemarksBlock(openRemarks));

/**
 * «Принять трассы»: уже приняты - решения нет; одобрение вида отозвано - принять нельзя;
 * иначе только без открытых замечаний.
 */
export const acceptBlock = (
  acceptance: CadDecisionRead | null | undefined,
  openRemarks: number | null,
  approvalRevoked = false,
): string | null => {
  if (acceptance) return 'Трассы уже приняты.';
  if (approvalRevoked) return 'Одобрение вида отозвано: принять эти трассы нельзя.';
  return openRemarksBlock(openRemarks);
};

/** Состояние route-задания, от которого зависит пересчёт. */
export interface IRecomputeState {
  readonly status: string;
  readonly accepted: boolean;
  readonly approvalRevoked: boolean;
}

/** «Пересчитать»: в работе, приняты или одобрение отозвано - нельзя; иначе доступно. */
export const recomputeBlock = ({ status, accepted, approvalRevoked }: IRecomputeState): string | null => {
  if (status === 'queued' || status === 'running') return 'Трассы считаются: дождитесь результата.';
  if (status !== 'succeeded' && status !== 'failed') return 'Задание отменено.';
  if (accepted) return 'Трассы приняты: сначала отзовите принятие.';
  if (approvalRevoked) return 'Одобрение вида отозвано: одобрите вид заново.';
  return null;
};

/** Отметка и высота, которые показывает форма пересчёта по умолчанию: только ввод человека. */
export const initialFloorText = (
  value: number | null | undefined,
  source: string | null | undefined,
): string => (source === 'operator' && value != null ? String(value) : '');

/** Коды отказа генератора, после которых нужен ручной ввод отметки и высоты. */
export const needsManualFloor = (code: string | null | undefined): boolean =>
  code === 'CAD_ELEVATION_NOT_FOUND' || code === 'CAD_FLOOR_HEIGHT_NOT_FOUND';

/** Текст отказа сервера по действиям с трассами. */
export const mepErrorText = (error: unknown): string =>
  extractCode(error) === 'CAD_INPUT_INVALID'
    ? 'Исходные данные вида не подходят для построения трасс.'
    : cadErrorText(error);
