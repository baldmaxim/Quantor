import { describe, expect, it } from 'vitest';

import { buildConstructionIndex, buildShapes, type IConstructionShape } from './constructions';
import { construction } from './constructions-fixtures';
import { createConstructionsPainter, type IConstructionPaintData } from './constructions-painter';
import { withoutHiddenCategories } from './layer-categories';

const COLORS = { masonry: 'brown', monolith: 'indigo', slab: 'teal', check: 'amber', accent: 'blue', notInVor: 'red' };
const FRAME = { originX: 100, originY: 500, mmPerPt: 10 };
const PAGE = { width: 1000, height: 1000 };
const PLACEMENT = { x: 0, y: 0, width: 1000, height: 1000, rotation: 0 as const };

const shapes = buildShapes(
  [construction({ id: 'm' }), construction({ id: 'c', kind: 'monolith_wall' }), construction({ id: 'f', kind: 'frame_partition' })],
  FRAME,
  PAGE,
);

const fillColors = (
  hidden: IConstructionPaintData['hiddenCategories'],
  hiddenLayerNames?: ReadonlySet<string>,
  paintShapes: readonly IConstructionShape[] = shapes,
): string[] => {
  const fills: string[] = [];
  let fill = '';
  const context = new Proxy(
    { canvas: { width: 1000, height: 1000 } },
    {
      get: (target, key) => {
        if (key in target) return Reflect.get(target, key);
        return () => {
          if (key === 'fill') fills.push(fill);
        };
      },
      set: (_target, key, value) => {
        if (key === 'fillStyle') fill = value;
        return true;
      },
    },
  ) as unknown as CanvasRenderingContext2D;
  createConstructionsPainter(
    {
      shapes: paintShapes,
      colors: COLORS,
      selected: new Set<string>(),
      showAll: true,
      hiddenCategories: hidden,
      hiddenLayerNames,
    },
    { clear: true },
  ).paint(context, PLACEMENT, 1, null);
  return fills;
};

describe('рисовальщик: скрытые категории', () => {
  it('без скрытых рисуются все', () => {
    expect(fillColors(undefined)).toHaveLength(3);
  });

  it('скрытая категория не рисуется', () => {
    expect(fillColors(new Set(['monolith']))).toEqual(['brown', 'brown']);
    expect(fillColors(new Set(['masonry', 'frame_partition']))).toEqual(['indigo']);
    expect(fillColors(new Set(['masonry', 'frame_partition', 'monolith']))).toEqual([]);
  });

  it('конструкция, все слои-источники которой скрыты, не рисуется', () => {
    const layered = buildShapes(
      [
        construction({ id: 'a', source_layers: ['01_КЛАДКА_200'] }),
        construction({ id: 'b', kind: 'monolith_wall', source_layers: ['01_КЛАДКА_80'] }),
        construction({ id: 'c', source_layers: ['01_КЛАДКА_200', '01_КЛАДКА_80'] }),
      ],
      FRAME,
      PAGE,
    );
    expect(fillColors(undefined, new Set(['01_КЛАДКА_200']), layered)).toEqual(['indigo', 'brown']);
    expect(fillColors(undefined, new Set(['01_КЛАДКА_200', '01_КЛАДКА_80']), layered)).toEqual([]);
    expect(fillColors(undefined, new Set(), layered)).toHaveLength(3);
  });

  it('touches не строже paint: всё скрыто - слой пуст', () => {
    const all = new Set(['masonry', 'monolith', 'frame_partition'] as const);
    const painter = createConstructionsPainter(
      { shapes, colors: COLORS, selected: new Set<string>(), showAll: true, hiddenCategories: all },
      { clear: true },
    );
    expect(painter.touches(PLACEMENT, 1, [{ x: 0, y: 0, width: 1000, height: 1000 }])).toBe(false);
  });
});

describe('хит-тест: скрытое не выбирается кликом', () => {
  it('индекс без скрытой категории не отдаёт её конструкцию', () => {
    const target = shapes[0]!;
    const centre = {
      x: (target.bounds.minX + target.bounds.maxX) / 2,
      y: (target.bounds.minY + target.bounds.maxY) / 2,
    };
    expect(buildConstructionIndex(shapes).hit(centre, 0.01)).not.toBeNull();
    const visible = withoutHiddenCategories(shapes, new Set(['masonry', 'monolith', 'frame_partition']));
    expect(buildConstructionIndex(visible).hit(centre, 0.01)).toBeNull();
  });
});
