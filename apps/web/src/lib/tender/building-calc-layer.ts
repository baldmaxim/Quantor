import type { CadBuilding3dFloorRead, TenderBuildingLayerRead } from '@quantor/api-client';
import type * as THREE from 'three';

import { cleanOutline, MM_IN_M, type IBuildingFloorSpec } from '@/lib/cad/building3d-geometry';
import { buildFloor3dRoutes, readFloor3dRouteColors } from '@/lib/cad/floor3d-routes';

import type { ITenderLayerData } from './geometry';
import { placementOf, tenderFloor3dInput } from './floor3d';
import { viewKeyOf } from './view-key';

/**
 * Слой «Расчёты» в 3D здания (ADR-0051): геометрия расчёта ставится на этаж здания так же, как сам этаж:
 * `R(rotation_deg) · точка вида + offset_mm`, `z` - от отметки этажа (`base_z_mm`). Один план типового
 * этажа - одна постановка: расчёт ставится на тот этаж, ключ вида которого у него есть.
 *
 * Модуль не знает внутренностей просмотрщика: по готовому плану этажей (просмотрщик объекта и колонка «Здание») он строит по группе
 * на этаж в координатах сцены; просмотрщик лишь добавляет группу к группе этажа (разнос этажей
 * двигает расчёт вместе с ним).
 */

/** Ключ вида этажа здания в формате обмена. */
export const floorViewKey = (
  floor: Pick<CadBuilding3dFloorRead, 'revision_id' | 'page_index' | 'view'>,
): string => viewKeyOf(floor.revision_id, floor.page_index, floor.view);

/** Этажи, на которых у расчёта есть геометрия. */
export const floorsOfLayer = (
  layer: Pick<TenderBuildingLayerRead, 'view_keys'>,
  floors: readonly CadBuilding3dFloorRead[],
): CadBuilding3dFloorRead[] => floors.filter((floor) => layer.view_keys.includes(floorViewKey(floor)));

/** Геометрия одного расчёта на одном этаже здания. */
export interface IBuildingCalcItem {
  /** Ключ этажа в плане просмотрщика (`floorKey`). */
  readonly floorKey: string;
  readonly layer: ITenderLayerData;
}

/** Сдвиг из системы здания (мм) в систему сцены (м): `scene = building / 1000 + shift`. */
export interface ISceneShift {
  readonly u: number;
  readonly v: number;
  readonly h: number;
}

/**
 * Сдвиг этажа в плане просмотрщика. Берётся из самого плана - первая вершина контура этажа в мм и в
 * метрах плана, высота плиты: так же верно и для одного здания, и для «Весь объект» с раскладкой групп.
 * `null` - контура нет.
 */
export const sceneShiftOf = (spec: IBuildingFloorSpec): ISceneShift | null => {
  const outline = cleanOutline(spec.floor.outline);
  const first = outline?.[0];
  const shell = spec.shell[0];
  if (first === undefined || shell === undefined) return null;
  return {
    u: shell[0] - first[0] / MM_IN_M,
    v: shell[1] - first[1] / MM_IN_M,
    h: spec.slabTop - spec.floor.base_z_mm / MM_IN_M,
  };
};

export interface IBuildingCalcGroups {
  /** Группа сцены по ключу этажа. */
  readonly groups: ReadonlyMap<string, THREE.Group>;
  readonly dispose: () => void;
}

/** Группы сцены с геометрией расчётов по этажам плана. Этаж без расчёта группы не получает. */
export const buildBuildingCalcGroups = (
  plan: { readonly floors: readonly IBuildingFloorSpec[] },
  items: readonly IBuildingCalcItem[],
): IBuildingCalcGroups => {
  const groups = new Map<string, THREE.Group>();
  const disposers: (() => void)[] = [];
  for (const spec of plan.floors) {
    const layers = items.filter((item) => item.floorKey === spec.key).map((item) => item.layer);
    if (layers.length === 0) continue;
    const shift = sceneShiftOf(spec);
    if (shift === null) continue;
    const input = tenderFloor3dInput(layers, placementOf(spec.floor));
    if (input.polylines.length === 0 && input.elements.length === 0) continue;
    const built = buildFloor3dRoutes(
      input.polylines,
      readFloor3dRouteColors(input.layerTokens),
      // `toScenePoint`: u = (x - cx) / 1000, h = (z - cz) / 1000, Z сцены = -(y - cy) / 1000.
      {
        center: { x: -shift.u * MM_IN_M, y: -shift.v * MM_IN_M, z: -shift.h * MM_IN_M },
        baseZMm: spec.floor.base_z_mm,
      },
      input.elements,
    );
    groups.set(spec.key, built.group);
    disposers.push(built.dispose);
  }
  return {
    groups,
    dispose: () => {
      for (const dispose of disposers) dispose();
      groups.clear();
    },
  };
};
