import type {
  CadFinishLayer,
  CadFinishSheetRead,
  CadFinishTemplateRead,
  CadFinishWallsBreakdownRead,
  CadFinishZoneRead,
} from '@quantor/api-client';

/** Шаблон отделки для тестов: черновая МОП с одним слоем пола. */
export const templateFixture = (
  patch: Partial<CadFinishTemplateRead> = {},
): CadFinishTemplateRead => ({
  id: 't1',
  project_id: 'p1',
  name: 'Черновая МОП',
  room_types: ['corridor'],
  wall_height_mm: null,
  floor_layers: [{ work: 'Стяжка', coats: 1 } satisfies CadFinishLayer],
  wall_layers: [],
  ceiling_layers: [],
  walls_include_reveals: false,
  created_at: '2026-11-11T00:00:00Z',
  updated_at: '2026-11-11T00:00:00Z',
  ...patch,
});

/** Разбивка стен: привязано, все участки определены. */
export const wallsBreakdownFixture = (
  patch: Partial<CadFinishWallsBreakdownRead> = {},
): CadFinishWallsBreakdownRead => ({
  linked: true,
  monolith_m: 6.5,
  masonry_m: 4,
  gkl_m: 1.5,
  door_m: 2,
  gap_m: 0.8,
  open_m: 0.3,
  area_by_base: { monolith: 17.55, masonry: 10.8, gkl: 4.05 },
  door_over_area_m2: 0.9,
  reveal_m: 3.6,
  reveal_area_m2: 0.54,
  ...patch,
});

/** Зона ведомости: определённые площади, один слой стяжки пола. */
export const finishZoneFixture = (patch: Partial<CadFinishZoneRead> = {}): CadFinishZoneRead => ({
  zone_id: 'z1',
  name: 'Коридор',
  apartment_no: null,
  room_mark: null,
  kind: 'room_mop',
  room_type: 'corridor',
  template_id: 't1',
  template_source: 'by_type',
  floor_area_m2: 12.5,
  ceiling_area_m2: 12.5,
  perimeter_m: 14,
  wall_height_mm: 2700,
  wall_height_source: 'levels',
  wall_area_m2: 37.8,
  walls_breakdown: wallsBreakdownFixture(),
  layers: [
    {
      surface: 'floor',
      work: 'Стяжка',
      material: 'Смесь М150',
      coats: 1,
      thickness_mm: 50,
      bases: null,
      area_m2: 12.5,
      material_qty: 1125,
      material_unit: 'кг',
    },
  ],
  ...patch,
});

export const sheetFixture = (patch: Partial<CadFinishSheetRead> = {}): CadFinishSheetRead => ({
  revision_id: 'r1',
  page_index: 0,
  zones: [finishZoneFixture()],
  totals: [
    {
      surface: 'floor',
      work: 'Стяжка',
      material: 'Смесь М150',
      material_unit: 'кг',
      area_m2: 12.5,
      material_qty: 1125,
      zone_count: 1,
    },
  ],
  by_room_type: [
    {
      room_type: 'corridor',
      zone_count: 1,
      floor_area_m2: 12.5,
      wall_area_m2: 37.8,
      ceiling_area_m2: 12.5,
    },
  ],
  warnings: [],
  ...patch,
});
