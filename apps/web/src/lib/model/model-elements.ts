/** Элементы этажа из части `elements/<этаж>.jsonl` пакета QMP (ADR-0053). */

export type ModelPropValue = string | number | boolean | null;

export interface IModelElement {
  readonly id: string;
  readonly category: string;
  readonly ifc_class?: string | null;
  readonly name?: string | null;
  readonly type?: string | null;
  readonly discipline: string;
  readonly bbox_mm?: readonly number[] | null;
  readonly part?: string | null;
  readonly props?: Readonly<Record<string, ModelPropValue>>;
}

export const CATEGORY_LABELS: Readonly<Record<string, string>> = {
  wall: 'Стена',
  slab: 'Перекрытие',
  column: 'Колонна',
  beam: 'Балка',
  door: 'Дверь',
  window: 'Окно',
  curtain_wall: 'Витраж',
  plate: 'Панель',
  member: 'Профиль',
  railing: 'Ограждение',
  stair: 'Лестница',
  covering: 'Покрытие',
  roof: 'Кровля',
  furniture: 'Мебель',
  equipment: 'Оборудование',
  pipe: 'Труба',
  duct: 'Воздуховод',
  cable_carrier: 'Лоток',
  other: 'Прочее',
};

const isElement = (value: unknown): value is IModelElement => {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const row = value as Record<string, unknown>;
  return (
    typeof row.id === 'string' &&
    typeof row.category === 'string' &&
    typeof row.discipline === 'string'
  );
};

/** Разбор JSON Lines: строки не той формы и битые пропускаются, а не роняют этаж. */
export const parseElements = (text: string): Map<string, IModelElement> => {
  const out = new Map<string, IModelElement>();
  for (const line of text.split('\n')) {
    if (line.trim() === '') {
      continue;
    }
    try {
      const row: unknown = JSON.parse(line);
      if (isElement(row)) {
        out.set(row.id, row);
      }
    } catch {
      // битая строка: элемента в списке не будет, геометрия этажа при этом рисуется
    }
  }
  return out;
};

export const categoryLabel = (category: string): string => CATEGORY_LABELS[category] ?? category;

export const elementTitle = (element: IModelElement): string => {
  const name = element.name?.trim();
  if (name) {
    return name;
  }
  const type = element.type?.trim();
  return type ? type : categoryLabel(element.category);
};

export interface IPropRow {
  readonly label: string;
  readonly value: string;
}

const propText = (value: ModelPropValue): string => {
  if (value === null) {
    return '—';
  }
  if (typeof value === 'boolean') {
    return value ? 'да' : 'нет';
  }
  return String(value);
};

/** Строки плашки элемента: категория, дисциплина, тип, класс источника, затем свойства. */
export const propertyRows = (element: IModelElement): IPropRow[] => {
  const rows: IPropRow[] = [
    { label: 'Категория', value: categoryLabel(element.category) },
    { label: 'Дисциплина', value: element.discipline },
  ];
  if (element.type) {
    rows.push({ label: 'Тип', value: element.type });
  }
  if (element.ifc_class) {
    rows.push({ label: 'Класс IFC', value: element.ifc_class });
  }
  for (const [label, value] of Object.entries(element.props ?? {})) {
    rows.push({ label, value: propText(value) });
  }
  return rows;
};

/** Отметка этажа в метрах со знаком: `+10,540`, `−5,940`, `+0,000`. */
export const formatElevation = (mm: number): string => {
  const rounded = Math.round(mm);
  const metres = (Math.abs(rounded) / 1000).toFixed(3).replace('.', ',');
  return `${rounded < 0 ? '−' : '+'}${metres}`;
};
