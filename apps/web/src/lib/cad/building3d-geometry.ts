import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';

/**
 * План колонки «Здание» (вид «3D»): чистые функции без DOM и без three.js.
 *
 * Этаж с известной отметкой - призма: контур `outline` (мм системы DXF, Y вверх), плита толщиной
 * `slab_thickness_mm` под `base_z_mm` и полупрозрачный объём этажа от `base_z_mm` на
 * `floor_height_mm`. Координаты XY берутся как есть: сервер уже совместил этажи одного здания
 * (корпус + секция) по осям, поэтому план строится по этажам одного выбранного здания, а общий
 * центр - один на это здание. Этажи без отметки в 3D не строятся.
 *
 * Ориентация та же, что в `floor3d-geometry`: контур `(u, v) = (x, y)` в метрах, сцена three:
 * `X = u`, `Y` = высота, `Z = -v`.
 */

export const MM_IN_M = 1000;

export type Point2 = readonly [number, number];

export interface IBuildingFloorSpec {
  readonly key: string;
  readonly floor: CadBuilding3dFloorRead;
  /** Контур в плане, м, от общего центра. */
  readonly shell: readonly Point2[];
  /** Высоты, м, от общего центра по высоте: низ плиты, верх плиты (= отметка этажа), верх объёма. */
  readonly slabBottom: number;
  readonly slabTop: number;
  readonly volumeTop: number;
}

export interface IBuildingPlan {
  /** Построенные этажи, сверху вниз. */
  readonly floors: readonly IBuildingFloorSpec[];
  /** Центр габарита, мм. */
  readonly center: { readonly x: number; readonly y: number; readonly z: number };
  /** Габарит здания, м. */
  readonly size: { readonly width: number; readonly depth: number; readonly height: number };
}

export interface IBuildingList {
  /** Этажи с отметкой, сверху вниз; в 3D строятся те, у кого годится контур. */
  readonly known: readonly CadBuilding3dFloorRead[];
  /** Этажи без отметки: списком, внизу. */
  readonly unknown: readonly CadBuilding3dFloorRead[];
}

/**
 * Ключ этажа: адрес его листа (то же, что открывает лист на холсте). У копии типового листа
 * (`typical_of`) лист общий с другими его этажами, поэтому к адресу добавлена отметка.
 */
export const floorKey = (
  floor: Pick<CadBuilding3dFloorRead, 'job_id' | 'page_index' | 'view'> &
    Partial<Pick<CadBuilding3dFloorRead, 'typical_of' | 'base_z_mm'>>,
): string => {
  const sheet = `${floor.job_id}:${floor.page_index}:${floor.view}`;
  return floor.typical_of === undefined || floor.typical_of === null ? sheet : `${sheet}@${floor.base_z_mm ?? 0}`;
};

/** Отметка в метрах: «+3.000», «-3.200», «0.000». */
export const formatElevation = (baseZMm: number): string => {
  const meters = baseZMm / MM_IN_M;
  const text = meters.toFixed(3);
  return meters > 0 ? `+${text}` : meters === 0 ? '0.000' : text;
};

/** Откуда высота этажа, когда она не определена: по отметке следующего этажа или типовая. */
export const heightNote = (floor: CadBuilding3dFloorRead): string | null => {
  if (floor.floor_height_known) return null;
  return floor.floor_height_source === 'derived_stack' ? 'высота по отметке следующего этажа' : 'высота типовая';
};

/** Подпись этажа: отметка и пометка, если высота этажа не прочитана, а принята для отрисовки. */
export const describeFloor = (floor: CadBuilding3dFloorRead): string => {
  if (!floor.elevation_known) return `${floor.label}, отметка не определена`;
  const height = heightNote(floor);
  return `${floor.label}, ${formatElevation(floor.base_z_mm)}${height === null ? '' : `, ${height}`}`;
};

/** Этажи выбранного здания; ключа нет (старый ответ без групп) - все этажи. */
export const filterFloorsByGroup = (
  floors: readonly CadBuilding3dFloorRead[],
  groupKey: string | null,
): CadBuilding3dFloorRead[] =>
  groupKey === null ? [...floors] : floors.filter((floor) => floor.group_key === groupKey);

/**
 * Действующее здание по убыванию приоритета: ручной выбор, группа открытого листа, первое в списке.
 * Ключ, которого нет в ответе, пропускается; групп нет - `null`.
 */
export const resolveGroupKey = (
  groups: readonly CadBuilding3dGroupRead[],
  chosen: string | null,
  sheetGroup: string | null = null,
): string | null => {
  const first = groups[0];
  if (first === undefined) return null;
  const exists = (key: string | null): key is string => key !== null && groups.some((group) => group.key === key);
  if (exists(chosen)) return chosen;
  if (exists(sheetGroup)) return sheetGroup;
  return first.key;
};

/** Светофор качества совмещения этажа с эталоном здания. */
export type AlignmentGrade = 'green' | 'yellow' | 'red';

export interface IAlignmentNote {
  /** Короткий текст для строки списка. */
  readonly text: string;
  /** Полное пояснение (подсказка по наведению и нажатию). */
  readonly title: string | null;
  /** Этаж не совмещён: пометка предупреждением. */
  readonly warn: boolean;
  /** Светофор; `null` - оценивать нечего (эталон, один лист). */
  readonly grade: AlignmentGrade | null;
}

const AXES_SHOWN = 4;

/** Пороги светофора: остаток осей (СКО, мм), число согласных осей, наклон шкалы (промилле). */
export const ALIGNMENT_LIMITS = {
  green: { rmsMm: 5, axes: 6, scalePermille: 0.5 },
  yellow: { rmsMm: 25, axes: 3, scalePermille: 2 },
} as const;

/**
 * Светофор совмещения: зелёный - остаток до 5 мм, осей от 6, наклон шкалы до 0,5 ‰; жёлтый - остаток до
 * 25 мм, осей от 3, наклон до 2 ‰; красный - хуже и не совмещённый этаж. Показателя нет (старый ответ,
 * мало осей для наклона) - он не ухудшает оценку. Эталон не оценивается.
 */
export const alignmentGrade = (floor: CadBuilding3dFloorRead): AlignmentGrade | null => {
  if (floor.alignment === 'reference') return null;
  if (floor.alignment === 'none') return 'red';
  const rms = floor.alignment_rms_mm ?? 0;
  const scale = Math.abs(floor.alignment_scale_permille ?? 0);
  const axes = floor.alignment_axes.length;
  const within = (limit: { rmsMm: number; axes: number; scalePermille: number }): boolean =>
    rms <= limit.rmsMm && axes >= limit.axes && scale <= limit.scalePermille;
  if (within(ALIGNMENT_LIMITS.green)) return 'green';
  return within(ALIGNMENT_LIMITS.yellow) ? 'yellow' : 'red';
};

const decimal = (value: number, digits: number): string => value.toFixed(digits).replace('.', ',');

/** Показатели совмещения одной строкой: остаток, оси, наклон шкалы; чего нет в ответе - пропущено. */
export const alignmentQuality = (floor: CadBuilding3dFloorRead): string => {
  const parts: string[] = [];
  const rms = floor.alignment_rms_mm;
  const max = floor.alignment_max_mm;
  if (rms !== undefined && rms !== null) {
    parts.push(`остаток ${decimal(rms, 1)} мм${max !== undefined && max !== null ? ` (до ${decimal(max, 1)})` : ''}`);
  }
  const common = floor.alignment_axes_common;
  parts.push(
    common !== undefined && common !== null
      ? `согласных осей ${floor.alignment_axes.length} из ${common}`
      : `осей ${floor.alignment_axes.length}`,
  );
  const scale = floor.alignment_scale_permille;
  if (scale !== undefined && scale !== null) parts.push(`наклон шкалы ${decimal(scale, 2)} ‰`);
  return parts.join(', ');
};

/**
 * Пометка совмещения этажа. `sheetCount` - число листов здания (без копий типовых листов): здание из
 * одного листа совмещать не с чем - «один лист», а не «совмещён». Этаж, совмещённый по осям, - короткий
 * список осей и светофор; эталон здания из нескольких листов - «эталон».
 */
export const alignmentNote = (
  floor: CadBuilding3dFloorRead,
  sheetCount: number,
): IAlignmentNote | null => {
  if (sheetCount <= 1) return { text: 'один лист', title: 'В здании один лист: совмещать не с чем', warn: false, grade: null };
  if (floor.alignment === 'none') {
    return { text: 'не совмещён по осям', title: floor.alignment_message, warn: true, grade: 'red' };
  }
  if (floor.alignment === 'reference') {
    return { text: 'эталон', title: 'Эталонный этаж: остальные совмещены с ним', warn: false, grade: null };
  }
  if (floor.alignment_axes.length > 0) {
    const shown = floor.alignment_axes.slice(0, AXES_SHOWN).join(', ');
    const rest = floor.alignment_axes.length - AXES_SHOWN;
    return {
      text: `по осям ${shown}${rest > 0 ? ` +${rest}` : ''}`,
      title: `Совмещён по осям: ${floor.alignment_axes.join(', ')}. ${alignmentQuality(floor)}`,
      warn: false,
      grade: alignmentGrade(floor),
    };
  }
  return null;
};

/** Число листов здания: копии типовых листов (`typical_of`) листами не считаются. */
export const sheetCountOf = (floors: readonly CadBuilding3dFloorRead[]): number =>
  floors.filter((floor) => floor.typical_of === undefined || floor.typical_of === null).length;

const byElevationDesc = (a: CadBuilding3dFloorRead, b: CadBuilding3dFloorRead): number =>
  b.base_z_mm - a.base_z_mm || a.label.localeCompare(b.label, 'ru') || a.page_index - b.page_index;

/** Разбивка для списка: с отметкой сверху вниз, без отметки - отдельно. */
export const splitFloors = (floors: readonly CadBuilding3dFloorRead[]): IBuildingList => ({
  known: floors.filter((floor) => floor.elevation_known).sort(byElevationDesc),
  unknown: floors
    .filter((floor) => !floor.elevation_known)
    .sort((a, b) => a.label.localeCompare(b.label, 'ru') || a.page_index - b.page_index),
});

/** Контур без замыкающей точки и без неконечных чисел; меньше трёх вершин - контура нет. */
export const cleanOutline = (outline: readonly (readonly number[])[]): Point2[] | null => {
  const points: Point2[] = [];
  for (const point of outline) {
    const x = point[0];
    const y = point[1];
    if (x === undefined || y === undefined || !Number.isFinite(x) || !Number.isFinite(y)) continue;
    points.push([x, y]);
  }
  const first = points[0];
  const last = points[points.length - 1];
  if (points.length > 1 && first && last && first[0] === last[0] && first[1] === last[1]) points.pop();
  return points.length >= 3 ? points : null;
};

const positive = (value: number): number => (Number.isFinite(value) && value > 0 ? value : 0);

export const buildBuildingPlan = (floors: readonly CadBuilding3dFloorRead[]): IBuildingPlan | null => {
  const raw: { floor: CadBuilding3dFloorRead; outline: Point2[] }[] = [];
  for (const floor of splitFloors(floors).known) {
    const outline = cleanOutline(floor.outline);
    if (outline === null || !Number.isFinite(floor.base_z_mm)) continue;
    raw.push({ floor, outline });
  }
  if (raw.length === 0) return null;

  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const { floor, outline } of raw) {
    for (const [x, y] of outline) {
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
    minZ = Math.min(minZ, floor.base_z_mm - positive(floor.slab_thickness_mm));
    maxZ = Math.max(maxZ, floor.base_z_mm + positive(floor.floor_height_mm));
  }
  const center = { x: (minX + maxX) / 2, y: (minY + maxY) / 2, z: (minZ + maxZ) / 2 };

  const specs: IBuildingFloorSpec[] = raw.map(({ floor, outline }) => ({
    key: floorKey(floor),
    floor,
    shell: outline.map(([x, y]): Point2 => [(x - center.x) / MM_IN_M, (y - center.y) / MM_IN_M]),
    slabBottom: (floor.base_z_mm - positive(floor.slab_thickness_mm) - center.z) / MM_IN_M,
    slabTop: (floor.base_z_mm - center.z) / MM_IN_M,
    volumeTop: (floor.base_z_mm + positive(floor.floor_height_mm) - center.z) / MM_IN_M,
  }));

  return {
    floors: specs,
    center,
    size: {
      width: (maxX - minX) / MM_IN_M,
      depth: (maxY - minY) / MM_IN_M,
      height: (maxZ - minZ) / MM_IN_M,
    },
  };
};
