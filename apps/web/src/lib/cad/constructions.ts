/**
 * Конструкции листа (ADR-0038): геометрия для отрисовки и попаданий, выбор по клику, положение
 * карточки у курсора. Модуль без DOM и React: ошибка здесь выглядит как «клик попал не в ту стену».
 *
 * Полигоны приходят в мм DXF (та же система, что у путей предпросмотра) и переводятся в
 * нормализованные координаты листа тем же кадром, что и CAD-пути (`frame.ts`).
 */

import type {
  CadConstructionGroupRead,
  CadConstructionRead,
  CadOpeningRead,
} from '@quantor/api-client';

import type { NormalizedPoint } from '@/lib/viewer/coordinates';
import { GridIndex, type NormalizedBounds } from '@/lib/viewer/spatial-index';

import { cadToNormalized, type ICadFrame, type IPageSize } from './frame';
import type { ConstructionKind, ConstructionStatus } from './construction-labels';

/**
 * Ключ localStorage: рисовать ли контуры всех конструкций на вкладке CAD (по умолчанию - нет,
 * рисуются только выбранные). Ключ сменён (v2), чтобы сохранённое раньше «да» не включало полный показ.
 */
export const CAD_CONSTRUCTIONS_VISIBLE_KEY = 'quantor.cad.constructions-visible.v2';

/** Контуры конструкции в нормализованных координатах: внешнее кольцо, затем отверстия. */
export type Ring = readonly NormalizedPoint[];

export interface IConstructionShape {
  readonly id: string;
  readonly kind: ConstructionKind;
  readonly status: ConstructionStatus;
  readonly accepted: boolean;
  readonly rings: readonly Ring[];
  readonly bounds: NormalizedBounds;
}

const ringOf = (
  points: readonly (readonly number[])[],
  frame: ICadFrame,
  page: IPageSize,
): Ring =>
  points.map((point) => {
    const [x, y] = cadToNormalized(frame, page, point[0] ?? 0, point[1] ?? 0);
    return { x, y };
  });

export const boundsOfRing = (ring: Ring): NormalizedBounds => {
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const point of ring) {
    if (point.x < minX) minX = point.x;
    if (point.y < minY) minY = point.y;
    if (point.x > maxX) maxX = point.x;
    if (point.y > maxY) maxY = point.y;
  }
  return { minX, minY, maxX, maxY };
};

/** Конструкция сервера -> фигура листа. Кольцо короче трёх точек не фигура: `null`. */
export const shapeOf = (
  construction: CadConstructionRead,
  frame: ICadFrame,
  page: IPageSize,
): IConstructionShape | null => {
  const shell = ringOf(construction.polygon.shell, frame, page);
  if (shell.length < 3) return null;
  const holes = construction.polygon.holes
    .map((hole) => ringOf(hole, frame, page))
    .filter((hole) => hole.length >= 3);
  return {
    id: construction.id,
    kind: construction.kind,
    status: construction.computed.status,
    accepted: construction.accepted,
    rings: [shell, ...holes],
    bounds: boundsOfRing(shell),
  };
};

export const buildShapes = (
  constructions: readonly CadConstructionRead[],
  frame: ICadFrame,
  page: IPageSize,
): IConstructionShape[] => {
  const shapes: IConstructionShape[] = [];
  for (const construction of constructions) {
    const shape = shapeOf(construction, frame, page);
    if (shape) shapes.push(shape);
  }
  return shapes;
};

/** Точка внутри кольца (чётно-нечётное правило, луч вправо). */
export const pointInRing = (point: NormalizedPoint, ring: Ring): boolean => {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
    const a = ring[index];
    const b = ring[previous];
    if (!a || !b) continue;
    if (
      a.y > point.y !== b.y > point.y &&
      point.x < ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x
    ) {
      inside = !inside;
    }
  }
  return inside;
};

/** Точка внутри фигуры: в внешнем кольце и не в отверстии. */
export const pointInRings = (point: NormalizedPoint, rings: readonly Ring[]): boolean => {
  const [shell, ...holes] = rings;
  if (!shell || !pointInRing(point, shell)) return false;
  return !holes.some((hole) => pointInRing(point, hole));
};

const distanceToSegment = (
  point: NormalizedPoint,
  a: NormalizedPoint,
  b: NormalizedPoint,
): number => {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lengthSquared = dx * dx + dy * dy;
  const t =
    lengthSquared === 0
      ? 0
      : Math.max(0, Math.min(1, ((point.x - a.x) * dx + (point.y - a.y) * dy) / lengthSquared));
  return Math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy));
};

/** Расстояние от точки до ближайшего ребра любого кольца фигуры. */
export const distanceToRings = (point: NormalizedPoint, rings: readonly Ring[]): number => {
  let best = Number.POSITIVE_INFINITY;
  for (const ring of rings) {
    for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index, index += 1) {
      const a = ring[index];
      const b = ring[previous];
      if (a && b) best = Math.min(best, distanceToSegment(point, a, b));
    }
  }
  return best;
};

const boundsArea = (bounds: NormalizedBounds): number =>
  (bounds.maxX - bounds.minX) * (bounds.maxY - bounds.minY);

export interface IConstructionIndex {
  readonly size: number;
  /**
   * Конструкция под точкой. Внутри контура - с меньшим охватом (вложенное побеждает объемлющее);
   * иначе ближайшая в пределах `tolerance` (доли листа): тонкую стену трудно попасть точно.
   * Плита перекрытия уступает любой другой конструкции под точкой.
   */
  hit(point: NormalizedPoint, tolerance: number): string | null;
  /** Идентификаторы, чей охват пересекает прямоугольник. */
  search(bounds: NormalizedBounds): string[];
}

export const buildConstructionIndex = (
  shapes: readonly IConstructionShape[],
): IConstructionIndex => {
  const grid = new GridIndex<string>();
  const byId = new Map<string, IConstructionShape>();
  for (const shape of shapes) {
    byId.set(shape.id, shape);
    grid.set(shape.id, shape.bounds);
  }
  return {
    size: byId.size,
    search: (bounds) => grid.search(bounds),
    hit: (point, tolerance) => {
      const reach = Math.max(0, tolerance);
      const candidates = grid.search({
        minX: point.x - reach,
        minY: point.y - reach,
        maxX: point.x + reach,
        maxY: point.y + reach,
      });
      let inside: IConstructionShape | null = null;
      let insideSlab: IConstructionShape | null = null;
      let near: { shape: IConstructionShape; distance: number } | null = null;
      for (const id of candidates) {
        const shape = byId.get(id);
        if (!shape) continue;
        // Плита - фон под стенами: возвращается, только если под точкой нет другой конструкции
        // (ни внутри, ни рядом); попадание в отверстие плиты и близость к её краю - не попадание.
        if (shape.kind === 'floor_slab') {
          if (pointInRings(point, shape.rings)) insideSlab = shape;
          continue;
        }
        if (pointInRings(point, shape.rings)) {
          if (inside === null || boundsArea(shape.bounds) < boundsArea(inside.bounds)) {
            inside = shape;
          }
          continue;
        }
        if (inside !== null || reach === 0) continue;
        const distance = distanceToRings(point, shape.rings);
        if (distance <= reach && (near === null || distance < near.distance)) {
          near = { shape, distance };
        }
      }
      return inside?.id ?? near?.shape.id ?? insideSlab?.id ?? null;
    },
  };
};

/* ------------------------------------------------------------------- клик и карточка */

/** Сдвиг указателя между нажатием и отпусканием, до которого жест считается щелчком. */
export const CLICK_SLOP_PX = 4;
/** Допуск попадания в конструкцию, пиксели экрана. */
export const HIT_TOLERANCE_PX = 6;

export const isClick = (
  down: { readonly x: number; readonly y: number },
  up: { readonly x: number; readonly y: number },
  slop: number = CLICK_SLOP_PX,
): boolean => Math.hypot(up.x - down.x, up.y - down.y) < slop;

export interface IPopoverPlacement {
  readonly left: number;
  readonly top: number;
}

export const POPOVER_OFFSET_PX = 12;
const POPOVER_EDGE_PX = 8;

const place = (anchor: number, size: number, limit: number, offset: number): number => {
  const edge = POPOVER_EDGE_PX;
  let start = anchor + offset;
  if (start + size > limit - edge) start = anchor - offset - size;
  return Math.max(edge, Math.min(start, Math.max(edge, limit - edge - size)));
};

/**
 * Положение карточки: правее и ниже точки клика со смещением; у края окна переворачивается влево
 * и вверх, но не выходит за него.
 */
export const placePopover = (
  anchor: { readonly x: number; readonly y: number },
  size: { readonly width: number; readonly height: number },
  viewport: { readonly width: number; readonly height: number },
  offset: number = POPOVER_OFFSET_PX,
): IPopoverPlacement => ({
  left: place(anchor.x, size.width, viewport.width, offset),
  top: place(anchor.y, size.height, viewport.height, offset),
});

/* --------------------------------------------------------------------- группы и проёмы */

/** Номинальная толщина конструкции: ключ группы «применить ко всем»; `null` - не определена. */
export const nominalOf = (construction: CadConstructionRead): number | null =>
  construction.thickness_nominal_mm;

/** Конструкции того же вида и той же номинальной толщины, включая саму. */
export const sameGroupIds = (
  constructions: readonly CadConstructionRead[],
  target: CadConstructionRead,
): string[] =>
  constructions
    .filter(
      (item) => item.kind === target.kind && nominalOf(item) === nominalOf(target),
    )
    .map((item) => item.id);

/** Конструкции группы итогов: вид, номинал, материал; в итог входят только посчитанные. */
export const groupIds = (
  constructions: readonly CadConstructionRead[],
  group: {
    readonly kind: ConstructionKind;
    readonly thickness_mm: number;
    readonly material: CadConstructionRead['props']['material'] | null;
  },
): string[] =>
  constructions
    .filter(
      (item) =>
        item.computed.status === 'ok' &&
        item.kind === group.kind &&
        item.computed.thickness_mm === group.thickness_mm &&
        (item.material.value ?? null) === group.material,
    )
    .map((item) => item.id);

/** Двери, стоящие в этой конструкции. */
export const doorsOf = (
  openings: readonly CadOpeningRead[],
  construction: CadConstructionRead,
): CadOpeningRead[] =>
  openings.filter((opening) => opening.kind === 'door' && opening.host_id === construction.id);

/* ------------------------------------------------------------------------- свод */

export type ConstructionGroup = CadConstructionGroupRead;

export interface IGroupSum {
  readonly count: number;
  readonly length_m: number;
  readonly wall_area_m2: number;
  readonly volume_m3: number;
}

const round = (value: number, digits: number): number => {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
};

/** Итог по группам, прошедшим отбор; `null` - таких групп нет. */
export const sumGroups = (
  groups: readonly ConstructionGroup[],
  pick: (group: ConstructionGroup) => boolean,
): IGroupSum | null => {
  const picked = groups.filter(pick);
  if (picked.length === 0) return null;
  return {
    count: picked.reduce((total, group) => total + group.count, 0),
    length_m: round(picked.reduce((total, group) => total + group.length_m, 0), 3),
    wall_area_m2: round(picked.reduce((total, group) => total + group.wall_area_m2, 0), 3),
    volume_m3: round(picked.reduce((total, group) => total + (group.volume_m3 ?? 0), 0), 4),
  };
};

/** Ключ строки свода: вид, номинал, материал. */
export const groupKeyOf = (group: ConstructionGroup): string =>
  `${group.kind}|${group.thickness_mm}|${group.material ?? ''}`;

export const STATUS_GROUP_PREFIX = 'status:';

/** Конструкции листа с таким статусом расчёта (строки «Толщина не определена», «Нет высоты»). */
export const statusIds = (
  constructions: readonly CadConstructionRead[],
  status: ConstructionStatus,
): string[] =>
  constructions.filter((item) => item.computed.status === status).map((item) => item.id);
