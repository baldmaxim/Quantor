import type { ScaleCalibrationRead } from '@quantor/api-client';

/**
 * Выбор листов для CAD-преобразования (ADR-0036): лист выбирает человек, масштаб берёт сервер
 * из калибровки листа (ADR-0018). Здесь - чистые правила выбора и разбор отказа сервера.
 */

/** Предел страниц в одном задании (контракт `CadConvertCreate.pages`). */
export const MAX_CAD_PAGES = 50;

/** Известность калибровки листа: `unknown` - статус прочитать нельзя (флаг ручного обмера выключен). */
export type SheetCalibrationState = 'calibrated' | 'missing' | 'unknown' | 'loading';

/** Действующая калибровка - та, что помечена `is_default`. */
export const hasDefaultCalibration = (
  calibrations: readonly ScaleCalibrationRead[] | undefined,
): boolean => calibrations?.some((item) => item.is_default) === true;

/** Добавляет или убирает страницу; сверх предела новая страница не добавляется. */
export const toggleSheetPage = (selected: readonly number[], pageIndex: number): number[] => {
  if (selected.includes(pageIndex)) {
    return selected.filter((item) => item !== pageIndex);
  }
  if (selected.length >= MAX_CAD_PAGES) {
    return [...selected];
  }
  return [...selected, pageIndex].sort((a, b) => a - b);
};

/** Выбранные страницы, у которых калибровки точно нет. */
export const missingCalibrationPages = (
  selected: readonly number[],
  states: ReadonlyMap<number, SheetCalibrationState>,
): number[] => selected.filter((index) => states.get(index) === 'missing');

/** Запуск возможен: выбран хотя бы один лист, и ни у одного нет заведомо отсутствующей калибровки. */
export const canLaunchCad = (
  selected: readonly number[],
  states: ReadonlyMap<number, SheetCalibrationState>,
): boolean =>
  selected.length > 0 &&
  selected.length <= MAX_CAD_PAGES &&
  missingCalibrationPages(selected, states).length === 0 &&
  selected.every((index) => states.get(index) !== 'loading');

/**
 * Страницы (индексы с 0) из отказа `CAD_CALIBRATION_REQUIRED`: сервер кладёт их в
 * `detail.issue.pages` через запятую. Нет поля - пустой список.
 */
export const calibrationPagesOf = (error: unknown): number[] => {
  const read = (value: unknown): unknown =>
    (value as { detail?: { issue?: { pages?: unknown } } } | null)?.detail?.issue?.pages;
  const raw = read(error) ?? read((error as { error?: unknown } | null)?.error) ?? undefined;
  if (typeof raw !== 'string') {
    return [];
  }
  return raw
    .split(',')
    .map((part) => part.trim())
    .filter((part) => /^\d{1,6}$/.test(part))
    .map(Number);
};

/** Текст отказа 409: список страниц с 1, как их видит человек. */
export const calibrationRequiredText = (pages: readonly number[]): string =>
  pages.length === 0
    ? 'Откалибруйте масштаб выбранных листов и запустите снова.'
    : `Откалибруйте масштаб листов и запустите снова: стр. ${pages.map((index) => index + 1).join(', ')}.`;

/** Ссылка на лист в рабочей области (просмотрщик): `page` - номер листа в ревизии с 1. */
export const sheetWorkspaceHref = (
  projectId: string,
  revisionId: string,
  listPosition: number,
): string => `/projects/${projectId}/workspace?revision=${revisionId}&page=${listPosition + 1}`;

/** Что сказать, когда калибровку сделать нельзя: создание закрыто флагом `takeoff.manual`. */
export const CALIBRATION_UNAVAILABLE_TEXT =
  'Калибровка недоступна: включите в пространстве флаг ручного обмера';
