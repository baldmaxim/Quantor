import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';

import { MM_IN_M } from './building3d-geometry';
import {
  buildViewerPlan,
  type IViewerFloorSpec,
  type IViewerGroupLabel,
  type IViewerPlan,
} from './building-viewer-geometry';

/**
 * Режим «Весь объект»: планы групп (корпус + секция) в одной сцене. Сервер ставит группы на объект по
 * общим маркам осей (опора - обычно паркинг) и присылает их этажи уже в системе объекта: такие группы
 * рисуются одним планом на своих местах. Не поставленные группы (`placement = none`) - в своей системе
 * координат, их раскладка условная: в ряд по X справа от поставленных, каждая по своему габариту.
 * Отметки по высоте общие.
 */

/** Значение `?group=` и пункта переключателя: все группы сразу. */
export const ALL_GROUPS_KEY = 'all';

/** Зазор между группами: доля наибольшей ширины группы, но не меньше `MIN_GROUP_GAP_M`. */
export const GROUP_GAP_FACTOR = 0.15;
export const MIN_GROUP_GAP_M = 10;
/** Подпись стоит над верхом группы на этой высоте, м. */
export const LABEL_LIFT_M = 1.5;

export interface IGroupPlanInput {
  readonly key: string;
  readonly label: string;
  readonly plan: IViewerPlan;
  /**
   * Подписи нескольких групп, поставленных на объект одним планом, в координатах этого плана.
   * Нет - одна подпись `label` над верхним этажом по центру плана.
   */
  readonly labels?: readonly IViewerGroupLabel[];
}

/** Зазор между соседними группами, м. */
export const groupGap = (widths: readonly number[]): number =>
  Math.max(MIN_GROUP_GAP_M, GROUP_GAP_FACTOR * Math.max(0, ...widths));

const shiftSpec = (spec: IViewerFloorSpec, dx: number, dy: number): IViewerFloorSpec => ({
  ...spec,
  shell: spec.shell.map(([u, v]) => [u + dx, v] as const),
  walls: spec.walls.map((wall) => ({
    ...wall,
    shell: wall.shell.map(([u, v]) => [u + dx, v] as const),
    ...(wall.top === undefined ? {} : { top: wall.top + dy }),
  })),
  levels: spec.levels.map((level) => ({
    shell: level.shell.map(([u, v]) => [u + dx, v] as const),
    holes: level.holes.map((ring) => ring.map(([u, v]) => [u + dx, v] as const)),
    top: level.top + dy,
  })),
  slabBottom: spec.slabBottom + dy,
  slabTop: spec.slabTop + dy,
  volumeTop: spec.volumeTop + dy,
  wallTop: spec.wallTop + dy,
});

/**
 * Один план из планов групп. Группы идут слева направо в порядке `parts`; центр раскладки - в нуле сцены
 * (камера вписывается по нему). Высоты сведены к общей отметке: этаж на той же отметке стоит на той же высоте.
 */
export const layoutGroupPlans = (parts: readonly IGroupPlanInput[]): IViewerPlan | null => {
  if (parts.length === 0) return null;
  const gap = groupGap(parts.map((part) => part.plan.size.width));
  const total = parts.reduce((sum, part) => sum + part.plan.size.width, 0) + gap * (parts.length - 1);

  // Абсолютные высоты, м: низ самой низкой плиты и верх самого высокого объёма.
  let low = Infinity;
  let high = -Infinity;
  for (const part of parts) {
    const base = part.plan.zCenterMm / MM_IN_M;
    for (const spec of part.plan.floors) {
      low = Math.min(low, spec.slabBottom + base);
      high = Math.max(high, spec.volumeTop + base);
    }
  }
  const commonCenter = (low + high) / 2;

  const floors: IViewerFloorSpec[] = [];
  const labels: IViewerGroupLabel[] = [];
  let depth = 0;
  let cursor = -total / 2;
  for (const part of parts) {
    const { key, label, plan } = part;
    const dx = cursor + plan.size.width / 2;
    const dy = plan.zCenterMm / MM_IN_M - commonCenter;
    cursor += plan.size.width + gap;
    depth = Math.max(depth, plan.size.depth);
    const shifted = plan.floors.map((spec) => shiftSpec(spec, dx, dy));
    if (part.labels !== undefined) {
      labels.push(...part.labels.map((item) => ({ ...item, x: item.x + dx, y: item.y + dy })));
    } else {
      let top: IViewerFloorSpec | null = null;
      for (const spec of shifted) if (top === null || spec.volumeTop > top.volumeTop) top = spec;
      if (top !== null) {
        labels.push({ key, text: label, x: dx, y: top.volumeTop + LABEL_LIFT_M, z: 0, floorKey: top.key });
      }
    }
    floors.push(...shifted);
  }
  if (floors.length === 0) return null;
  return {
    floors,
    size: { width: total, depth, height: high - low },
    zCenterMm: commonCenter * MM_IN_M,
    labels,
  };
};

/**
 * Подписи групп одного плана: над верхним этажом группы, по центру её контуров в плане.
 * Ось v контура уходит в сцене в -Z (`extrudeShell` поворачивает фигуру на -90° вокруг X).
 */
export const groupLabels = (
  plan: IViewerPlan,
  groups: readonly Pick<CadBuilding3dGroupRead, 'key' | 'label'>[],
): IViewerGroupLabel[] => {
  const labels: IViewerGroupLabel[] = [];
  for (const group of groups) {
    const specs = plan.floors.filter((spec) => spec.floor.group_key === group.key);
    let top: IViewerFloorSpec | null = null;
    let minU = Infinity;
    let maxU = -Infinity;
    let minV = Infinity;
    let maxV = -Infinity;
    for (const spec of specs) {
      if (top === null || spec.volumeTop > top.volumeTop) top = spec;
      for (const [u, v] of spec.shell) {
        minU = Math.min(minU, u);
        maxU = Math.max(maxU, u);
        minV = Math.min(minV, v);
        maxV = Math.max(maxV, v);
      }
    }
    if (top === null || !Number.isFinite(minU)) continue;
    labels.push({
      key: group.key,
      text: group.label,
      x: (minU + maxU) / 2,
      y: top.volumeTop + LABEL_LIFT_M,
      z: -(minV + maxV) / 2,
      floorKey: top.key,
    });
  }
  return labels;
};

/** Поставленные на объект группы: опора и поставленные по осям; одной опоры мало - раскладывать нечего. */
const placedGroups = (groups: readonly CadBuilding3dGroupRead[]): CadBuilding3dGroupRead[] => {
  const placed = groups.filter((group) => group.placement !== 'none');
  return placed.length >= 2 ? placed : [];
};

/**
 * План всех групп. Поставленные на объект - одним планом на своих местах (первым слева), остальные -
 * планами групп по порядку списка; группы без этажей с отметкой пропускаются.
 */
export const buildAllGroupsPlan = (
  floors: readonly CadBuilding3dFloorRead[],
  groups: readonly CadBuilding3dGroupRead[],
): IViewerPlan | null => {
  const parts: IGroupPlanInput[] = [];
  const placed = placedGroups(groups);
  const placedKeys = new Set(placed.map((group) => group.key));
  if (placed.length > 0) {
    const plan = buildViewerPlan(floors.filter((floor) => placedKeys.has(floor.group_key)));
    if (plan !== null) {
      const labels = groupLabels(plan, placed);
      parts.push({ key: placed[0]?.key ?? '', label: placed[0]?.label ?? '', plan, labels });
    }
  }
  for (const group of groups) {
    if (placedKeys.has(group.key)) continue;
    const plan = buildViewerPlan(floors.filter((floor) => floor.group_key === group.key));
    if (plan !== null) parts.push({ key: group.key, label: group.label, plan });
  }
  return layoutGroupPlans(parts);
};
