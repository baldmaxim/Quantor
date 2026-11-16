import type { CadFloor3dRead, CadFloor3dWindowRead, CadHeightsRead } from '@quantor/api-client';

/** Синтетические данные 3D-вида для тестов: этаж 10 x 6 м (мм DXF), отметка 3000, плита 200. */

export const heightsFixture = (patch: Partial<CadHeightsRead> = {}): CadHeightsRead => ({
  floor_elevation_mm: 3000,
  floor_elevation_source: 'observed',
  floor_height: { value_mm: 3000, source: 'derived', default_mm: 2800 },
  slab_thickness: { value_mm: 200, source: 'assumption', default_mm: 200 },
  door_height: { value_mm: 2100, source: 'assumption', default_mm: 2100 },
  slab_thickness_sheet_ref: null,
  wall_height_mm: 2800,
  wall_height_source: 'derived',
  evidence: null,
  message: null,
  ...patch,
});

const rect = (x0: number, y0: number, x1: number, y1: number): number[][] => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
];

export const floor3dFixture = (patch: Partial<CadFloor3dRead> = {}): CadFloor3dRead => ({
  units: 'mm',
  generator: 'cad_walls',
  heights: heightsFixture(),
  base_z_mm: 3000,
  elevation_known: true,
  slab: { shell: rect(0, 0, 10000, 6000), z_bottom_mm: 2800, z_top_mm: 3000, area_m2: 60 },
  slab_holes: [
    { key: 'h1', shell: rect(1000, 1000, 2000, 2000), area_m2: 1, state: 'candidate' },
    { key: 'h2', shell: rect(3000, 1000, 4000, 2000), area_m2: 1, state: 'enabled' },
    { key: 'h3', shell: rect(5000, 1000, 6000, 2000), area_m2: 1, state: 'disabled' },
  ],
  walls: [
    {
      construction_key: 'w1',
      kind: 'masonry',
      family: 'masonry',
      thickness_nominal_mm: 200,
      shell: rect(0, 0, 10000, 200),
      holes: [],
      z_bottom_mm: 3000,
      z_top_mm: 5800,
    },
    {
      construction_key: 'w2',
      kind: 'monolith_pylon',
      family: 'monolith',
      thickness_nominal_mm: 300,
      shell: rect(0, 0, 300, 300),
      holes: [],
      z_bottom_mm: 3000,
      z_top_mm: null,
    },
  ],
  lintels: [
    {
      opening_id: 'o1',
      kind: 'door',
      shell: rect(4000, 0, 4900, 200),
      z_bottom_mm: 5100,
      z_top_mm: 5800,
      door_height_mm: 2100,
      door_height_source: 'assumption',
    },
  ],
  doors: [
    {
      opening_id: 'o1',
      shell: rect(4000, 0, 4900, 200),
      z_bottom_mm: 3000,
      z_top_mm: 5100,
      door_height_mm: 2100,
      door_height_source: 'assumption',
    },
    {
      opening_id: 'o2',
      shell: rect(6000, 0, 6900, 200),
      z_bottom_mm: 3000,
      z_top_mm: 5000,
      door_height_mm: 2000,
      door_height_source: 'observed',
    },
  ],
  bbox: [0, 0, 10000, 6000],
  warnings: [],
  ...patch,
});

/** Окно по фасаду: подоконная часть 3000-3900, стекло 3900-5000 (мм), подоконник 900, верх 2000. */
export const windowFixture = (patch: Partial<CadFloor3dWindowRead> = {}): CadFloor3dWindowRead => ({
  opening_id: 'win1',
  host_id: 'w1',
  shell: rect(1000, 0, 2200, 200),
  sill_z_bottom_mm: 3000,
  sill_z_top_mm: 3900,
  glass_z_top_mm: 5000,
  sill_mm: 900,
  head_mm: 2000,
  accepted: true,
  facade_view_key: 'north',
  facade_page_index: 2,
  facade_revision_id: 'rev1',
  facade_title: 'Фасад 1-12',
  axes_checked: true,
  ...patch,
});
