import type { CadZoneRead } from '@quantor/api-client';

import { ZONE_CATEGORIES, type ZoneCategory } from './zone-categories';
import type { IZoneLabelOptions } from './zone-labels';

/**
 * Настройки вида зон листа: окраска, скрытые категории, подписи. Запоминаются в localStorage
 * (недоступен или испорчен - умолчание).
 */

export type ZoneColorMode = 'category' | 'apartment';

export interface IZoneView {
  readonly colorMode: ZoneColorMode;
  readonly hidden: ReadonlySet<ZoneCategory>;
  /** Подписи зон показываются вообще. */
  readonly labelsOn: boolean;
  readonly labels: IZoneLabelOptions;
}

export const DEFAULT_ZONE_VIEW: IZoneView = {
  colorMode: 'category',
  hidden: new Set(),
  labelsOn: true,
  labels: { apartment: false, mark: true, name: false, area: true },
};

export const ZONE_VIEW_KEY = 'quantor.cad.zoneView';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const flag = (value: unknown, fallback: boolean): boolean =>
  typeof value === 'boolean' ? value : fallback;

export const parseZoneView = (raw: string | null): IZoneView => {
  if (raw === null) return DEFAULT_ZONE_VIEW;
  try {
    const data: unknown = JSON.parse(raw);
    if (!isRecord(data)) return DEFAULT_ZONE_VIEW;
    const labels = isRecord(data.labels) ? data.labels : {};
    const hidden = Array.isArray(data.hidden)
      ? ZONE_CATEGORIES.filter((category) => (data.hidden as unknown[]).includes(category))
      : [];
    const defaults = DEFAULT_ZONE_VIEW.labels;
    return {
      colorMode: data.colorMode === 'apartment' ? 'apartment' : 'category',
      hidden: new Set(hidden),
      labelsOn: flag(data.labelsOn, DEFAULT_ZONE_VIEW.labelsOn),
      labels: {
        apartment: flag(labels.apartment, defaults.apartment),
        mark: flag(labels.mark, defaults.mark),
        name: flag(labels.name, defaults.name),
        area: flag(labels.area, defaults.area),
      },
    };
  } catch {
    return DEFAULT_ZONE_VIEW;
  }
};

export const readStoredZoneView = (): IZoneView => {
  try {
    return parseZoneView(window.localStorage.getItem(ZONE_VIEW_KEY));
  } catch {
    return DEFAULT_ZONE_VIEW;
  }
};

export const writeStoredZoneView = (view: IZoneView): void => {
  try {
    window.localStorage.setItem(
      ZONE_VIEW_KEY,
      JSON.stringify({ ...view, hidden: [...view.hidden] }),
    );
  } catch {
    // хранилище недоступно - вид живёт до перезагрузки
  }
};

/** Число цветов палитры «по квартирам». */
export const APARTMENT_PALETTE_SIZE = 8;

/**
 * Номер цвета палитры для каждой квартиры листа: по порядку уникальных номеров (естественная
 * сортировка), циклически. Помещения без номера в карту не попадают.
 */
export const apartmentColorIndex = (
  zones: readonly Pick<CadZoneRead, 'kind' | 'apartment_no'>[],
): ReadonlyMap<string, number> => {
  const numbers = new Set<string>();
  for (const zone of zones) {
    if (zone.kind === 'room_apartment' && zone.apartment_no !== null)
      numbers.add(zone.apartment_no);
  }
  const sorted = [...numbers].sort((first, second) =>
    first.localeCompare(second, 'ru', { numeric: true }),
  );
  return new Map(sorted.map((number, index) => [number, index % APARTMENT_PALETTE_SIZE]));
};
