import { describe, expect, it } from 'vitest';

import { groupLayers } from './layer-groups';

const keysOf = (names: readonly string[]): Record<string, string> => {
  const result: Record<string, string> = {};
  groupLayers(names).forEach((group) =>
    group.indices.forEach((index) => {
      result[names[index] ?? ''] = group.key;
    }),
  );
  return result;
};

describe('groupLayers', () => {
  it('латинские имена: подстрока без учёта регистра', () => {
    expect(
      keysOf(['A-WALL', 'Doors', 'WINDOW-1', 'S-COLS', 'A-STAIR', 'ROOMS', 'GRID', 'DIMS', 'TEXT', 'HATCH', '0']),
    ).toEqual({
      'A-WALL': 'walls',
      Doors: 'doors',
      'WINDOW-1': 'windows',
      'S-COLS': 'columns',
      'A-STAIR': 'stairs',
      ROOMS: 'rooms',
      GRID: 'axes',
      DIMS: 'dimensions',
      TEXT: 'texts',
      HATCH: 'hatches',
      '0': 'other',
    });
  });

  it('кириллица и «ё/е»', () => {
    expect(keysOf(['Стены', 'ДВЕРИ', 'Окна', 'Проёмы', 'Проемы', 'Колонны', 'Лестница', 'Помещения', 'Оси', 'Размеры', 'Текст', 'Штриховка'])).toEqual({
      Стены: 'walls',
      ДВЕРИ: 'doors',
      Окна: 'windows',
      Проёмы: 'openings',
      Проемы: 'openings',
      Колонны: 'columns',
      Лестница: 'stairs',
      Помещения: 'rooms',
      Оси: 'axes',
      Размеры: 'dimensions',
      Текст: 'texts',
      Штриховка: 'hatches',
    });
  });

  it('настоящие слои движка попадают в свою группу', () => {
    expect(
      keysOf([
        '01_СТЕНЫ_КАНДИДАТЫ',
        '01_КОНТУРЫ_СТЕН',
        '01_КЛАДКА_И_ПЕРЕГОРОДКИ',
        '02_МОНОЛИТ_КАНДИДАТЫ',
        '03_ДВЕРИ_ПОЛОТНА_И_ДУГИ',
        '03_ВОРОТА_БЛОКИ',
        '04_ОКНА_КАНДИДАТЫ',
        '04_ОКОННЫЕ_ПРОФИЛИ_КАНДИДАТЫ',
        '10_ШТРИХОВКИ',
        '11_ТЕКСТ_И_МАРКИ',
        '13_РАЗМЕРЫ_КАНДИДАТЫ',
        '14_ОСИ_КАНДИДАТЫ',
        '06_ОБОРУДОВАНИЕ_КАНДИДАТЫ',
        '20_БЕЛЫЕ_МАСКИ',
        '90_ВСПОМОГАТЕЛЬНОЕ',
        '99_ТРЕБУЕТ_РАЗБОРА',
        '04_ПРОФИЛИ_ФАСАДА',
        '05_УТЕПЛИТЕЛЬ',
      ]),
    ).toEqual({
      '01_СТЕНЫ_КАНДИДАТЫ': 'walls',
      '01_КОНТУРЫ_СТЕН': 'walls',
      '01_КЛАДКА_И_ПЕРЕГОРОДКИ': 'walls',
      '02_МОНОЛИТ_КАНДИДАТЫ': 'columns',
      '03_ДВЕРИ_ПОЛОТНА_И_ДУГИ': 'doors',
      '03_ВОРОТА_БЛОКИ': 'doors',
      '04_ОКНА_КАНДИДАТЫ': 'windows',
      '04_ОКОННЫЕ_ПРОФИЛИ_КАНДИДАТЫ': 'windows',
      '10_ШТРИХОВКИ': 'hatches',
      '11_ТЕКСТ_И_МАРКИ': 'texts',
      '13_РАЗМЕРЫ_КАНДИДАТЫ': 'dimensions',
      '14_ОСИ_КАНДИДАТЫ': 'axes',
      '06_ОБОРУДОВАНИЕ_КАНДИДАТЫ': 'other',
      '20_БЕЛЫЕ_МАСКИ': 'other',
      '90_ВСПОМОГАТЕЛЬНОЕ': 'other',
      '99_ТРЕБУЕТ_РАЗБОРА': 'other',
      '04_ПРОФИЛИ_ФАСАДА': 'other',
      '05_УТЕПЛИТЕЛЬ': 'other',
    });
  });

  it('слои контроля QA_ - всегда «Прочее», даже если в имени есть «двери»', () => {
    expect(keysOf(['QA_ЛИФТОВЫЕ_ВХОДЫ_НЕ_ДВЕРИ', 'QA_МАРКЕРЫ_НЕ_УЧИТЫВАТЬ'])).toEqual({
      QA_ЛИФТОВЫЕ_ВХОДЫ_НЕ_ДВЕРИ: 'other',
      QA_МАРКЕРЫ_НЕ_УЧИТЫВАТЬ: 'other',
    });
  });

  it('дверной проём - дверь: первое совпадение по порядку групп', () => {
    expect(keysOf(['DOOR_OPENING_019'])).toEqual({ DOOR_OPENING_019: 'doors' });
  });

  it('порядок групп фиксирован, индексы по возрастанию, пустые группы не показываются', () => {
    const groups = groupLayers(['0', 'TEXT', 'WALLS', 'A-WALL-2', 'DOORS']);
    expect(groups.map((group) => group.key)).toEqual(['walls', 'doors', 'texts', 'other']);
    expect(groups[0]?.indices).toEqual([2, 3]);
    expect(groups[0]?.label).toBe('Стены');
    expect(groupLayers([])).toEqual([]);
  });
});
