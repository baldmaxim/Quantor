import type { CadConstructionProps, CadConstructionRead } from '@quantor/api-client';

/**
 * Подписи контура «Конструкции CAD» (ADR-0038): виды, материалы, назначение, источники величин и
 * предупреждения расчёта. Словари по-русски; значения - из контракта API, ручных DTO нет.
 */

export type ConstructionKind = CadConstructionRead['kind'];
export type ConstructionStatus = CadConstructionRead['computed']['status'];
export type ConstructionWarning = CadConstructionRead['computed']['warnings'][number];
export type MaterialSource = NonNullable<CadConstructionRead['material']['source']>;
export type ValueSource = NonNullable<CadConstructionRead['computed']['sources']['height']>;

type Material = NonNullable<CadConstructionProps['material']>;
type BrickLayout = NonNullable<CadConstructionProps['brick_layout']>;
type Mortar = NonNullable<CadConstructionProps['mortar']>;
type Purpose = NonNullable<CadConstructionProps['purpose']>;

export const CONSTRUCTION_KINDS: readonly ConstructionKind[] = [
  'masonry',
  'monolith_wall',
  'monolith_pylon',
  'monolith_column',
  'frame_partition',
];

export const KIND_LABELS: Readonly<Record<ConstructionKind, string>> = {
  masonry: 'Кладка',
  monolith_wall: 'Монолит — стена',
  monolith_pylon: 'Монолит — пилон',
  monolith_column: 'Монолит — колонна',
  frame_partition: 'Каркасная перегородка ГКЛ',
};

export const isMonolith = (kind: ConstructionKind): boolean =>
  kind === 'monolith_wall' || kind === 'monolith_pylon' || kind === 'monolith_column';

/** Каркасная перегородка ГКЛ меряется площадью: объёма у неё нет. */
export const isFramePartition = (kind: ConstructionKind): boolean => kind === 'frame_partition';

export const MATERIAL_LABELS: Readonly<Record<Material, string>> = {
  aerated_concrete: 'Газобетон',
  expanded_clay_block: 'Керамзитобетонный блок',
  ceramic_block: 'Керамический блок',
  brick_solid: 'Кирпич полнотелый',
  brick_hollow: 'Кирпич пустотелый',
  silicate_block: 'Силикатный блок',
  gypsum_tongue_groove: 'Пазогребневая плита',
  monolith_concrete: 'Монолитный железобетон',
  other: 'Другое',
};

export const MATERIALS = Object.keys(MATERIAL_LABELS) as readonly Material[];

export const BRICK_LAYOUT_LABELS: Readonly<Record<BrickLayout, string>> = {
  half: '½ кирпича',
  one: '1 кирпич',
  one_and_half: '1½ кирпича',
  two: '2 кирпича',
};

export const BRICK_LAYOUTS = Object.keys(BRICK_LAYOUT_LABELS) as readonly BrickLayout[];

export const MORTAR_LABELS: Readonly<Record<Mortar, string>> = {
  glue: 'Клей',
  cement_sand: 'Цементно-песчаный',
  other: 'Другой',
};

export const MORTARS = Object.keys(MORTAR_LABELS) as readonly Mortar[];

export const PURPOSE_LABELS: Readonly<Record<Purpose, string>> = {
  external: 'Наружная',
  inter_apartment: 'Межквартирная',
  interior: 'Межкомнатная',
  mop: 'МОП',
  shaft: 'Шахта',
  other: 'Другое',
};

export const PURPOSES = Object.keys(PURPOSE_LABELS) as readonly Purpose[];

export const SOURCE_LABELS: Readonly<Record<ValueSource, string>> = {
  observed: 'документ',
  derived: 'выведено',
  assumption: 'допущение',
  manual: 'вручную',
};

export const sourceLabel = (source: ValueSource | null | undefined): string =>
  source ? SOURCE_LABELS[source] : 'источник не определён';

/** Источник действующего материала конструкции: ввод человека или условные обозначения листа. */
export const MATERIAL_SOURCE_LABELS: Readonly<Record<MaterialSource, string>> = {
  document: 'документ',
  manual: 'вручную',
};

export const materialSourceLabel = (source: MaterialSource | null | undefined): string =>
  source ? MATERIAL_SOURCE_LABELS[source] : 'источник не определён';

export const STATUS_LABELS: Readonly<Record<ConstructionStatus, string>> = {
  ok: 'Посчитано',
  thickness_check: 'Проверить толщину',
  height_missing: 'Нет высоты',
};

export const WARNING_LABELS: Readonly<Record<ConstructionWarning, string>> = {
  thickness_check: 'Толщина не совпала с номиналом: назначьте толщину вручную.',
  height_missing: 'Высота не определена: задайте высоту этажа или высоту вручную.',
  opening_no_data: 'У проёма нет данных о ширине или толщине: он не учтён.',
  opening_estimate: 'Размеры проёма оценены по допущению.',
  material_check:
    'Проверить материал: в условных обозначениях нет однозначного материала для этой толщины.',
};

/** Материал по умолчанию для вида: у монолита - монолитный железобетон, у кладки его нет. */
export const defaultMaterial = (kind: ConstructionKind): Material | null =>
  isMonolith(kind) ? 'monolith_concrete' : null;

export const materialLabel = (material: Material | null | undefined): string =>
  material ? MATERIAL_LABELS[material] : 'не задан';

export const BRICK_MATERIALS: ReadonlySet<Material> = new Set<Material>([
  'brick_solid',
  'brick_hollow',
]);

const BLOCK_MATERIALS: ReadonlySet<Material> = new Set<Material>([
  'aerated_concrete',
  'expanded_clay_block',
  'ceramic_block',
  'silicate_block',
  'gypsum_tongue_groove',
]);

/** Показывать «Кладка в кирпичах»: у кирпича и у материала, который ещё не выбран. */
export const showBrickLayout = (kind: ConstructionKind, material: Material | null): boolean =>
  kind === 'masonry' &&
  (material === null || material === 'other' || BRICK_MATERIALS.has(material));

/** Показывать размер блока: у блоков и у материала, который ещё не выбран. */
export const showBlockSize = (kind: ConstructionKind, material: Material | null): boolean =>
  kind === 'masonry' &&
  (material === null || material === 'other' || BLOCK_MATERIALS.has(material));

/** Заголовок карточки: вид и толщина. */
export const constructionTitle = (construction: CadConstructionRead): string => {
  const thickness = construction.computed.thickness_mm ?? construction.thickness_nominal_mm;
  return thickness === null
    ? `${KIND_LABELS[construction.kind]}, толщина не определена — проверить`
    : `${KIND_LABELS[construction.kind]}, ${thickness} мм`;
};
