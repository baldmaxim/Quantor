/**
 * Ключи слоя «Расчёты» (ADR-0051): ключ вида и ключ слоя в хранилище видимости слоёв CAD.
 * Чистые функции без React.
 */

/** Ключ вида в формате обмена: `<revision_id>:<page_index>:<view>`. */
export const viewKeyOf = (revisionId: string, pageIndex: number, view: number): string =>
  `${revisionId}:${pageIndex}:${view}`;

const LAYER_PREFIX = 'tender:';

/**
 * Имя слоя расчёта в хранилище видимости CAD (общем у 2D и 3D). Скрытые слои хранятся по именам,
 * отсутствие записи - слой включён.
 */
export const tenderLayerKey = (calcId: string): string => `${LAYER_PREFIX}${calcId}`;

export const isTenderLayerKey = (name: string): boolean => name.startsWith(LAYER_PREFIX);

/** Расчёты, скрытые человеком: из набора скрытых имён слоёв листа остаются только слои расчётов. */
export const hiddenCalcIds = (hiddenNames: ReadonlySet<string>): ReadonlySet<string> =>
  new Set(
    [...hiddenNames].filter(isTenderLayerKey).map((name) => name.slice(LAYER_PREFIX.length)),
  );
