import type { CadHeightsRead, CadSheetLevelsWrite } from '@quantor/api-client';

/**
 * Высоты 3D-вида: подписи источников и переопределения листа (ADR-0039 п. 5).
 * Сервер заменяет высоты листа целиком, поэтому запись всегда несёт все шесть полей.
 */

type Source = CadHeightsRead['floor_elevation_source'];

const SOURCE_TEXT: Readonly<Record<NonNullable<Source>, string>> = {
  observed: 'чертёж',
  derived: 'выведено',
  manual: 'ввод',
  assumption: 'допущение',
};

export const heightSourceText = (source: Source): string =>
  source === null ? 'не определено' : SOURCE_TEXT[source];

export type SheetLevelKey = keyof CadSheetLevelsWrite;

export interface ISheetLevelSpec {
  readonly key: SheetLevelKey;
  readonly label: string;
  readonly range: readonly [number, number];
}

export const SHEET_LEVEL_SPECS: readonly ISheetLevelSpec[] = [
  { key: 'floor_elevation_mm', label: 'Отметка этажа (верх плиты), мм', range: [-100000, 500000] },
  { key: 'floor_height_mm', label: 'Высота этажа, мм', range: [2000, 6000] },
  { key: 'slab_thickness_mm', label: 'Толщина плиты листа, мм', range: [100, 1000] },
  { key: 'door_height_mm', label: 'Высота двери, мм', range: [1500, 3500] },
  { key: 'window_sill_mm', label: 'Подоконник, мм', range: [0, 5999] },
  {
    key: 'window_head_mm',
    label: 'Высота окна (верх от чистого пола), мм',
    range: [1, 6000],
  },
];

/**
 * Текущие переопределения листа по ответу вида. Ввод человека - источник `manual`; толщина плиты из
 * разреза проекта тоже `manual`, но у неё есть лист разреза - это не переопределение листа.
 */
export const sheetOverridesOf = (heights: CadHeightsRead): Record<SheetLevelKey, number | null> => {
  const manual = (value: number | null, source: Source): number | null =>
    source === 'manual' ? value : null;
  const slabIsProject =
    heights.slab_thickness_sheet_ref !== null && heights.slab_thickness_sheet_ref !== undefined;
  return {
    floor_elevation_mm: manual(heights.floor_elevation_mm, heights.floor_elevation_source),
    floor_height_mm: manual(heights.floor_height.value_mm, heights.floor_height.source),
    slab_thickness_mm: slabIsProject
      ? null
      : manual(heights.slab_thickness.value_mm, heights.slab_thickness.source),
    door_height_mm: manual(heights.door_height.value_mm, heights.door_height.source),
    window_sill_mm: manual(heights.window_sill.value_mm, heights.window_sill.source),
    window_head_mm: manual(heights.window_head.value_mm, heights.window_head.source),
  };
};

/** Текст поля -> число; пусто = `null` (снять переопределение); `undefined` - ошибка ввода. */
export const parseLevel = (raw: string, [min, max]: readonly [number, number]): number | null | undefined => {
  const text = raw.trim();
  if (text === '') return null;
  const value = Number(text.replace(',', '.'));
  return Number.isInteger(value) && value >= min && value <= max ? value : undefined;
};

export type LevelsDraft = Readonly<Record<SheetLevelKey, string>>;

export const draftOf = (overrides: Record<SheetLevelKey, number | null>): LevelsDraft => ({
  floor_elevation_mm: overrides.floor_elevation_mm === null ? '' : String(overrides.floor_elevation_mm),
  floor_height_mm: overrides.floor_height_mm === null ? '' : String(overrides.floor_height_mm),
  slab_thickness_mm: overrides.slab_thickness_mm === null ? '' : String(overrides.slab_thickness_mm),
  door_height_mm: overrides.door_height_mm === null ? '' : String(overrides.door_height_mm),
  window_sill_mm: overrides.window_sill_mm === null ? '' : String(overrides.window_sill_mm),
  window_head_mm: overrides.window_head_mm === null ? '' : String(overrides.window_head_mm),
});

/** Тело PUT высот листа из черновика; ошибка - текст для пользователя. */
export const writeOfDraft = (
  draft: LevelsDraft,
): { readonly write: CadSheetLevelsWrite } | { readonly error: string } => {
  const write: CadSheetLevelsWrite = {};
  for (const spec of SHEET_LEVEL_SPECS) {
    const value = parseLevel(draft[spec.key], spec.range);
    if (value === undefined) {
      return { error: `${spec.label}: целое число от ${spec.range[0]} до ${spec.range[1]}.` };
    }
    write[spec.key] = value;
  }
  // Подоконник и верх окна - пара: оба или ни одного, подоконник ниже верха (как на сервере).
  const sill = write.window_sill_mm ?? null;
  const head = write.window_head_mm ?? null;
  if ((sill === null) !== (head === null)) {
    return { error: 'Подоконник и высота окна задаются вместе: заполните оба поля.' };
  }
  if (sill !== null && head !== null && sill >= head) {
    return { error: 'Подоконник должен быть ниже верха окна.' };
  }
  return { write };
};

/** Секция листа по заголовку плана: корпус и секция обе заданы; иначе `null` (кнопка недоступна). */
export const sectionLabelOf = (
  title: { readonly corps?: string | null; readonly section?: string | null } | null | undefined,
): string | null => {
  const corps = title?.corps?.trim() ?? '';
  const section = title?.section?.trim() ?? '';
  return corps !== '' && section !== '' ? `корп. ${corps}, сек. ${section}` : null;
};
