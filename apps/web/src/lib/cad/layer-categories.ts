import type { ConstructionKind } from './construction-labels';

/**
 * Категории конструкций, которыми управляет вкладка «Слои» и в плане, и в 3D (ADR-0039).
 * Слой DXF с таким префиксом имени скрывает и свою подложку, и конструкции своей категории;
 * «Монолит - стены и пилоны», «Монолит - колонны» и «Плита» - строки без слоя DXF. Перемычка - часть
 * своей стены и отдельной категории не имеет: скрывается вместе со стеной-хозяином.
 * `monolith` - только категория слитого меша монолита в 3D (floor3d); панель её не выдаёт, монолит
 * там скрывается по id конструкций (см. `layerGroupKeys`).
 */
export type CadLayerCategory =
  | 'masonry'
  | 'monolith_vertical'
  | 'monolith_column'
  | 'monolith'
  | 'frame_partition'
  | 'door'
  | 'slab';

/** Строки-категории без слоя DXF: хранятся рядом с именами скрытых слоёв. */
export type CadExtraCategory = 'monolith_vertical' | 'monolith_column' | 'slab';

export const EXTRA_CATEGORIES: readonly CadExtraCategory[] = [
  'monolith_vertical',
  'monolith_column',
  'slab',
];

/** Обе монолитные строки: слой DXF `02_МОНОЛИТ` один на все виды монолита. */
export const MONOLITH_CATEGORIES: readonly CadExtraCategory[] = ['monolith_vertical', 'monolith_column'];

const MONOLITH_LAYER = /^02_МОНОЛИТ/;
const SERVICE_LAYER = /^(aux|qa)_/i;

/** Слой монолита DXF (`02_МОНОЛИТ…`): в списке слоёв его нет, им управляют две монолитные строки. */
export const isMonolithLayer = (name: string): boolean => MONOLITH_LAYER.test(name.trim().toUpperCase());

/** Служебный слой движка (`AUX_…`, `QA_…`): не показывается в панели и не рисуется в плане. */
export const isServiceLayer = (name: string): boolean => SERVICE_LAYER.test(name.trim());

/** Префиксы имён слоёв (в верхнем регистре); для C112 принимается и латинская, и кириллическая «С». */
const LAYER_PREFIXES: readonly { readonly pattern: RegExp; readonly category: CadLayerCategory }[] = [
  { pattern: /^01_КЛАДКА/, category: 'masonry' },
  { pattern: /^07_[CС]112/, category: 'frame_partition' },
  { pattern: /^03_ДВЕРИ/, category: 'door' },
];

/** Категория слоя по префиксу имени без учёта регистра; `null` - слой только для плана. */
export const categoryOfLayer = (name: string): CadLayerCategory | null => {
  const upper = name.trim().toUpperCase();
  return LAYER_PREFIXES.find((item) => item.pattern.test(upper))?.category ?? null;
};

/** Категория конструкции листа по виду: стены и пилоны монолита - `monolith_vertical`, колонны - `monolith_column`. */
export const categoryOfKind = (kind: ConstructionKind): CadLayerCategory => {
  if (kind === 'floor_slab') return 'slab';
  if (kind === 'masonry') return 'masonry';
  if (kind === 'frame_partition') return 'frame_partition';
  if (kind === 'monolith_column') return 'monolith_column';
  return 'monolith_vertical';
};

/**
 * Монолит, который рисует рисовальщик конструкций, а не DXF: включена ровно одна из двух
 * монолитных строк (слой `02_МОНОЛИТ` в этом случае не рисуется). Обе включены - рисует DXF,
 * обе выключены - монолита нет.
 */
export const monolithPaintedByShapes = (
  hidden: ReadonlySet<CadLayerCategory> | undefined,
): ReadonlySet<CadLayerCategory> => {
  const visible = MONOLITH_CATEGORIES.filter((category) => hidden?.has(category) !== true);
  return visible.length === 1 ? new Set<CadLayerCategory>(visible) : new Set<CadLayerCategory>();
};

/**
 * Индексы слоёв DXF, которые в плане не рисуются: скрытые человеком, служебные (`AUX_`, `QA_`) и
 * `02_МОНОЛИТ…`, когда включена не обе монолитные строки.
 */
export const paintHiddenLayerIndices = (
  layerNames: readonly string[],
  hiddenIndices: ReadonlySet<number>,
  hiddenCategories: ReadonlySet<CadLayerCategory>,
): ReadonlySet<number> => {
  const monolithOff = MONOLITH_CATEGORIES.some((category) => hiddenCategories.has(category));
  const result = new Set(hiddenIndices);
  layerNames.forEach((name, index) => {
    if (isServiceLayer(name) || (monolithOff && isMonolithLayer(name))) result.add(index);
  });
  return result;
};

/**
 * Скрытые категории: категория слоёв скрыта, когда скрыты все слои листа с таким префиксом
 * (хотя бы один такой слой есть); строка «Плита» и монолитные строки добавляются как есть.
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
 * Ключи подгрупп 3D по id конструкций и категории слоя по id (для перемычек: они скрываются вместе
 * со стеной-хозяином). `signature` меняется только вместе с содержимым: по нему вид решает, нужна ли
 * пересборка сцены (повторная загрузка тех же данных её не вызывает).
 */
export const layerGroupKeys = (
  constructions: readonly IHideableConstruction[],
): {
  readonly signature: string;
  readonly keyOf: (id: string) => string | undefined;
  readonly categoryOf: (id: string) => CadLayerCategory | undefined;
} => {
  const keys = new Map<string, string>();
  const categories = new Map<string, CadLayerCategory>();
  for (const item of constructions) {
    const layersKey = layerGroupKeyOf(item.source_layers);
    // Меш монолита в 3D один на стены, пилоны и колонны: подгруппа делится ещё и по строке панели.
    const category = categoryOfKind(item.kind);
    categories.set(item.id, category);
    const key = MONOLITH_CATEGORIES.some((row) => row === category)
      ? `${category}\u0004${layersKey ?? ''}`
      : layersKey;
    if (key !== undefined) keys.set(item.id, key);
  }
  const signature = [
    [...keys].map(([id, key]) => `${id}\u0002${key}`).join('\u0003'),
    [...categories].map(([id, category]) => `${id}\u0002${category}`).join('\u0003'),
  ].join('\u0006');
  return { signature, keyOf: (id) => keys.get(id), categoryOf: (id) => categories.get(id) };
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
