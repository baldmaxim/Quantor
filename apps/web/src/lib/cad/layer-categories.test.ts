import { describe, expect, it } from 'vitest';

import {
  categoryOfKind,
  categoryOfLayer,
  hiddenCategoriesOf,
  hiddenConstructionIdsOf,
  isHiddenByLayers,
  isMonolithLayer,
  isServiceLayer,
  layerGroupKeyOf,
  layerGroupKeys,
  monolithPaintedByShapes,
  paintHiddenLayerIndices,
  withoutHiddenCategories,
} from './layer-categories';

describe('категория слоя по префиксу имени', () => {
  it('кладка, монолит, двери - по префиксу, регистр не важен', () => {
    expect(categoryOfLayer('01_КЛАДКА')).toBe('masonry');
    expect(categoryOfLayer('01_кладка_наружная')).toBe('masonry');
    expect(categoryOfLayer('03_ДВЕРИ')).toBe('door');
    expect(categoryOfLayer('03_двери_1')).toBe('door');
  });

  it('C112 - и латинская C, и кириллическая С', () => {
    expect(categoryOfLayer('07_C112')).toBe('frame_partition');
    expect(categoryOfLayer('07_С112')).toBe('frame_partition');
    expect(categoryOfLayer('07_c112_гкл')).toBe('frame_partition');
    expect(categoryOfLayer('07_с112')).toBe('frame_partition');
  });

  it('02_МОНОЛИТ - не категория слоя: им управляют две монолитные строки', () => {
    expect(categoryOfLayer('02_МОНОЛИТ')).toBeNull();
    expect(isMonolithLayer('02_МОНОЛИТ')).toBe(true);
    expect(isMonolithLayer('02_Монолит_стены')).toBe(true);
    expect(isMonolithLayer('01_КЛАДКА')).toBe(false);
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
    expect(categoryOfKind('monolith_wall')).toBe('monolith_vertical');
    expect(categoryOfKind('monolith_pylon')).toBe('monolith_vertical');
    expect(categoryOfKind('monolith_column')).toBe('monolith_column');
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

  it('слой без соответствия категорию не скрывает; плита - как есть', () => {
    const hidden = hiddenCategoriesOf(names, new Set(['04_ОСИ']), new Set(['slab']));
    expect([...hidden]).toEqual(['slab']);
  });

  it('монолитные строки - как есть, слой 02_МОНОЛИТ категорию не скрывает', () => {
    expect(hiddenCategoriesOf(names, new Set(['02_МОНОЛИТ']), new Set()).size).toBe(0);
    const hidden = hiddenCategoriesOf(names, new Set(), new Set(['monolith_column']));
    expect([...hidden]).toEqual(['monolith_column']);
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
    expect(withoutHiddenCategories(shapes, new Set(['monolith_vertical', 'slab'])).map((s) => s.id)).toEqual(['a']);
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

  it('скрытая строка монолита плиту не трогает', () => {
    const hidden = hiddenCategoriesOf([], new Set(), new Set(['monolith_column']));
    expect(hiddenConstructionIdsOf(items, hidden, new Set()).size).toBe(0);
  });
});

describe('служебные слои', () => {
  it('AUX_ и QA_ - служебные без учёта регистра, остальные нет', () => {
    for (const name of ['AUX_КЛАДКА_ШТРИХОВКА', 'aux_контуры_стен', 'QA_МАРКЕРЫ_НЕ_УЧИТЫВАТЬ', 'qa_x']) {
      expect(isServiceLayer(name)).toBe(true);
    }
    for (const name of ['01_КЛАДКА', '02_МОНОЛИТ', 'AUXILIARY', 'QAX', 'MY_AUX_X', '']) {
      expect(isServiceLayer(name)).toBe(false);
    }
  });
});

describe('монолит: две строки и слой 02_МОНОЛИТ', () => {
  const items = [
    { id: 'w', kind: 'monolith_wall' as const, source_layers: ['02_МОНОЛИТ'] },
    { id: 'p', kind: 'monolith_pylon' as const, source_layers: ['02_МОНОЛИТ'] },
    { id: 'c', kind: 'monolith_column' as const, source_layers: ['02_МОНОЛИТ'] },
    { id: 'm', kind: 'masonry' as const, source_layers: ['01_КЛАДКА'] },
  ];

  it('скрытая строка скрывает только свои конструкции (план и 3D)', () => {
    const columnsOff = hiddenCategoriesOf([], new Set(), new Set(['monolith_column']));
    expect([...hiddenConstructionIdsOf(items, columnsOff, new Set())]).toEqual(['c']);
    const verticalOff = hiddenCategoriesOf([], new Set(), new Set(['monolith_vertical']));
    expect([...hiddenConstructionIdsOf(items, verticalOff, new Set())].sort()).toEqual(['p', 'w']);
    expect(withoutHiddenCategories(items, columnsOff).map((s) => s.id)).toEqual(['w', 'p', 'm']);
  });

  it('рисуется рисовальщиком конструкций, когда включена ровно одна строка', () => {
    expect(monolithPaintedByShapes(undefined).size).toBe(0);
    expect(monolithPaintedByShapes(new Set()).size).toBe(0);
    expect([...monolithPaintedByShapes(new Set(['monolith_column']))]).toEqual(['monolith_vertical']);
    expect([...monolithPaintedByShapes(new Set(['monolith_vertical']))]).toEqual(['monolith_column']);
    expect(monolithPaintedByShapes(new Set(['monolith_vertical', 'monolith_column'])).size).toBe(0);
  });

  it('слой 02_МОНОЛИТ в плане: рисуется только при обеих включённых строках; служебные - никогда', () => {
    const names = ['01_КЛАДКА_100', '02_МОНОЛИТ', 'AUX_КЛАДКА_ШТРИХОВКА', 'QA_X', '03_ДВЕРИ_БЛОКИ'];
    expect([...paintHiddenLayerIndices(names, new Set(), new Set())]).toEqual([2, 3]);
    expect([...paintHiddenLayerIndices(names, new Set(), new Set(['monolith_column'])).values()].sort()).toEqual([1, 2, 3]);
    expect([...paintHiddenLayerIndices(names, new Set([0]), new Set(['monolith_vertical'])).values()].sort()).toEqual([0, 1, 2, 3]);
  });

  it('подгруппы 3D: стены/пилоны и колонны одного слоя - разные ключи', () => {
    const keys = layerGroupKeys(items);
    expect(keys.keyOf('w')).toBe(keys.keyOf('p'));
    expect(keys.keyOf('w')).not.toBe(keys.keyOf('c'));
    expect(keys.keyOf('m')).toBe(layerGroupKeyOf(['01_КЛАДКА']));
    const bare = layerGroupKeys([{ id: 'c2', kind: 'monolith_column' as const, source_layers: [] }]);
    expect(bare.keyOf('c2')).toBeDefined();
    expect(keys.categoryOf('w')).toBe('monolith_vertical');
    expect(keys.categoryOf('c')).toBe('monolith_column');
    expect(keys.categoryOf('нет')).toBeUndefined();
  });
});
