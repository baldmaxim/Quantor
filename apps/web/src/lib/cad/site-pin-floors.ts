import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';

import { cleanOutline, floorKey } from './building3d-geometry';

/**
 * Какие этажи предлагает диалог ручной привязки (ADR-0052): панель корпуса и панель площадки.
 * Этаж подходит, если у него есть геометрия (контур или стены) и его лист ещё не предложен: копии
 * типового листа делят один лист, а точки сервер привязывает к листу.
 */

const sheetAddress = (floor: CadBuilding3dFloorRead): string =>
  `${floor.revision_id}:${floor.page_index}:${floor.view}`;

export const hasPlanGeometry = (floor: CadBuilding3dFloorRead): boolean =>
  cleanOutline(floor.outline) !== null || (floor.walls ?? []).length > 0;

const distinctSheets = (floors: readonly CadBuilding3dFloorRead[]): CadBuilding3dFloorRead[] => {
  const seen = new Set<string>();
  const result: CadBuilding3dFloorRead[] = [];
  for (const floor of floors) {
    const address = sheetAddress(floor);
    if (seen.has(address)) continue;
    seen.add(address);
    result.push(floor);
  }
  return result;
};

const byElevationAsc = (a: CadBuilding3dFloorRead, b: CadBuilding3dFloorRead): number =>
  a.base_z_mm - b.base_z_mm || a.label.localeCompare(b.label, 'ru') || a.page_index - b.page_index;

/** Этажи привязываемого корпуса с геометрией, снизу вверх: первый - нижний, он выбран по умолчанию. */
export const sourceFloorsOf = (
  floors: readonly CadBuilding3dFloorRead[],
  groupKey: string,
): CadBuilding3dFloorRead[] =>
  distinctSheets(
    floors.filter((floor) => floor.group_key === groupKey && hasPlanGeometry(floor)).sort(byElevationAsc),
  );

/** Площадь контура этажа, мм²: по ней выбирается основной этаж площадки. */
export const outlineAreaMm2 = (floor: CadBuilding3dFloorRead): number => {
  const ring = cleanOutline(floor.outline);
  if (ring === null) return 0;
  let twice = 0;
  ring.forEach((point, index) => {
    const next = ring[(index + 1) % ring.length] as readonly [number, number];
    twice += point[0] * next[1] - next[0] * point[1];
  });
  return Math.abs(twice) / 2;
};

export interface ITargetFloors {
  readonly floors: readonly CadBuilding3dFloorRead[];
  /** Ключ этажа по умолчанию; `null` - предлагать нечего. */
  readonly defaultKey: string | null;
}

/**
 * Этажи уже поставленных зданий (кроме привязываемого). По умолчанию - этаж базового здания
 * (`placement = reference`; нет такого - любого поставленного) с наибольшей площадью контура.
 */
export const targetFloorsOf = (
  floors: readonly CadBuilding3dFloorRead[],
  groups: readonly CadBuilding3dGroupRead[],
  sourceGroupKey: string,
): ITargetFloors => {
  const placed = groups.filter((group) => group.placement !== 'none' && group.key !== sourceGroupKey);
  const placedKeys = new Set(placed.map((group) => group.key));
  const candidates = distinctSheets(
    floors.filter((floor) => placedKeys.has(floor.group_key) && hasPlanGeometry(floor)).sort(byElevationAsc),
  );
  const base = new Set(placed.filter((group) => group.placement === 'reference').map((group) => group.key));
  const pool = candidates.filter((floor) => base.has(floor.group_key));
  const from = pool.length > 0 ? pool : candidates;
  let best: CadBuilding3dFloorRead | null = null;
  for (const floor of from) {
    if (best === null || outlineAreaMm2(floor) > outlineAreaMm2(best)) best = floor;
  }
  return { floors: candidates, defaultKey: best === null ? null : floorKey(best) };
};

/** Подпись этажа в списке выбора: здание и этаж. */
export const sitePinFloorLabel = (floor: CadBuilding3dFloorRead): string =>
  floor.label.startsWith(floor.group_label) ? floor.label : `${floor.group_label} · ${floor.label}`;
