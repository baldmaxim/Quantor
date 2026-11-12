import { describe, expect, it } from 'vitest';

import {
  categoryOfKind,
  categoryOfLayer,
  hiddenCategoriesOf,
  hiddenConstructionIdsOf,
  isHiddenByLayers,
  layerGroupKeyOf,
  withoutHiddenCategories,
} from './layer-categories';

describe('категория слоя по префиксу имени', () => {
  it('кладка, монолит, двери - по префиксу, регистр не важен', () => {
    expect(categoryOfLayer('01_КЛАДКА')).toBe('masonry');
    expect(categoryOfLayer('01_кладка_наружная')).toBe('masonry');
    expect(categoryOfLayer('02_МОНОЛИТ')).toBe('monolith');
    expect(categoryOfLayer('02_Монолит_стены')).toBe('monolith');
    expect(categoryOfLayer('03_ДВЕРИ')).toBe('door');
    expect(categoryOfLayer('03_двери_1')).toBe('door');
  });

  it('C112 - и латинская C, и кириллическая С', () => {
    expect(categoryOfLayer('07_C112')).toBe('frame_partition');
    expect(categoryOfLayer('07_С112')).toBe('frame_partition');
    expect(categoryOfLayer('07_c112_гкл')).toBe('frame_partition');
    expect(categoryOfLayer('07_с112')).toBe('frame_partition');
  });

  it('слои без соответствия - null', () => {
    for (const name of ['04_ОСИ', '05_РАЗМЕРЫ', '0', '', '07_C113', 'МОНОЛИТ', 'x01_КЛАДКА']) {
      expect(categoryOfLayer(name)).toBeNull();
    }
  });
});

describe('категория конструкции по виду', () => {
  it('сопоставляет виды', () => {
    expect(categoryOfKind('masonry')).toBe('masonry');
    expect(categoryOfKind('monolith_wall')).toBe('monolith');
    expect(categoryOfKind('monolith_pylon')).toBe('monolith');
    expect(categoryOfKind('monolith_column')).toBe('monolith');
    expect(categoryOfKind('frame_partition')).toBe('frame_partition');
    expect(categoryOfKind('floor_slab')).toBe('slab');
  });
});

describe('скрытые категории', () => {
  const names = ['01_КЛАДКА', '01_КЛАДКА_2', '02_МОНОЛИТ', '04_ОСИ'];

  it('категория скрыта, когда скрыты все её слои', () => {
    expect(hiddenCategoriesOf(names, new Set(['01_КЛАДКА']), new Set()).size).toBe(0);
    const both = hiddenCategoriesOf(names, new Set(['01_КЛАДКА', '01_КЛАДКА_2']), new Set());
    expect([...both]).toEqual(['masonry']);
  });

  it('слой без соответствия категорию не скрывает; плита и перемычки - как есть', () => {
    const hidden = hiddenCategoriesOf(names, new Set(['04_ОСИ']), new Set(['slab', 'lintel']));
    expect([...hidden].sort()).toEqual(['lintel', 'slab']);
  });

  it('скрытое имя, которого нет в листе, ничего не скрывает', () => {
    expect(hiddenCategoriesOf(names, new Set(['03_ДВЕРИ']), new Set()).size).toBe(0);
  });
});

describe('фильтр фигур по скрытым категориям', () => {
  const shapes = [
    { id: 'a', kind: 'masonry' as const },
    { id: 'b', kind: 'monolith_wall' as const },
    { id: 'slab', kind: 'floor_slab' as const },
  ];

  it('убирает скрытые; нет скрытых - тот же массив', () => {
    expect(withoutHiddenCategories(shapes, new Set(['monolith', 'slab'])).map((s) => s.id)).toEqual(['a']);
    expect(withoutHiddenCategories(shapes, new Set())).toBe(shapes);
    expect(withoutHiddenCategories(shapes, undefined)).toBe(shapes);
  });
});

describe('скрытие конструкций слоями-источниками', () => {
  const hidden = new Set(['01_КЛАДКА_200']);

  it('isHiddenByLayers: пустой список, часть скрыта, все скрыты', () => {
    expect(isHiddenByLayers([], hidden)).toBe(false);
    expect(isHiddenByLayers(['01_КЛАДКА_200', '01_КЛАДКА_80'], hidden)).toBe(false);
    expect(isHiddenByLayers(['01_КЛАДКА_200'], hidden)).toBe(true);
    expect(isHiddenByLayers(['01_КЛАДКА_200'], new Set())).toBe(false);
  });

  it('набор скрытых id: слой 200 скрыт, 80 виден - скрыты только конструкции слоя 200', () => {
    const items = [
      { id: 'a', kind: 'masonry' as const, source_layers: ['01_КЛАДКА_200'] },
      { id: 'b', kind: 'masonry' as const, source_layers: ['01_КЛАДКА_80'] },
      { id: 'c', kind: 'masonry' as const, source_layers: [] },
    ];
    expect([...hiddenConstructionIdsOf(items, new Set(), hidden)]).toEqual(['a']);
    // Скрытая категория скрывает и конструкции без слоёв.
    expect([...hiddenConstructionIdsOf(items, new Set(['masonry']), hidden)].sort()).toEqual(['a', 'b', 'c']);
  });

  it('withoutHiddenCategories учитывает слои фигуры', () => {
    const shapes = [
      { kind: 'masonry' as const, layers: ['01_КЛАДКА_200'] },
      { kind: 'masonry' as const, layers: ['01_КЛАДКА_80'] },
    ];
    expect(withoutHiddenCategories(shapes, undefined, hidden)).toEqual([shapes[1]]);
  });

  it('ключ подгруппы не зависит от порядка и дублей слоёв', () => {
    expect(layerGroupKeyOf(['b', 'a', 'a'])).toBe(layerGroupKeyOf(['a', 'b']));
    expect(layerGroupKeyOf([])).toBeUndefined();
  });
});

describe('плита скрывается своей строкой «Плита»', () => {
  const items = [
    { id: 'slab', kind: 'floor_slab' as const, source_layers: [] },
    { id: 'a', kind: 'masonry' as const, source_layers: ['01_КЛАДКА'] },
  ];

  it('строка «Плита» -> категория slab (3D: плита и отверстия) без слоёв DXF', () => {
    const hidden = hiddenCategoriesOf(['01_КЛАДКА'], new Set(), new Set(['slab']));
    expect([...hidden]).toEqual(['slab']);
  });

  it('скрытые конструкции: плита по категории, кладка остаётся', () => {
    const hidden = hiddenCategoriesOf([], new Set(), new Set(['slab']));
    expect([...hiddenConstructionIdsOf(items, hidden, new Set())]).toEqual(['slab']);
  });

  it('2D-фигуры: floor_slab пропадает при скрытой плите, без неё остаётся', () => {
    const shapes = [
      { id: 'slab', kind: 'floor_slab' as const },
      { id: 'a', kind: 'masonry' as const },
    ];
    const hidden = hiddenCategoriesOf([], new Set(), new Set(['slab']));
    expect(withoutHiddenCategories(shapes, hidden).map((s) => s.id)).toEqual(['a']);
    expect(withoutHiddenCategories(shapes, hiddenCategoriesOf([], new Set(), new Set())).length).toBe(2);
  });

  it('скрытая строка «Перемычки» плиту не трогает', () => {
    const hidden = hiddenCategoriesOf([], new Set(), new Set(['lintel']));
    expect(hiddenConstructionIdsOf(items, hidden, new Set()).size).toBe(0);
  });
});
