import type { CadSheetFloorTitle } from '@quantor/api-client';

/**
 * Подпись листа этажом по заголовку плана из PDF: корпус, секция, этаж. Заголовок есть только у
 * листов с успешным «Конструкции CAD»; без него остаётся прежняя подпись листа (`fallback`).
 */

export type FloorTitleLike = CadSheetFloorTitle | null | undefined;

/** Этажи: один - «14», подряд - «2–5», иначе перечисление «2, 4». Этажей нет - `null`. */
export const floorsText = (floors: readonly string[] | undefined): string | null => {
  if (!floors || floors.length === 0) return null;
  const numbers = floors.map((floor) => (/^-?\d+$/.test(floor) ? Number(floor) : Number.NaN));
  if (floors.length > 1 && numbers.every((n) => !Number.isNaN(n))) {
    const sorted = [...numbers].sort((a, b) => a - b);
    const first = sorted[0] ?? 0;
    const last = sorted[sorted.length - 1] ?? 0;
    if (last - first === sorted.length - 1 && new Set(sorted).size === sorted.length) {
      return `${first}–${last}`;
    }
  }
  return floors.join(', ');
};

/** Короткая подпись «К9 · С3 · 14 эт.»; в заголовке нет ни корпуса, ни секции, ни этажа - `fallback`. */
export const formatFloorTitle = (title: FloorTitleLike, fallback: string): string => {
  if (!title) return fallback;
  const parts: string[] = [];
  if (title.corps) parts.push(`К${title.corps}`);
  if (title.section) parts.push(`С${title.section}`);
  const floors = floorsText(title.floors);
  if (floors !== null) parts.push(`${floors} эт.`);
  return parts.length > 0 ? parts.join(' · ') : fallback;
};

/** Полная форма для подсказки: «Корпус 9, секция 3, 14 этаж»; пусто - `null`. */
export const formatFloorTitleFull = (title: FloorTitleLike): string | null => {
  if (!title) return null;
  const parts: string[] = [];
  if (title.corps) parts.push(`Корпус ${title.corps}`);
  if (title.section) parts.push(`секция ${title.section}`);
  const floors = floorsText(title.floors);
  if (floors !== null) parts.push(`${floors} ${(title.floors?.length ?? 0) > 1 ? 'этажи' : 'этаж'}`);
  return parts.length > 0 ? parts.join(', ') : null;
};

const TRANSLIT: Readonly<Record<string, string>> = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y',
  к: 'k', л: 'l', м: 'm', н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f',
  х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch', ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
};

/** Фрагмент имени файла: латиница, цифры и «-»; кириллица транслитерируется, остальное отбрасывается. */
const fileToken = (value: string): string =>
  Array.from(value.toLowerCase())
    .map((char) => TRANSLIT[char] ?? char)
    .join('')
    .replace(/[^a-z0-9-]/g, '');

/**
 * Имя файла по заголовку: `floor3d_K9_S3_14.dxf` (латиница, без пробелов). Диапазон этажей -
 * «2-5», перечисление - «2_4». В заголовке нет ничего пригодного для имени - `null`.
 */
export const floorTitleFileName = (title: FloorTitleLike): string | null => {
  if (!title) return null;
  const parts: string[] = [];
  const corps = fileToken(title.corps ?? '');
  const section = fileToken(title.section ?? '');
  if (corps) parts.push(`K${corps.toUpperCase()}`);
  if (section) parts.push(`S${section.toUpperCase()}`);
  const floors = floorsText(title.floors);
  if (floors !== null) {
    const token = floors
      .split(', ')
      .map((floor) => fileToken(floor.replace('–', '-')))
      .filter(Boolean)
      .join('_');
    if (token) parts.push(token);
  }
  return parts.length > 0 ? `floor3d_${parts.join('_')}.dxf` : null;
};
