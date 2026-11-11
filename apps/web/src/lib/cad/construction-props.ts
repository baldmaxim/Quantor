import type { CadConstructionProps } from '@quantor/api-client';

/**
 * Черновик формы параметров конструкции: строки полей <-> контракт `CadConstructionProps`.
 * Пустое поле - «не задано» (в контракте ключа нет). Диапазоны повторяют ограничения сервера:
 * понятный отказ до запроса вместо общего «Данные запроса не приняты».
 */

export type TextField =
  | 'material_note'
  | 'density_grade'
  | 'strength_class'
  | 'reinforcement'
  | 'fire_rating'
  | 'note';

export type NumberField =
  | 'block_length_mm'
  | 'block_width_mm'
  | 'block_height_mm'
  | 'joint_mm'
  | 'sound_rw_db'
  | 'height_override_mm'
  | 'thickness_override_mm';

export type SelectField = 'material' | 'brick_layout' | 'mortar' | 'purpose';

export const TEXT_MAX: Readonly<Record<TextField, number>> = {
  material_note: 200,
  density_grade: 16,
  strength_class: 16,
  reinforcement: 200,
  fire_rating: 16,
  note: 1000,
};

export const NUMBER_RANGES: Readonly<Record<NumberField, readonly [number, number]>> = {
  block_length_mm: [10, 2000],
  block_width_mm: [10, 2000],
  block_height_mm: [10, 2000],
  joint_mm: [1, 30],
  sound_rw_db: [0, 90],
  height_override_mm: [500, 10000],
  thickness_override_mm: [30, 1500],
};

export const NUMBER_LABELS: Readonly<Record<NumberField, string>> = {
  block_length_mm: 'Длина блока, мм',
  block_width_mm: 'Ширина блока, мм',
  block_height_mm: 'Высота блока, мм',
  joint_mm: 'Шов, мм',
  sound_rw_db: 'Rw, дБ',
  height_override_mm: 'Высота вручную, мм',
  thickness_override_mm: 'Толщина вручную, мм',
};

export interface IPropsDraft {
  readonly material: string;
  readonly brick_layout: string;
  readonly mortar: string;
  readonly purpose: string;
  readonly text: Readonly<Record<TextField, string>>;
  readonly numbers: Readonly<Record<NumberField, string>>;
  readonly count_openings: boolean;
}

const TEXT_FIELDS = Object.keys(TEXT_MAX) as TextField[];
const NUMBER_FIELDS = Object.keys(NUMBER_RANGES) as NumberField[];

const str = (value: string | number | null | undefined): string =>
  value === null || value === undefined ? '' : String(value);

export const draftOf = (props: CadConstructionProps): IPropsDraft => ({
  material: str(props.material),
  brick_layout: str(props.brick_layout),
  mortar: str(props.mortar),
  purpose: str(props.purpose),
  text: Object.fromEntries(TEXT_FIELDS.map((key) => [key, str(props[key])])) as Record<
    TextField,
    string
  >,
  numbers: Object.fromEntries(NUMBER_FIELDS.map((key) => [key, str(props[key])])) as Record<
    NumberField,
    string
  >,
  count_openings: props.count_openings ?? true,
});

export interface IDraftResult {
  /** Заполненные поля; пустые не входят. */
  readonly props: CadConstructionProps;
  /** Первая найденная ошибка ввода; `null` - всё в порядке. */
  readonly error: string | null;
}

/** Черновик -> параметры (только заполненные поля) и первая ошибка ввода. */
export const propsOfDraft = (draft: IPropsDraft): IDraftResult => {
  const props: Record<string, string | number | boolean> = {};
  let error: string | null = null;

  const select = (key: SelectField, value: string) => {
    if (value !== '') props[key] = value;
  };
  select('material', draft.material);
  select('brick_layout', draft.brick_layout);
  select('mortar', draft.mortar);
  select('purpose', draft.purpose);

  for (const key of TEXT_FIELDS) {
    const value = draft.text[key].trim();
    if (value === '') continue;
    if (value.length > TEXT_MAX[key]) {
      error ??= `Поле слишком длинное: не более ${TEXT_MAX[key]} знаков.`;
      continue;
    }
    props[key] = value;
  }

  for (const key of NUMBER_FIELDS) {
    const raw = draft.numbers[key].trim();
    if (raw === '') continue;
    const value = Number(raw.replace(',', '.'));
    const [min, max] = NUMBER_RANGES[key];
    if (!Number.isInteger(value) || value < min || value > max) {
      error ??= `${NUMBER_LABELS[key]}: целое число от ${min} до ${max}.`;
      continue;
    }
    props[key] = value;
  }

  props.count_openings = draft.count_openings;
  return { props: props as CadConstructionProps, error };
};

/**
 * Патч для «применить ко всем»: заполненные поля формы. Признак «учитывать надпроёмные части»
 * входит, только если его изменили или он выключен: по умолчанию он включён и «не заполнен».
 */
export const patchOfDraft = (draft: IPropsDraft, initial: IPropsDraft): IDraftResult => {
  const { props, error } = propsOfDraft(draft);
  const patch: Record<string, unknown> = { ...props };
  if (draft.count_openings && initial.count_openings) delete patch.count_openings;
  return { props: patch as CadConstructionProps, error };
};

export const isEmptyPatch = (patch: CadConstructionProps): boolean =>
  Object.keys(patch).length === 0;

/** Параметры равны (порядок ключей не важен; `count_openings` по умолчанию включён). */
export const samePropsDraft = (a: IPropsDraft, b: IPropsDraft): boolean =>
  JSON.stringify(propsOfDraft(a).props, sortedKeys) === JSON.stringify(propsOfDraft(b).props, sortedKeys) &&
  a.count_openings === b.count_openings;

const sortedKeys = (_key: string, value: unknown): unknown =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).sort(([x], [y]) => x.localeCompare(y)))
    : value;
