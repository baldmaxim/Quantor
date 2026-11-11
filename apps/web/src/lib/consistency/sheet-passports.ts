import type { BadgeTone } from '@quantor/ui';
import type { SheetPassportOut, SheetPassportStatus } from '@quantor/api-client';

/**
 * Паспорт листа (ADR-0043, С1): подписи словарей и чистые помощники таблицы «Листы комплекта».
 * Сами значения (марки разделов, типы листов) — словарь сервера: здесь только русские подписи.
 */

export const PASSPORT_PAGE_SIZE = 500;
/** Предел пачки в `bulk-status` на сервере. */
export const BULK_MAX = 1000;
export const EMPTY_CELL = '—';

export const SHEET_KIND_LABELS: Readonly<Record<string, string>> = {
  floor_plan: 'План',
  section: 'Разрез',
  facade: 'Фасад',
  scheme: 'Схема',
  table: 'Таблица',
  text: 'Текст',
  general_data: 'Общие данные',
  other: 'Прочее',
};

/** Порядок типов в выпадающем списке правки. */
export const SHEET_KIND_VALUES: readonly string[] = Object.keys(SHEET_KIND_LABELS);

export const STAGE_VALUES: readonly string[] = ['П', 'РД'];

export const STATUS_LABELS: Readonly<Record<SheetPassportStatus, string>> = {
  candidate: 'Кандидат',
  confirmed: 'Подтверждён',
  rejected: 'Отклонён',
};

export const STATUS_TONES: Readonly<Record<SheetPassportStatus, BadgeTone>> = {
  candidate: 'warning',
  confirmed: 'success',
  rejected: 'danger',
};

export const EVIDENCE_LABELS: Readonly<Record<string, string>> = {
  stamp: 'штамп',
  title: 'заголовок',
  page_label: 'метка стр.',
  file_name: 'имя файла',
  manual: 'вручную',
};

/** Подпись типа листа; незнакомое значение показывается как есть, пустое — прочерком. */
export const sheetKindLabel = (kind: string | null): string =>
  kind === null ? EMPTY_CELL : (SHEET_KIND_LABELS[kind] ?? kind);

/** Пустое значение — «—», а не 0 и не пустая ячейка. */
export const cellText = (value: string | number | null): string =>
  value === null || value === '' ? EMPTY_CELL : String(value);

/** Этажи «от–до»; один заданный край показывается один, ничего — прочерк. */
export const levelsText = (from: string | null, to: string | null): string => {
  if (from && to) {
    return from === to ? from : `${from}–${to}`;
  }
  return from ?? to ?? EMPTY_CELL;
};

export interface IFieldSource {
  readonly label: string;
  readonly snippet: string;
  readonly manual: boolean;
}

/** Источник значения поля из `evidence`; `null` — у поля нет доказательства. */
export const fieldSource = (row: SheetPassportOut, field: string): IFieldSource | null => {
  const item = row.evidence[field];
  if (!item) {
    return null;
  }
  return {
    label: EVIDENCE_LABELS[item.source] ?? item.source,
    snippet: item.snippet,
    manual: item.source === 'manual',
  };
};

/** Поиск по шифру и заголовку: без учёта регистра и лишних пробелов; пустой запрос — всё. */
export const matchesSearch = (row: SheetPassportOut, query: string): boolean => {
  const needle = query.trim().toLowerCase();
  if (needle === '') {
    return true;
  }
  return [row.code, row.title].some((value) => value?.toLowerCase().includes(needle));
};

/** Марки разделов из строк в порядке появления, без повторов. */
export const sectionMarksOf = (rows: readonly SheetPassportOut[]): string[] => {
  const marks = new Set<string>();
  for (const row of rows) {
    if (row.section_mark) {
      marks.add(row.section_mark);
    }
  }
  return [...marks];
};

export const confirmedCount = (rows: readonly SheetPassportOut[]): number =>
  rows.filter((row) => row.status === 'confirmed').length;
