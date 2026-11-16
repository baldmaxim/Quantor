import type { CalcElement, CalcPolyline } from '@quantor/api-client';

import type { IMepInfo, IMepInfoRow } from '@/lib/cad/floor3d-mep-info';
import { formatNumber } from '@/lib/cad/view-format';

import { disciplineLabel, systemLabel } from './systems';

/**
 * Плашка объекта расчёта (2D и 3D): расчёт, версия, система, `id`, Ø или сечение, марка, квартира,
 * примечание. Чистые функции без React; в 3D плашка собирается тем же видом `IMepInfo`.
 */

/** Откуда объект: действующая версия расчёта. */
export interface ITenderSource {
  readonly calcId: string;
  readonly versionId: string;
  /** Название репозитория расчёта. */
  readonly title: string;
  /** Номер версии, выданный порталом. */
  readonly number: number;
  /** Подпись версии от автора («v3»). */
  readonly label: string;
  readonly system: string;
  readonly discipline: string;
  /** База объекта перестроена после выпуска: координаты могут быть смещены. */
  readonly baseStale: boolean;
}

export type TenderObject =
  | { readonly kind: 'polyline'; readonly data: CalcPolyline }
  | { readonly kind: 'element'; readonly data: CalcElement };

/** Объект расчёта вместе с источником: то, что хранят выбор и плашка. */
export interface ITenderRef {
  readonly source: ITenderSource;
  readonly object: TenderObject;
}

const KIND_LABELS: Readonly<Record<string, string>> = {
  route: 'Трасса',
  jumper: 'Перемычка',
  riser: 'Стояк',
  leadin: 'Подводка',
  cable: 'Кабель',
  tray: 'Лоток',
  duct: 'Воздуховод',
};

const ELEMENT_LABELS: Readonly<Record<string, string>> = {
  fitting: 'Фасонина',
  valve: 'Арматура',
  sleeve: 'Гильза',
  terminal: 'Прибор',
  equipment: 'Оборудование',
};

const positive = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

const rowOf = (label: string, value: string): IMepInfoRow => ({ label, value });

/** Подпись версии: «№3 v3». */
export const versionTitle = (source: Pick<ITenderSource, 'number' | 'label'>): string =>
  `№${source.number} ${source.label}`.trim();

/** Длина полилинии по 3D-сегментам, м (вершины в мм). */
const lengthM = (pts: CalcPolyline['pts']): number => {
  let total = 0;
  for (let i = 1; i < pts.length; i += 1) {
    const a = pts[i - 1];
    const b = pts[i];
    if (a === undefined || b === undefined) continue;
    total += Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
  }
  return total / 1000;
};

const sectionRow = (
  shape: string | null | undefined,
  dn: number | null | undefined,
  w: number | null | undefined,
  h: number | null | undefined,
): IMepInfoRow | null => {
  if (shape === 'rect' || (shape == null && positive(w) && positive(h))) {
    return positive(w) && positive(h) ? rowOf('Сечение', `${w}×${h} мм`) : null;
  }
  return positive(dn) ? rowOf('Диаметр', `Ø ${dn} мм`) : null;
};

const sourceRows = (source: ITenderSource): IMepInfoRow[] => [
  rowOf('Расчёт', source.title),
  rowOf('Версия', versionTitle(source)),
  rowOf('Раздел', disciplineLabel(source.discipline)),
  rowOf('Система', systemLabel(source.system)),
  ...(source.baseStale ? [rowOf('База', 'устарела: вид перестроен после выпуска')] : []),
];

/** Плашка объекта расчёта. */
export const tenderInfo = (ref: ITenderRef): IMepInfo => {
  const { source, object } = ref;
  const rows: IMepInfoRow[] = [...sourceRows(source), rowOf('Объект', object.data.id)];
  if (object.kind === 'polyline') {
    const line = object.data;
    const kind = KIND_LABELS[line.kind];
    if (kind !== undefined) rows.push(rowOf('Вид', kind));
    const section = sectionRow(line.shape, line.dn_mm, line.w_mm, line.h_mm);
    if (section !== null) rows.push(section);
    if (line.mark) rows.push(rowOf('Марка', line.mark));
    if (line.apt) rows.push(rowOf('Квартира', line.apt));
    rows.push(rowOf('Длина', formatNumber(lengthM(line.pts), 2, 'м')));
    if (line.note) rows.push(rowOf('Примечание', line.note));
    return { title: kind ?? 'Трасса', rows };
  }
  const element = object.data;
  if (element.subtype) rows.push(rowOf('Тип', element.subtype));
  if (positive(element.w_mm) && positive(element.length_mm) && positive(element.h_mm)) {
    rows.push(rowOf('Размеры', `${element.w_mm}×${element.length_mm}×${element.h_mm} мм`));
  } else {
    const section = sectionRow(null, element.dn_mm, element.w_mm, element.h_mm);
    if (section !== null) rows.push(section);
  }
  if (element.mark) rows.push(rowOf('Марка', element.mark));
  if (element.apt) rows.push(rowOf('Квартира', element.apt));
  return { title: ELEMENT_LABELS[element.type] ?? 'Элемент', rows };
};
