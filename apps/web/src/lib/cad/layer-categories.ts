import type { ConstructionKind } from './construction-labels';

/**
 * Категории конструкций, которыми управляет вкладка «Слои» и в плане, и в 3D (ADR-0039).
 * Слой DXF с таким префиксом имени скрывает и свою подложку, и конструкции своей категории;
 * «Плита» и «Перемычки» - строки без слоя DXF.
 */
export type CadLayerCategory =
  | 'masonry'
  | 'monolith'
  | 'frame_partition'
  | 'door'
  | 'slab'
  | 'lintel';

/** Строки-категории без слоя DXF: хранятся рядом с именами скрытых слоёв. */
export type CadExtraCategory = 'slab' | 'lintel';

export const EXTRA_CATEGORIES: readonly CadExtraCategory[] = ['slab', 'lintel'];

/** Префиксы имён слоёв (в верхнем регистре); для C112 принимается и латинская, и кириллическая «С». */
const LAYER_PREFIXES: readonly { readonly pattern: RegExp; readonly category: CadLayerCategory }[] = [
  { pattern: /^01_КЛАДКА/, category: 'masonry' },
  { pattern: /^02_МОНОЛИТ/, category: 'monolith' },
  { pattern: /^07_[CС]112/, category: 'frame_partition' },
  { pattern: /^03_ДВЕРИ/, category: 'door' },
];

/** Категория слоя по префиксу имени без учёта регистра; `null` - слой только для плана. */
export const categoryOfLayer = (name: string): CadLayerCategory | null => {
  const upper = name.trim().toUpperCase();
  return LAYER_PREFIXES.find((item) => item.pattern.test(upper))?.category ?? null;
};

/** Категория конструкции листа по виду: плита - `slab`, монолит любого вида - `monolith`. */
export const categoryOfKind = (kind: ConstructionKind): CadLayerCategory => {
  if (kind === 'floor_slab') return 'slab';
  if (kind === 'masonry') return 'masonry';
  if (kind === 'frame_partition') return 'frame_partition';
  return 'monolith';
};

/**
 * Скрытые категории: категория слоёв скрыта, когда скрыты все слои листа с таким префиксом
 * (хотя бы один такой слой есть); строки «Плита» и «Перемычки» добавляются как есть.
 */
export const hiddenCategoriesOf = (
  layerNames: readonly string[],
  hiddenNames: ReadonlySet<string>,
  hiddenExtra: ReadonlySet<CadExtraCategory>,
): ReadonlySet<CadLayerCategory> => {
  const total = new Map<CadLayerCategory, number>();
  const hidden = new Map<CadLayerCategory, number>();
  for (const name of layerNames) {
    const category = categoryOfLayer(name);
    if (category === null) continue;
    total.set(category, (total.get(category) ?? 0) + 1);
    if (hiddenNames.has(name)) hidden.set(category, (hidden.get(category) ?? 0) + 1);
  }
  const result = new Set<CadLayerCategory>(hiddenExtra);
  for (const [category, count] of total) {
    if (hidden.get(category) === count) result.add(category);
  }
  return result;
};

/**
 * Конструкция скрыта слоями: у неё есть слои-источники (`source_layers`, имена слоёв DXF) и все они
 * скрыты на вкладке «Слои». Пустой список - только правило категории. Имена сравниваются точно:
 * так их хранит `useCadLayerVisibility`.
 */
export const isHiddenByLayers = (
  sourceLayers: readonly string[],
  hiddenNames: ReadonlySet<string>,
): boolean =>
  sourceLayers.length > 0 && hiddenNames.size > 0 && sourceLayers.every((name) => hiddenNames.has(name));

/** Конструкция листа в минимуме, нужном для скрытия: id, вид и слои-источники. */
export interface IHideableConstruction {
  readonly id: string;
  readonly kind: ConstructionKind;
  readonly source_layers: readonly string[];
}

/** Ключ подгруппы 3D по набору слоёв-источников; без слоёв - `undefined` (общая группа категории). */
export const layerGroupKeyOf = (sourceLayers: readonly string[]): string | undefined =>
  sourceLayers.length === 0 ? undefined : [...new Set(sourceLayers)].sort().join('\u0001');

/**
 * Ключи подгрупп 3D по id конструкций. `signature` меняется только вместе с содержимым: по нему
 * вид решает, нужна ли пересборка сцены (повторная загрузка тех же данных её не вызывает).
 */
export const layerGroupKeys = (
  constructions: readonly IHideableConstruction[],
): { readonly signature: string; readonly keyOf: (id: string) => string | undefined } => {
  const keys = new Map<string, string>();
  for (const item of constructions) {
    const key = layerGroupKeyOf(item.source_layers);
    if (key !== undefined) keys.set(item.id, key);
  }
  const signature = [...keys].map(([id, key]) => `${id}\u0002${key}`).join('\u0003');
  return { signature, keyOf: (id) => keys.get(id) };
};

/** Идентификаторы скрытых конструкций: скрыта категория вида или все слои-источники. */
export const hiddenConstructionIdsOf = (
  constructions: readonly IHideableConstruction[],
  hiddenCategories: ReadonlySet<CadLayerCategory> | undefined,
  hiddenNames: ReadonlySet<string> | undefined,
): ReadonlySet<string> => {
  const result = new Set<string>();
  for (const item of constructions) {
    if (
      hiddenCategories?.has(categoryOfKind(item.kind)) === true ||
      (hiddenNames !== undefined && isHiddenByLayers(item.source_layers, hiddenNames))
    ) {
      result.add(item.id);
    }
  }
  return result;
};

/**
 * Фигуры без скрытых конструкций: скрыта категория вида или (если у фигуры есть `layers`) все её
 * слои-источники; ничего не скрыто - тот же массив.
 */
export const withoutHiddenCategories = <
  T extends { readonly kind: ConstructionKind; readonly layers?: readonly string[] },
>(
  shapes: readonly T[],
  hidden: ReadonlySet<CadLayerCategory> | undefined,
  hiddenNames?: ReadonlySet<string>,
): readonly T[] => {
  const noCategories = hidden === undefined || hidden.size === 0;
  const noLayers = hiddenNames === undefined || hiddenNames.size === 0;
  if (noCategories && noLayers) return shapes;
  return shapes.filter(
    (shape) =>
      !(hidden?.has(categoryOfKind(shape.kind)) ?? false) &&
      !(hiddenNames !== undefined && isHiddenByLayers(shape.layers ?? [], hiddenNames)),
  );
};
