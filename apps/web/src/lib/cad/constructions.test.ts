import { describe, expect, it } from 'vitest';

import {
  CLICK_SLOP_PX,
  buildConstructionIndex,
  buildShapes,
  groupIds,
  isClick,
  placePopover,
  pointInRing,
  pointInRings,
  sameGroupIds,
  shapeOf,
  statusIds,
  sumGroups,
} from './constructions';
import { construction, opening } from './constructions-fixtures';
import { doorsOf } from './constructions';
import type { ICadFrame } from './frame';

// pt = (100 + x / 10, 500 - y / 10); лист 1000 x 1000 pt.
const FRAME: ICadFrame = { originX: 100, originY: 500, mmPerPt: 10 };
const PAGE = { width: 1000, height: 1000 };

describe('полигон в нормализованных координатах листа', () => {
  it('те же кадр и формула, что у CAD-путей: ось Y переворачивается, деление на размер листа', () => {
    const shape = shapeOf(construction({ id: 'a' }), FRAME, PAGE);
    expect(shape?.rings[0]?.[0]).toEqual({ x: 0.1, y: 0.5 });
    expect(shape?.rings[0]?.[2]).toEqual({ x: 0.6, y: 0.488 });
    expect(shape?.bounds).toEqual({ minX: 0.1, minY: 0.488, maxX: 0.6, maxY: 0.5 });
  });

  it('отверстия сохраняются, вырожденное кольцо отбрасывается', () => {
    const shape = shapeOf(
      construction({
        id: 'h',
        polygon: {
          shell: [
            [0, 0],
            [1000, 0],
            [1000, 1000],
            [0, 1000],
          ],
          holes: [
            [
              [200, 200],
              [400, 200],
              [400, 400],
            ],
            [
              [0, 0],
              [1, 1],
            ],
          ],
        },
      }),
      FRAME,
      PAGE,
    );
    expect(shape?.rings).toHaveLength(2);
    expect(shapeOf(construction({ id: 'bad', polygon: { shell: [[0, 0]], holes: [] } }), FRAME, PAGE)).toBeNull();
  });

  it('buildShapes пропускает конструкции без контура', () => {
    const shapes = buildShapes(
      [construction({ id: 'a' }), construction({ id: 'bad', polygon: { shell: [], holes: [] } })],
      FRAME,
      PAGE,
    );
    expect(shapes.map((shape) => shape.id)).toEqual(['a']);
  });
});

describe('точка в полигоне', () => {
  const square = [
    { x: 0, y: 0 },
    { x: 1, y: 0 },
    { x: 1, y: 1 },
    { x: 0, y: 1 },
  ];
  const hole = [
    { x: 0.4, y: 0.4 },
    { x: 0.6, y: 0.4 },
    { x: 0.6, y: 0.6 },
    { x: 0.4, y: 0.6 },
  ];

  it('внутри и снаружи кольца', () => {
    expect(pointInRing({ x: 0.2, y: 0.2 }, square)).toBe(true);
    expect(pointInRing({ x: 1.2, y: 0.2 }, square)).toBe(false);
  });

  it('точка в отверстии не попадает в фигуру', () => {
    expect(pointInRings({ x: 0.5, y: 0.5 }, [square, hole])).toBe(false);
    expect(pointInRings({ x: 0.2, y: 0.5 }, [square, hole])).toBe(true);
  });
});

describe('индекс попаданий', () => {
  const wall = construction({ id: 'wall' });
  // Вложенная колонна внутри охвата стены-рамки: побеждает меньший охват.
  const frame = construction({
    id: 'frame',
    polygon: {
      shell: [
        [0, 0],
        [5000, 0],
        [5000, 3000],
        [0, 3000],
      ],
      holes: [],
    },
  });
  const column = construction({
    id: 'column',
    kind: 'monolith_column',
    polygon: {
      shell: [
        [1000, 1000],
        [1400, 1000],
        [1400, 1400],
        [1000, 1400],
      ],
      holes: [],
    },
  });

  it('клик внутри контура находит конструкцию, мимо - пусто', () => {
    const index = buildConstructionIndex(buildShapes([wall], FRAME, PAGE));
    expect(index.hit({ x: 0.3, y: 0.494 }, 0)).toBe('wall');
    expect(index.hit({ x: 0.9, y: 0.9 }, 0)).toBeNull();
  });

  it('точка в отверстии - мимо', () => {
    const holed = construction({
      id: 'holed',
      polygon: {
        shell: [
          [0, 0],
          [1000, 0],
          [1000, 1000],
          [0, 1000],
        ],
        holes: [
          [
            [400, 400],
            [600, 400],
            [600, 600],
            [400, 600],
          ],
        ],
      },
    });
    const index = buildConstructionIndex(buildShapes([holed], FRAME, PAGE));
    // Центр отверстия: x = 0.1 + 500/10/1000, y = 0.5 - 500/10/1000.
    expect(index.hit({ x: 0.15, y: 0.45 }, 0)).toBeNull();
    expect(index.hit({ x: 0.12, y: 0.45 }, 0)).toBe('holed');
  });

  it('из вложенных побеждает фигура с меньшим охватом', () => {
    const index = buildConstructionIndex(buildShapes([frame, column], FRAME, PAGE));
    // Центр колонны в нормализованных: x = 0.1 + 120/1000, y = 0.5 - 120/1000.
    expect(index.hit({ x: 0.22, y: 0.38 }, 0)).toBe('column');
  });

  it('тонкую стену можно взять с допуском; без допуска - мимо', () => {
    const index = buildConstructionIndex(buildShapes([wall], FRAME, PAGE));
    const justAbove = { x: 0.3, y: 0.4865 };
    expect(index.hit(justAbove, 0)).toBeNull();
    expect(index.hit(justAbove, 0.002)).toBe('wall');
    expect(index.hit({ x: 0.3, y: 0.4 }, 0.002)).toBeNull();
  });

  describe('плита перекрытия', () => {
    // Плита 6000 x 4000 мм с отверстием 1000 x 1000 мм: x 0.1..0.7, y 0.1..0.5; центр отверстия (0.4, 0.2).
    const slab = construction({
      id: 'slab',
      kind: 'floor_slab',
      polygon: {
        shell: [
          [0, 0],
          [6000, 0],
          [6000, 4000],
          [0, 4000],
        ],
        holes: [
          [
            [2500, 2500],
            [3500, 2500],
            [3500, 3500],
            [2500, 3500],
          ],
        ],
      },
    });

    it('точка в стене - стена, в плите вне стен - плита, в отверстии - ничего', () => {
      const index = buildConstructionIndex(buildShapes([slab, wall], FRAME, PAGE));
      expect(index.hit({ x: 0.3, y: 0.494 }, 0)).toBe('wall');
      expect(index.hit({ x: 0.65, y: 0.3 }, 0)).toBe('slab');
      expect(index.hit({ x: 0.4, y: 0.2 }, 0)).toBeNull();
      expect(index.hit({ x: 0.9, y: 0.9 }, 0)).toBeNull();
    });

    it('стена рядом с точкой (допуск) побеждает плиту под ней', () => {
      const index = buildConstructionIndex(buildShapes([slab, wall], FRAME, PAGE));
      expect(index.hit({ x: 0.3, y: 0.4865 }, 0.002)).toBe('wall');
      expect(index.hit({ x: 0.3, y: 0.4865 }, 0)).toBe('slab');
    });

    it('близость к краю плиты вне её контура - не попадание', () => {
      const index = buildConstructionIndex(buildShapes([slab], FRAME, PAGE));
      expect(index.hit({ x: 0.701, y: 0.2 }, 0.002)).toBeNull();
    });
  });

  it('search отдаёт конструкции по охвату', () => {
    const index = buildConstructionIndex(buildShapes([wall, column], FRAME, PAGE));
    expect(index.size).toBe(2);
    expect(index.search({ minX: 0.9, minY: 0.9, maxX: 1, maxY: 1 })).toEqual([]);
  });
});

describe('щелчок или перетаскивание', () => {
  it('меньше 4 px - щелчок, 4 и больше - панорама', () => {
    expect(isClick({ x: 10, y: 10 }, { x: 12, y: 11 })).toBe(true);
    expect(isClick({ x: 10, y: 10 }, { x: 10 + CLICK_SLOP_PX, y: 10 })).toBe(false);
    expect(isClick({ x: 10, y: 10 }, { x: 30, y: 10 })).toBe(false);
  });
});

describe('положение карточки у курсора', () => {
  const size = { width: 340, height: 400 };
  const viewport = { width: 1280, height: 800 };

  it('правее и ниже клика на 12 px', () => {
    expect(placePopover({ x: 100, y: 100 }, size, viewport)).toEqual({ left: 112, top: 112 });
  });

  it('у правого края переворачивается влево от клика', () => {
    const at = placePopover({ x: 1200, y: 100 }, size, viewport);
    expect(at.left).toBe(1200 - 12 - 340);
  });

  it('у нижнего края переворачивается вверх', () => {
    const at = placePopover({ x: 100, y: 700 }, size, viewport);
    expect(at.top).toBe(700 - 12 - 400);
  });

  it('не выходит за окно, если не помещается ни так, ни так', () => {
    const at = placePopover({ x: 100, y: 100 }, { width: 340, height: 2000 }, viewport);
    expect(at.top).toBeGreaterThanOrEqual(0);
    const narrow = placePopover({ x: 50, y: 50 }, { width: 340, height: 100 }, { width: 300, height: 800 });
    expect(narrow.left).toBeGreaterThanOrEqual(0);
  });
});

describe('группы, двери и свод', () => {
  const a = construction({ id: 'a' });
  const b = construction({ id: 'b', props: { material: 'aerated_concrete' } });
  const c = construction({ id: 'c', thickness_nominal_mm: 200, computed: { ...a.computed, thickness_mm: 200 } });
  const d = construction({
    id: 'd',
    kind: 'monolith_wall',
    thickness_nominal_mm: 120,
    computed: { ...a.computed, thickness_mm: 120 },
  });
  const check = construction({
    id: 'e',
    thickness_nominal_mm: null,
    computed: { ...a.computed, status: 'thickness_check', thickness_mm: null },
  });
  const all = [a, b, c, d, check];

  it('«ко всем» - тот же вид и тот же номинал', () => {
    expect(sameGroupIds(all, a)).toEqual(['a', 'b']);
    expect(sameGroupIds(all, d)).toEqual(['d']);
    expect(sameGroupIds(all, check)).toEqual(['e']);
  });

  it('строка свода подсвечивает конструкции вида, толщины и материала', () => {
    expect(groupIds(all, { kind: 'masonry', thickness_mm: 120, material: null })).toEqual(['a']);
    expect(groupIds(all, { kind: 'masonry', thickness_mm: 120, material: 'aerated_concrete' })).toEqual([
      'b',
    ]);
  });

  it('statusIds и двери конструкции', () => {
    expect(statusIds(all, 'thickness_check')).toEqual(['e']);
    const doors = [
      opening({ id: 'o1', host_id: 'a' }),
      opening({ id: 'o2', host_id: 'a', kind: 'gap' }),
      opening({ id: 'o3', host_id: 'b' }),
    ];
    expect(doorsOf(doors, a).map((item) => item.id)).toEqual(['o1']);
  });

  it('итог по кладке и монолиту считается отдельно', () => {
    const totals = [
      { kind: 'masonry', thickness_mm: 120, material: null, count: 2, length_m: 3, wall_area_m2: 8, volume_m3: 1 },
      { kind: 'masonry', thickness_mm: 200, material: null, count: 1, length_m: 2, wall_area_m2: 5, volume_m3: 1.2 },
      { kind: 'monolith_wall', thickness_mm: 200, material: null, count: 4, length_m: 9, wall_area_m2: 20, volume_m3: 4 },
    ] as const;
    expect(sumGroups(totals, (group) => group.kind === 'masonry')).toEqual({
      count: 3,
      length_m: 5,
      wall_area_m2: 13,
      volume_m3: 2.2,
    });
    expect(sumGroups(totals, (group) => group.kind === 'monolith_column')).toBeNull();
  });
});
