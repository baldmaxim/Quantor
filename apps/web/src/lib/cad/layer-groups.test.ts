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
    expect(keysOf(['A-WALL', 'Doors', 'WINDOW-1', '0'])).toEqual({
      'A-WALL': 'walls',
      Doors: 'doors',
      'WINDOW-1': 'windows',
      '0': 'other',
    });
  });

  it('кириллица и «ё/е»', () => {
    expect(keysOf(['Стены', 'ДВЕРИ', 'Окна', 'Шахты', 'Утеплитель'])).toEqual({
      Стены: 'walls',
      ДВЕРИ: 'doors',
      Окна: 'windows',
      Шахты: 'shafts',
      Утеплитель: 'insulation',
    });
  });

  it('слои движка попадают в свою группу', () => {
    expect(
      keysOf([
        '01_КЛАДКА_80',
        '01_КЛАДКА_200',
        '01_КЛАДКА_НЕ_ОПРЕДЕЛЕНА',
        '03_ДВЕРИ_БЛОКИ',
        '03_ВОРОТА_БЛОКИ',
        '04_ОКНА',
        '04_ОКОННЫЕ_ПРОФИЛИ_КАНДИДАТЫ',
        '05_УТЕПЛИТЕЛЬ',
        '09_ШАХТЫ',
        '99_ТРЕБУЕТ_РАЗБОРА',
      ]),
    ).toEqual({
      '01_КЛАДКА_80': 'walls',
      '01_КЛАДКА_200': 'walls',
      '01_КЛАДКА_НЕ_ОПРЕДЕЛЕНА': 'walls',
      '03_ДВЕРИ_БЛОКИ': 'doors',
      '03_ВОРОТА_БЛОКИ': 'doors',
      '04_ОКНА': 'windows',
      '04_ОКОННЫЕ_ПРОФИЛИ_КАНДИДАТЫ': 'windows',
      '05_УТЕПЛИТЕЛЬ': 'insulation',
      '09_ШАХТЫ': 'shafts',
      '99_ТРЕБУЕТ_РАЗБОРА': 'other',
    });
  });

  it('служебные AUX_ и QA_ не показываются (без учёта регистра)', () => {
    expect(
      groupLayers([
        'AUX_КЛАДКА_ШТРИХОВКА',
        'aux_контуры_стен',
        'QA_ЛИФТОВЫЕ_ВХОДЫ_НЕ_ДВЕРИ',
        'qa_маркеры_не_учитывать',
        '01_КЛАДКА_100',
      ]),
    ).toEqual([{ key: 'walls', label: 'Кладка и перегородки', indices: [4] }]);
  });

  it('02_МОНОЛИТ в списке слоёв нет: им управляют строки «Монолит»', () => {
    expect(groupLayers(['02_МОНОЛИТ', '02_монолит_стены'])).toEqual([]);
  });

  it('прежние группы (оси, размеры, тексты, штриховка…) удалены: такие слои - «Прочее»', () => {
    expect(keysOf(['GRID', 'DIMS', 'TEXT', 'HATCH', 'ROOMS', 'A-STAIR', 'S-COLS', 'Проёмы'])).toEqual({
      GRID: 'other',
      DIMS: 'other',
      TEXT: 'other',
      HATCH: 'other',
      ROOMS: 'other',
      'A-STAIR': 'other',
      'S-COLS': 'other',
      Проёмы: 'other',
    });
  });

  it('дверной проём - дверь: первое совпадение по порядку групп', () => {
    expect(keysOf(['DOOR_OPENING_019'])).toEqual({ DOOR_OPENING_019: 'doors' });
  });

  it('порядок групп фиксирован, индексы по возрастанию, пустые группы не показываются', () => {
    const groups = groupLayers(['0', '09_ШАХТЫ', 'WALLS', 'A-WALL-2', 'DOORS', '05_УТЕПЛИТЕЛЬ', '04_ОКНА']);
    expect(groups.map((group) => group.key)).toEqual([
      'walls',
      'doors',
      'windows',
      'shafts',
      'insulation',
      'other',
    ]);
    expect(groups[0]?.indices).toEqual([2, 3]);
    expect(groups[0]?.label).toBe('Кладка и перегородки');
    expect(groupLayers([])).toEqual([]);
  });
});
