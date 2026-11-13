import { describe, expect, it } from 'vitest';

import { matchesSheetQuery, type SearchableSheet } from './pipeline-search';

const sheet = (patch: Partial<SearchableSheet> = {}): SearchableSheet => ({
  page_index: 31,
  page_label: '32',
  title: 'План 14 этажа. Корпус 9',
  floor_title: null,
  ...patch,
});

describe('matchesSheetQuery', () => {
  it('пустой запрос пропускает всё', () => {
    expect(matchesSheetQuery(sheet(), '   ')).toBe(true);
  });

  it('ищет по номеру листа и наименованию без учёта регистра', () => {
    expect(matchesSheetQuery(sheet(), 'лист 32')).toBe(true);
    expect(matchesSheetQuery(sheet(), 'ПЛАН')).toBe(true);
    expect(matchesSheetQuery(sheet(), 'разрез')).toBe(false);
  });

  it('номер без подписи - по порядку страницы', () => {
    expect(matchesSheetQuery(sheet({ page_label: null }), 'лист 32')).toBe(true);
  });

  it('ищет по этажу из заголовка плана, все слова запроса', () => {
    const withFloor = sheet({
      title: null,
      floor_title: { corps: '9', section: '3', floors: ['14'] },
    });
    expect(matchesSheetQuery(withFloor, 'секция 3 14 эт')).toBe(true);
    expect(matchesSheetQuery(withFloor, 'к9')).toBe(true);
    expect(matchesSheetQuery(withFloor, 'корпус 5')).toBe(false);
  });

  it('ё и е равны', () => {
    expect(matchesSheetQuery(sheet({ title: 'Ёмкость' }), 'емкость')).toBe(true);
  });
});
