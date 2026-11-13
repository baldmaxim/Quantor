import { MEP_LAYERS } from './mep-layers';

/**
 * Числа у слоёв трасс в панели «Слои»: сколько приборов на слое. Прибор - одна замкнутая фигура
 * на слое `M-SAN-*` в `preview.json` трасс. У остальных слоёв трасс числа нет (`null`).
 */

/** Часть `preview.json` трасс, нужная для подсчёта. */
export interface IMepCountSource {
  readonly layers: readonly string[];
  readonly paths: readonly { readonly layer: number; readonly closed: boolean }[];
}

const SANITARY_PREFIX = 'M-SAN-';

/** Слой приборов санузлов и кухонь. */
export const isSanitaryMepLayer = (name: string): boolean =>
  MEP_LAYERS.some((def) => def.name === name) && name.startsWith(SANITARY_PREFIX);

/** Числа по слоям `names` (по индексу `names`); не `M-SAN-*` - `null`, слой без фигур - 0. */
export const mepLayerCounts = (
  preview: IMepCountSource,
  names: readonly string[],
): (number | null)[] => {
  const closedByLayer = new Map<number, number>();
  for (const path of preview.paths) {
    if (path.closed) closedByLayer.set(path.layer, (closedByLayer.get(path.layer) ?? 0) + 1);
  }
  return names.map((name) => {
    if (!isSanitaryMepLayer(name)) return null;
    const index = preview.layers.indexOf(name);
    return index < 0 ? 0 : (closedByLayer.get(index) ?? 0);
  });
};

/** Сумма чисел группы по индексам `counts`; ни у одного слоя числа нет - `null`. */
export const mepGroupCount = (
  counts: readonly (number | null)[],
  indices: readonly number[],
): number | null => {
  let total: number | null = null;
  for (const index of indices) {
    const value = counts[index] ?? null;
    if (value !== null) total = (total ?? 0) + value;
  }
  return total;
};
