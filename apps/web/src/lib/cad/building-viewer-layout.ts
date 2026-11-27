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
 * общим маркам осей и ядрам (опора - обычно паркинг) и присылает их этажи уже в системе объекта: такие
 * группы рисуются одним планом на своих местах. Не поставленные группы (`placement = none`) - в своей
 * системе координат: их место на объекте неизвестно, поэтому они стоят отдельным блоком за поставленными
 * (ряд по X, каждая по своему габариту), полупрозрачные и с подписью «не поставлен на объект».
 * Отметки по высоте общие.
 */

/** Значение `?group=` и пункта переключателя: все группы сразу. */
export const ALL_GROUPS_KEY = 'all';

/** Зазор между группами: доля наибольшей ширины группы, но не меньше `MIN_GROUP_GAP_M`. */
export const GROUP_GAP_FACTOR = 0.15;
export const MIN_GROUP_GAP_M = 10;
/** Подпись стоит над верхом группы на этой высоте, м. */
export const LABEL_LIFT_M = 1.5;
/** Блок не поставленных групп отстоит от поставленных не меньше чем на это расстояние, м. */
export const MIN_LOST_GAP_M = 20;
/** Вторая строка подписи не поставленной группы. */
export const NOT_PLACED_NOTE = 'не поставлен на объект';

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

/** Сдвиг этажа: `dx` и `dv` - в плане (м), `dy` - по высоте; `ghost` - здание не поставлено на объект. */
const shiftSpec = (spec: IViewerFloorSpec, dx: number, dy: number, dv = 0, ghost = false): IViewerFloorSpec => ({
  ...spec,
  ...(ghost ? { ghost: true } : {}),
  shell: spec.shell.map(([u, v]) => [u + dx, v + dv] as const),
  ...(spec.extraShells === undefined
    ? {}
    : { extraShells: spec.extraShells.map((ring) => ring.map(([u, v]) => [u + dx, v + dv] as const)) }),
  walls: spec.walls.map((wall) => ({
    ...wall,
    shell: wall.shell.map(([u, v]) => [u + dx, v + dv] as const),
    ...(wall.top === undefined ? {} : { top: wall.top + dy }),
  })),
  windows: spec.windows.map((window) => ({
    ...window,
    shell: window.shell.map(([u, v]) => [u + dx, v + dv] as const),
    sillBottom: window.sillBottom + dy,
    glassBottom: window.glassBottom + dy,
    glassTop: window.glassTop + dy,
    lintelTop: window.lintelTop + dy,
  })),
  levels: spec.levels.map((level) => ({
    shell: level.shell.map(([u, v]) => [u + dx, v + dv] as const),
    holes: level.holes.map((ring) => ring.map(([u, v]) => [u + dx, v + dv] as const)),
    top: level.top + dy,
  })),
  slabBottom: spec.slabBottom + dy,
  slabTop: spec.slabTop + dy,
  volumeTop: spec.volumeTop + dy,
  wallTop: spec.wallTop + dy,
});

const rowWidth = (parts: readonly IGroupPlanInput[], gap: number): number =>
  parts.reduce((sum, part) => sum + part.plan.size.width, 0) + gap * Math.max(0, parts.length - 1);

const rowDepth = (parts: readonly IGroupPlanInput[]): number =>
  Math.max(0, ...parts.map((part) => part.plan.size.depth));

/**
 * Один план из планов групп. Группы `parts` идут слева направо в порядке списка. Не поставленные на
 * объект группы `lost` - отдельным блоком за ними (дальше по оси v), своим рядом по центру, помечены
 * `ghost`, в подписи - `NOT_PLACED_NOTE`. Центр раскладки - в нуле сцены (камера вписывается по нему).
 * Высоты сведены к общей отметке: этаж на той же отметке стоит на той же высоте.
 */
export const layoutGroupPlans = (
  parts: readonly IGroupPlanInput[],
  lost: readonly IGroupPlanInput[] = [],
): IViewerPlan | null => {
  if (parts.length === 0 && lost.length === 0) return null;
  const all = [...parts, ...lost];
  const gap = groupGap(all.map((part) => part.plan.size.width));
  const frontDepth = rowDepth(parts);
  const lostDepth = rowDepth(lost);
  const blockGap = parts.length > 0 && lost.length > 0 ? Math.max(MIN_LOST_GAP_M, gap) : 0;
  const depth = frontDepth + blockGap + lostDepth;

  // Абсолютные высоты, м: низ самой низкой плиты и верх самого высокого объёма.
  let low = Infinity;
  let high = -Infinity;
  for (const part of all) {
    const base = part.plan.zCenterMm / MM_IN_M;
    for (const spec of part.plan.floors) {
      low = Math.min(low, spec.slabBottom + base);
      high = Math.max(high, spec.volumeTop + base);
    }
  }
  const commonCenter = (low + high) / 2;

  const floors: IViewerFloorSpec[] = [];
  const labels: IViewerGroupLabel[] = [];
  const place = (row: readonly IGroupPlanInput[], dv: number, ghost: boolean): void => {
    let cursor = -rowWidth(row, gap) / 2;
    for (const part of row) {
      const { key, label, plan } = part;
      const dx = cursor + plan.size.width / 2;
      const dy = plan.zCenterMm / MM_IN_M - commonCenter;
      cursor += plan.size.width + gap;
      const shifted = plan.floors.map((spec) => shiftSpec(spec, dx, dy, dv, ghost));
      const note = ghost ? { note: NOT_PLACED_NOTE } : {};
      if (part.labels !== undefined) {
        labels.push(...part.labels.map((item) => ({ ...item, ...note, x: item.x + dx, y: item.y + dy, z: item.z - dv })));
      } else {
        let top: IViewerFloorSpec | null = null;
        for (const spec of shifted) if (top === null || spec.volumeTop > top.volumeTop) top = spec;
        if (top !== null) {
          labels.push({ key, text: label, ...note, x: dx, y: top.volumeTop + LABEL_LIFT_M, z: -dv, floorKey: top.key });
        }
      }
      floors.push(...shifted);
    }
  };
  // Ось v уходит в сцене в -Z: блок не поставленных стоит дальше от камеры исходного вида.
  place(parts, -depth / 2 + frontDepth / 2, false);
  place(lost, depth / 2 - lostDepth / 2, parts.length > 0);
  if (floors.length === 0) return null;
  return {
    floors,
    size: { width: Math.max(rowWidth(parts, gap), rowWidth(lost, gap)), depth, height: high - low },
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
      for (const [u, v] of [spec.shell, ...(spec.extraShells ?? [])].flat()) {
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

/**
 * План всех групп. Поставленные на объект (опора, по осям, по ядрам) - одним планом на своих местах;
 * не поставленные - отдельным блоком за ними, полупрозрачные, с пометкой в подписи. Группы без этажей с
 * отметкой пропускаются. Ответ без постановки (ни одной поставленной группы) - все группы в ряд.
 */
export const buildAllGroupsPlan = (
  floors: readonly CadBuilding3dFloorRead[],
  groups: readonly CadBuilding3dGroupRead[],
): IViewerPlan | null => {
  const placed = groups.filter((group) => group.placement !== 'none');
  const placedKeys = new Set(placed.map((group) => group.key));
  const parts: IGroupPlanInput[] = [];
  if (placed.length > 0) {
    const plan = buildViewerPlan(floors.filter((floor) => placedKeys.has(floor.group_key)));
    if (plan !== null) {
      const labels = groupLabels(plan, placed);
      parts.push({ key: placed[0]?.key ?? '', label: placed[0]?.label ?? '', plan, labels });
    }
  }
  const lost: IGroupPlanInput[] = [];
  for (const group of groups) {
    if (placedKeys.has(group.key)) continue;
    const plan = buildViewerPlan(floors.filter((floor) => floor.group_key === group.key));
    if (plan !== null) lost.push({ key: group.key, label: group.label, plan });
  }
  return parts.length === 0 ? layoutGroupPlans(lost) : layoutGroupPlans(parts, lost);
};
