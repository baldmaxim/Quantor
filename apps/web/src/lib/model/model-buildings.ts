import type { ModelStoreyRead } from '@quantor/api-client';

/** Здание модели и его этажи в порядке ответа API (внутри здания - по отметке снизу вверх). */
export interface IStoreyGroup {
  /** `building_key`; `null` - этажи вне зданий или модель одного здания (полей здания нет). */
  readonly key: string | null;
  readonly name: string | null;
  readonly storeys: readonly ModelStoreyRead[];
}

/**
 * Этажи по зданиям (QMP v1, раздел 4). API отдаёт этажи уже по зданиям, порядок сохраняется;
 * модель без полей здания - одна группа с `key = null`.
 */
export const storeysByBuilding = (storeys: readonly ModelStoreyRead[]): IStoreyGroup[] => {
  const groups = new Map<string | null, { name: string | null; storeys: ModelStoreyRead[] }>();
  for (const storey of storeys) {
    const key = storey.building_key ?? null;
    const group = groups.get(key);
    if (group) group.storeys.push(storey);
    else groups.set(key, { name: storey.building_name ?? null, storeys: [storey] });
  }
  return [...groups].map(([key, group]) => ({ key, ...group }));
};

/** Модель с несколькими зданиями: у этажей есть `building_key`. */
export const hasBuildings = (groups: readonly IStoreyGroup[]): boolean =>
  groups.some((group) => group.key !== null);

/**
 * Уровни «Всего дома» снизу вверх: номер различной отметки. Этажи разных зданий на одной отметке -
 * один уровень, поэтому ползунок «Этажи снизу до» и разнос этажей режут все корпуса по высоте.
 * В модели одного здания отметки различны, уровень - номер этажа снизу, как раньше.
 */
export const elevationLevels = (
  storeys: readonly ModelStoreyRead[],
): { readonly levels: readonly number[]; readonly levelOf: ReadonlyMap<string, number> } => {
  const levels = [...new Set(storeys.map((storey) => storey.elevation_mm))].sort((a, b) => a - b);
  const index = new Map(levels.map((elevation, level) => [elevation, level]));
  return {
    levels,
    levelOf: new Map(
      storeys.map((storey) => [storey.storey_key, index.get(storey.elevation_mm) ?? 0]),
    ),
  };
};
