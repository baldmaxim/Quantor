import type { CadPipelineSheetRead } from '@quantor/api-client';

import { formatFloorTitle, formatFloorTitleFull } from './floor-title';

/**
 * Поиск по листам панели «Обработка»: номер листа, наименование и этаж (кратко и полностью).
 * Без учёта регистра и «ё»; запрос режется на слова, лист подходит, если в нём есть каждое.
 */

export type SearchableSheet = Pick<
  CadPipelineSheetRead,
  'page_index' | 'page_label' | 'title' | 'floor_title'
>;

const normalize = (text: string): string => text.toLocaleLowerCase('ru').replaceAll('ё', 'е');

export const sheetSearchText = (sheet: SearchableSheet): string =>
  normalize(
    [
      `лист ${sheet.page_label ?? sheet.page_index + 1}`,
      sheet.title ?? '',
      formatFloorTitle(sheet.floor_title, ''),
      formatFloorTitleFull(sheet.floor_title) ?? '',
    ].join(' '),
  );

export const matchesSheetQuery = (sheet: SearchableSheet, query: string): boolean => {
  const words = normalize(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const text = sheetSearchText(sheet);
  return words.every((word) => text.includes(word));
};
