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

/** Фигуры без скрытых категорий; ничего не скрыто - тот же массив. */
export const withoutHiddenCategories = <T extends { readonly kind: ConstructionKind }>(
  shapes: readonly T[],
  hidden: ReadonlySet<CadLayerCategory> | undefined,
): readonly T[] =>
  hidden === undefined || hidden.size === 0
    ? shapes
    : shapes.filter((shape) => !hidden.has(categoryOfKind(shape.kind)));
