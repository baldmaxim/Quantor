import type { CadFloor3dRead } from '@quantor/api-client';

/**
 * План 3D-вида этажа (ADR-0039): чистые функции без DOM и без three.js.
 *
 * Сервер отдаёт призмы в мм системы DXF (ось Y вверх). Здесь они переводятся в метры, центрируются
 * по габариту модели и раскладываются по категориям. Вид только показывает: величин не считает.
 *
 * Ориентация. Контур призмы хранится как `(u, v) = (x, y)` DXF в метрах относительно центра.
 * Сцена three: `X = u`, `Y` = высота, `Z = -v` (поворот контура на -90° вокруг X, определитель +1).
 * Вид сверху с `Z` вниз по экрану показывает план как на чертеже, без зеркала.
 */

export const MM_IN_M = 1000;

export type Point2 = readonly [number, number];

export type PrismCategory = 'slab' | 'masonry' | 'monolith' | 'lintel';

/** Призма: контур с отверстиями в плане (м, от центра) и высоты низа/верха (м, от центра по высоте). */
export interface IPrismSpec {
  readonly id: string;
  readonly category: PrismCategory;
  readonly shell: readonly Point2[];
  readonly holes: readonly (readonly Point2[])[];
  readonly yBottom: number;
  readonly yTop: number;
}

/** Отверстие плиты для показа: контур на верхе плиты. */
export interface IHoleSpec {
  readonly key: string;
  readonly state: 'candidate' | 'enabled' | 'disabled';
  readonly contour: readonly Point2[];
  /** Высота (м), на которой лежит контур: верх плиты. */
  readonly y: number;
  readonly areaM2: number;
}

export interface IFloor3dCenter {
  /** Центр габарита в плане и по высоте, мм. */
  readonly x: number;
  readonly y: number;
  readonly z: number;
}

export interface IFloor3dPlan {
  readonly center: IFloor3dCenter;
  /** Плита, стены и перемычки. */
  readonly prisms: readonly IPrismSpec[];
  /** Отверстия `candidate` и `enabled`: плита по ним вырезана. */
  readonly holes: readonly IHoleSpec[];
  /** Отверстия `disabled` («Не отверстие»): плита сплошная, на сцене - только контур. */
  readonly disabledHoles: readonly IHoleSpec[];
  /** Полупрозрачная копия плиты на верхе стен; `null` - строить не из чего. */
  readonly slabCap: IPrismSpec | null;
  readonly skipped: {
    /** Стен без верхней отметки: не построены. */
    readonly wallsWithoutTop: number;
    /** Плита есть, а низа нет (нет толщины): не построена. */
    readonly slabWithoutBottom: boolean;
    /** Контуров из менее чем трёх точек. */
    readonly degenerate: number;
  };
  /** Габарит модели в метрах: ширина (X), высота (Y), глубина (Z); 0 - модель пуста. */
  readonly extent: { readonly width: number; readonly height: number; readonly depth: number };
}

export const EMPTY_EXTENT = { width: 0, height: 0, depth: 0 } as const;

/** Точка DXF (мм) -> точка сцены three (м) относительно центра. Не зеркальный перевод. */
export const toScenePoint = (
  xMm: number,
  yMm: number,
  zMm: number,
  center: IFloor3dCenter,
): readonly [number, number, number] => [
  (xMm - center.x) / MM_IN_M,
  (zMm - center.z) / MM_IN_M,
  -(yMm - center.y) / MM_IN_M,
];

type Ring = readonly (readonly number[])[];

/** Контур без замыкающей точки-повтора; меньше трёх точек - `null`. */
const cleanRing = (ring: Ring): Point2[] | null => {
  const points: Point2[] = ring
    .filter((point) => point.length >= 2 && Number.isFinite(point[0]) && Number.isFinite(point[1]))
    .map((point) => [point[0] as number, point[1] as number]);
  const first = points[0];
  const last = points[points.length - 1];
  if (points.length > 1 && first && last && first[0] === last[0] && first[1] === last[1]) {
    points.pop();
  }
  return points.length >= 3 ? points : null;
};

const bboxOfRings = (rings: readonly Ring[]): readonly [number, number, number, number] | null => {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const ring of rings) {
    for (const point of ring) {
      const [x, y] = point;
      if (x === undefined || y === undefined) continue;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }
  }
  return Number.isFinite(minX) ? [minX, minY, maxX, maxY] : null;
};

const validBbox = (bbox: readonly number[] | null): readonly [number, number, number, number] | null =>
  bbox !== null && bbox.length === 4 && bbox.every(Number.isFinite)
    ? [bbox[0] as number, bbox[1] as number, bbox[2] as number, bbox[3] as number]
    : null;

const toLocal = (ring: readonly Point2[], center: IFloor3dCenter): Point2[] =>
  ring.map(([x, y]) => [(x - center.x) / MM_IN_M, (y - center.y) / MM_IN_M]);

/**
 * Собирает план из ответа сервера.
 *
 * Не строятся: стены без верхней отметки, плита без низа, контуры из менее чем трёх точек.
 * Плита вырезается по отверстиям `candidate` и `enabled`; `disabled` лежат отдельно (`disabledHoles`)
 * и плиту не режут.
 */
export const buildFloor3dPlan = (model: CadFloor3dRead): IFloor3dPlan => {
  let degenerate = 0;
  const ring = (source: Ring): Point2[] | null => {
    const cleaned = cleanRing(source);
    if (cleaned === null) degenerate += 1;
    return cleaned;
  };

  // Сырые призмы в мм: центр известен только после сбора всех высот.
  interface IRaw {
    id: string;
    category: PrismCategory;
    shell: Point2[];
    holes: Point2[][];
    zBottom: number;
    zTop: number;
  }
  const raw: IRaw[] = [];
  let wallsWithoutTop = 0;
  let slabWithoutBottom = false;

  const allHoles = model.slab_holes.map((hole) => ({ hole, contour: ring(hole.shell) }));
  const slabHoles = allHoles.filter(({ hole }) => hole.state !== 'disabled');

  if (model.slab !== null) {
    const shell = ring(model.slab.shell);
    if (model.slab.z_bottom_mm === null) slabWithoutBottom = true;
    else if (shell !== null) {
      raw.push({
        id: 'slab',
        category: 'slab',
        shell,
        holes: slabHoles.flatMap(({ contour }) => (contour === null ? [] : [contour])),
        zBottom: model.slab.z_bottom_mm,
        zTop: model.slab.z_top_mm,
      });
    }
  }

  for (const wall of model.walls) {
    if (wall.z_top_mm === null) {
      wallsWithoutTop += 1;
      continue;
    }
    const shell = ring(wall.shell);
    if (shell === null) continue;
    raw.push({
      id: wall.construction_key,
      category: wall.family === 'monolith' ? 'monolith' : 'masonry',
      shell,
      holes: wall.holes.flatMap((hole) => {
        const cleaned = ring(hole);
        return cleaned === null ? [] : [cleaned];
      }),
      zBottom: wall.z_bottom_mm,
      zTop: wall.z_top_mm,
    });
  }

  for (const lintel of model.lintels) {
    const shell = ring(lintel.shell);
    if (shell === null) continue;
    raw.push({
      id: lintel.opening_id,
      category: 'lintel',
      shell,
      holes: [],
      zBottom: lintel.z_bottom_mm,
      zTop: lintel.z_top_mm,
    });
  }

  // Центр: габарит в плане - bbox сервера (иначе по контурам), по высоте - середина диапазона призм.
  const bbox =
    validBbox(model.bbox) ?? bboxOfRings(raw.map((item) => item.shell as unknown as Ring));
  if (raw.length === 0 || bbox === null) {
    return {
      center: { x: 0, y: 0, z: 0 },
      prisms: [],
      holes: [],
      disabledHoles: [],
      slabCap: null,
      skipped: { wallsWithoutTop, slabWithoutBottom, degenerate },
      extent: EMPTY_EXTENT,
    };
  }
  const zMin = Math.min(...raw.map((item) => item.zBottom));
  const zMax = Math.max(...raw.map((item) => item.zTop));
  const center: IFloor3dCenter = {
    x: (bbox[0] + bbox[2]) / 2,
    y: (bbox[1] + bbox[3]) / 2,
    z: (zMin + zMax) / 2,
  };

  const prisms: IPrismSpec[] = raw.map((item) => ({
    id: item.id,
    category: item.category,
    shell: toLocal(item.shell, center),
    holes: item.holes.map((hole) => toLocal(hole, center)),
    yBottom: (item.zBottom - center.z) / MM_IN_M,
    yTop: (item.zTop - center.z) / MM_IN_M,
  }));

  const slab = prisms.find((item) => item.category === 'slab') ?? null;
  const slabTopY = slab === null ? null : slab.yTop;
  const holeSpecs = (items: typeof allHoles): IHoleSpec[] =>
    slabTopY === null
      ? []
      : items.flatMap(({ hole, contour }) =>
          contour === null
            ? []
            : [
                {
                  key: hole.key,
                  state: hole.state,
                  contour: toLocal(contour, center),
                  y: slabTopY,
                  areaM2: hole.area_m2,
                },
              ],
        );
  const holes = holeSpecs(slabHoles);
  const disabledHoles = holeSpecs(allHoles.filter(({ hole }) => hole.state === 'disabled'));

  // «Плита сверху»: толщина та же, что у плиты этажа, лежит на верхе самых высоких стен.
  const wallTops = prisms
    .filter((item) => item.category === 'masonry' || item.category === 'monolith')
    .map((item) => item.yTop);
  const slabCap =
    slab !== null && wallTops.length > 0
      ? {
          ...slab,
          id: 'slab-cap',
          yBottom: Math.max(...wallTops),
          yTop: Math.max(...wallTops) + (slab.yTop - slab.yBottom),
        }
      : null;

  const topY = Math.max(...prisms.map((item) => item.yTop));
  const bottomY = Math.min(...prisms.map((item) => item.yBottom));
  return {
    center,
    prisms,
    holes,
    disabledHoles,
    slabCap,
    skipped: { wallsWithoutTop, slabWithoutBottom, degenerate },
    extent: {
      width: (bbox[2] - bbox[0]) / MM_IN_M,
      height: topY - bottomY,
      depth: (bbox[3] - bbox[1]) / MM_IN_M,
    },
  };
};

/**
 * Какому элементу слитой геометрии принадлежит треугольник. `starts[i]` - номер первого треугольника
 * элемента `i` (по возрастанию); `-1` - треугольник вне диапазона.
 */
export const itemAtTriangle = (starts: readonly number[], total: number, face: number): number => {
  if (face < 0 || face >= total || starts.length === 0) return -1;
  let low = 0;
  let high = starts.length - 1;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if ((starts[mid] as number) <= face) low = mid;
    else high = mid - 1;
  }
  return low;
};

/** Метры с двумя знаками для отметок в карточке. */
export const formatMeters = (valueMm: number): string =>
  (valueMm / MM_IN_M).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
