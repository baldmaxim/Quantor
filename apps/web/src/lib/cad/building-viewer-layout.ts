import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';

import { MM_IN_M } from './building3d-geometry';
import {
  buildViewerPlan,
  type IViewerFloorSpec,
  type IViewerGroupLabel,
  type IViewerPlan,
} from './building-viewer-geometry';

/**
 * Режим «Весь объект»: планы групп (корпус + секция) в одной сцене. Общей системы координат у групп
 * нет - каждая совмещена по осям внутри себя, - поэтому раскладка условная: группы в один ряд по X
 * в порядке списка, каждая отцентрирована по своему габариту. Отметки по высоте общие.
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
}

/** Зазор между соседними группами, м. */
export const groupGap = (widths: readonly number[]): number =>
  Math.max(MIN_GROUP_GAP_M, GROUP_GAP_FACTOR * Math.max(0, ...widths));

const shiftSpec = (spec: IViewerFloorSpec, dx: number, dy: number): IViewerFloorSpec => ({
  ...spec,
  shell: spec.shell.map(([u, v]) => [u + dx, v] as const),
  walls: spec.walls.map((wall) => ({ ...wall, shell: wall.shell.map(([u, v]) => [u + dx, v] as const) })),
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
  for (const { key, label, plan } of parts) {
    const dx = cursor + plan.size.width / 2;
    const dy = plan.zCenterMm / MM_IN_M - commonCenter;
    cursor += plan.size.width + gap;
    depth = Math.max(depth, plan.size.depth);
    const shifted = plan.floors.map((spec) => shiftSpec(spec, dx, dy));
    let top: IViewerFloorSpec | null = null;
    for (const spec of shifted) if (top === null || spec.volumeTop > top.volumeTop) top = spec;
    if (top !== null) {
      labels.push({ key, text: label, x: dx, y: top.volumeTop + LABEL_LIFT_M, z: 0, floorKey: top.key });
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

/** План всех групп: планы групп из `groups` по порядку списка; группы без этажей с отметкой пропускаются. */
export const buildAllGroupsPlan = (
  floors: readonly CadBuilding3dFloorRead[],
  groups: readonly CadBuilding3dGroupRead[],
): IViewerPlan | null => {
  const parts: IGroupPlanInput[] = [];
  for (const group of groups) {
    const plan = buildViewerPlan(floors.filter((floor) => floor.group_key === group.key));
    if (plan !== null) parts.push({ key: group.key, label: group.label, plan });
  }
  return layoutGroupPlans(parts);
};
