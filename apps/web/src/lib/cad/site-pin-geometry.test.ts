import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  buildSitePinBody,
  buildSitePlan,
  fitPlanView,
  isComplete,
  mmToScreen,
  nextSlot,
  panPlanView,
  pinHint,
  screenToMm,
  snapToVertex2d,
  toViewFrame,
  withPoint,
  zoomPlanView,
  type IPlanView,
  type PinPoints,
} from './site-pin-geometry';

const floor = (patch: Partial<CadBuilding3dFloorRead> = {}): CadBuilding3dFloorRead =>
  ({
    revision_id: 'r1',
    page_index: 3,
    view: 1,
    rotation_deg: 0,
    offset_mm: [0, 0],
    outline: [[0, 0], [10000, 0], [10000, 6000], [0, 6000]],
    walls: [],
    ...patch,
  }) as CadBuilding3dFloorRead;

const VIEW: IPlanView = { scale: 0.1, originX: 50, originY: 400 };

describe('перевод координат сборки в кадр вида', () => {
  it('обратный к R(rotation_deg) · p + offset_mm: поворот 90 градусов и сдвиг', () => {
    // p = (10, 0) -> R90 = (0, 10) -> + (1000, 2000)
    expect(toViewFrame([1000, 2010], { rotation_deg: 90, offset_mm: [1000, 2000] })).toEqual([10, 0]);
    expect(toViewFrame([-3, 7], { rotation_deg: 180, offset_mm: [0, 0] })).toEqual([3, -7]);
    expect(toViewFrame([5, 6], { rotation_deg: 0, offset_mm: [1, 2] })).toEqual([4, 4]);
  });

  it('не кратный 90 поворот возвращает точку с точностью до микрона', () => {
    const radians = (30 * Math.PI) / 180;
    const aligned: [number, number] = [
      100 * Math.cos(radians) - 50 * Math.sin(radians) + 7,
      100 * Math.sin(radians) + 50 * Math.cos(radians) - 3,
    ];
    const [x, y] = toViewFrame(aligned, { rotation_deg: 30, offset_mm: [7, -3] });
    expect(x).toBeCloseTo(100, 2);
    expect(y).toBeCloseTo(50, 2);
  });
});

describe('план этажа', () => {
  it('контур и стены без плит перекрытия, вершины без повторов, всё в кадре вида', () => {
    const plan = buildSitePlan(
      floor({
        rotation_deg: 0,
        offset_mm: [100, 0],
        outline: [[100, 0], [1100, 0], [1100, 500], [100, 500]],
        walls: [
          { id: 'w', kind: 'masonry', shell: [[100, 0], [200, 0], [200, 50], [100, 50]] },
          { id: 's', kind: 'floor_slab', shell: [[0, 0], [9, 0], [9, 9]] },
        ],
      }),
    );
    expect(plan?.rings).toHaveLength(2);
    expect(plan?.vertices).toContainEqual([0, 0]);
    expect(plan?.vertices).toHaveLength(7);
    expect(plan?.bounds).toEqual({ minX: 0, minY: 0, maxX: 1000, maxY: 500 });
  });

  it('нет ни контура, ни стен - плана нет', () => {
    expect(buildSitePlan(floor({ outline: [], walls: null }))).toBeNull();
  });
});

describe('экран и мм', () => {
  it('туда и обратно, Y вверх', () => {
    const screen = mmToScreen([1000, 2000], VIEW);
    expect(screen).toEqual({ x: 150, y: 200 });
    expect(screenToMm(screen, VIEW)).toEqual([1000, 2000]);
  });

  it('зум держит точку под курсором на месте, сдвиг переносит начало', () => {
    const anchor = { x: 150, y: 200 };
    const zoomed = zoomPlanView(VIEW, anchor, 2);
    expect(zoomed.scale).toBeCloseTo(0.2);
    expect(screenToMm(anchor, zoomed)[0]).toBeCloseTo(1000);
    expect(screenToMm(anchor, zoomed)[1]).toBeCloseTo(2000);
    expect(panPlanView(VIEW, 10, -5)).toMatchObject({ originX: 60, originY: 395, scale: 0.1 });
  });

  it('«Вписать» кладёт габарит в холст по центру', () => {
    const view = fitPlanView({ minX: 0, minY: 0, maxX: 10000, maxY: 5000 }, 400, 300, 0);
    expect(view.scale).toBeCloseTo(0.04);
    const centre = mmToScreen([5000, 2500], view);
    expect(centre.x).toBeCloseTo(200);
    expect(centre.y).toBeCloseTo(150);
  });
});

describe('привязка к вершине в 2D', () => {
  const vertices = [
    [0, 0],
    [1000, 2000],
  ] as const;

  it('в допуске - вершина', () => {
    // вершина (1000, 2000) на экране в (150, 200); щелчок в 5 px от неё
    expect(snapToVertex2d({ x: 153, y: 204 }, vertices, VIEW)).toEqual({ point: [1000, 2000], snapped: true });
  });

  it('вне допуска - точка щелчка без привязки', () => {
    const result = snapToVertex2d({ x: 300, y: 100 }, vertices, VIEW);
    expect(result.snapped).toBe(false);
    expect(result.point).toEqual(screenToMm({ x: 300, y: 100 }, VIEW));
  });

  it('допуск экранный: при зуме вершина «ближе» в мм не становится', () => {
    const zoomed: IPlanView = { scale: 1, originX: 0, originY: 0 };
    expect(snapToVertex2d({ x: 1005, y: -2000 }, vertices, zoomed).snapped).toBe(true);
    expect(snapToVertex2d({ x: 1100, y: -2000 }, vertices, zoomed).snapped).toBe(false);
  });
});

describe('точки и подсказка', () => {
  const none: PinPoints = [null, null];

  it('следующая точка: назначенная, иначе первая пустая, иначе никакая', () => {
    expect(nextSlot(none, null)).toBe(0);
    expect(nextSlot([[1, 1], null], null)).toBe(1);
    expect(nextSlot([[1, 1], [2, 2]], null)).toBeNull();
    expect(nextSlot([[1, 1], [2, 2]], 0)).toBe(0);
    expect(withPoint([[1, 1], [2, 2]], 0, [9, 9])).toEqual([[9, 9], [2, 2]]);
    expect(isComplete([[1, 1], null])).toBe(false);
  });

  it('длины отрезков и расхождение; короткая база и расхождение больше 1 %', () => {
    const ok = pinHint([[0, 0], [10000, 0]], [[0, 0], [0, 10050]]);
    expect(ok.sourceMm).toBe(10000);
    expect(ok.targetMm).toBe(10050);
    expect(ok.mismatch).toBeCloseTo(0.005);
    expect(ok.shortBaseline).toBe(false);
    expect(ok.mismatchTooBig).toBe(false);

    const bad = pinHint([[0, 0], [4000, 0]], [[0, 0], [0, 4100]]);
    expect(bad.shortBaseline).toBe(true);
    expect(bad.mismatchTooBig).toBe(true);
  });
});

describe('тело запроса', () => {
  const src = floor({ revision_id: 'r-src', page_index: 1, view: 0 });
  const dst = floor({ revision_id: 'r-dst', page_index: 7, view: 2 });
  const a: PinPoints = [[0, 0], [10000, 0]];
  const b: PinPoints = [[5, 6], [5, 10006]];

  it('листы и по две точки, примечание обрезается', () => {
    expect(buildSitePinBody(src, dst, a, b, '  ')).toEqual({
      source: { revision_id: 'r-src', page_index: 1, view: 0 },
      target: { revision_id: 'r-dst', page_index: 7, view: 2 },
      source_points: [{ x_mm: 0, y_mm: 0 }, { x_mm: 10000, y_mm: 0 }],
      target_points: [{ x_mm: 5, y_mm: 6 }, { x_mm: 5, y_mm: 10006 }],
    });
    expect(buildSitePinBody(src, dst, a, b, ' по оси А ')).toMatchObject({ note: 'по оси А' });
  });

  it('не хватает точки - тела нет', () => {
    expect(buildSitePinBody(src, dst, [[0, 0], null], b, '')).toBeNull();
    expect(buildSitePinBody(src, dst, a, [null, null], '')).toBeNull();
  });
});
