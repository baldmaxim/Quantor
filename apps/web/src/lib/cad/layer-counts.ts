import type { ConstructionKind } from './construction-labels';

/**
 * Числа вкладки «Слои»: сколько конструкций листа в каждой строке/группе. `null` - данных нет
 * (не считались, не загружены или в данных такого нет): число не показывается, а не «0».
 */
export interface ICadLayerCounts {
  readonly monolithVertical: number | null;
  readonly monolithColumn: number | null;
  readonly slab: number | null;
  /** Конструкции вида `masonry` (группа DXF «Кладка и перегородки»). */
  readonly masonry: number | null;
  /** Двери листа (группа DXF «Двери и ворота»). */
  readonly doors: number | null;
}

export const NO_LAYER_COUNTS: ICadLayerCounts = {
  monolithVertical: null,
  monolithColumn: null,
  slab: null,
  masonry: null,
  doors: null,
};

/** Числа по данным конструкций листа; данных нет - все `null`. */
export const layerCountsOf = (
  data: {
    readonly constructions: readonly { readonly kind: ConstructionKind }[];
    readonly openings: readonly { readonly kind: string }[];
  } | null,
): ICadLayerCounts => {
  if (data === null) return NO_LAYER_COUNTS;
  const count = (...kinds: ConstructionKind[]): number =>
    data.constructions.filter((item) => kinds.includes(item.kind)).length;
  return {
    monolithVertical: count('monolith_wall', 'monolith_pylon'),
    monolithColumn: count('monolith_column'),
    slab: count('floor_slab'),
      masonry: count('masonry'),
    doors: data.openings.filter((item) => item.kind === 'door').length,
  };
};
