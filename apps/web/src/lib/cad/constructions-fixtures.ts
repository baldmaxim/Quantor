import type {
  CadConstructionRead,
  CadConstructionsRead,
  CadOpeningRead,
} from '@quantor/api-client';

/** Синтетические конструкции для тестов: полигоны в мм DXF. */

export const construction = (
  patch: Partial<CadConstructionRead> & { id: string },
): CadConstructionRead => ({
  material: {
    value: patch.props?.material ?? null,
    source: patch.props?.material ? 'manual' : null,
    hint_status: null,
    evidence: [],
  },
  accepted: false,
  area_plan_m2: 0.6,
  bbox: [0, 0, 5000, 120],
  centroid: [2500, 60],
  computed: {
    height_mm: 2700,
    length_m: 5,
    sources: { door_height: null, height: 'derived', thickness: 'observed' },
    status: 'ok',
    thickness_mm: 120,
    volume_m3: 1.62,
    wall_area_m2: 13.5,
    warnings: [],
  },
  kind: 'masonry',
  polygon: {
    shell: [
      [0, 0],
      [5000, 0],
      [5000, 120],
      [0, 120],
    ],
    holes: [],
  },
  props: {},
  source_layers: ['WALL'],
  thickness_measured_mm: 119.6,
  thickness_nominal_mm: 120,
  thickness_status: 'matched',
  ...patch,
});

export const opening = (patch: Partial<CadOpeningRead> & { id: string }): CadOpeningRead => ({
  adjacent_ids: [],
  block_name: null,
  center: [0, 0],
  handle: null,
  host_id: null,
  kind: 'door',
  status: 'ok',
  thickness_mm: 120,
  width_mm: 900,
  width_source: 'block',
  ...patch,
});

export const constructionsRead = (
  patch: Partial<CadConstructionsRead> = {},
): CadConstructionsRead => ({
  constructions: [],
  dxf_sha256: 'd',
  generator: 'cad_walls',
  heights: {
    door_height: { default_mm: 2100, source: 'assumption', value_mm: 2100 },
    evidence: null,
    floor_elevation_mm: 0,
    floor_elevation_source: 'observed',
    floor_height: { default_mm: 3000, source: 'derived', value_mm: 3000 },
    message: null,
    slab_thickness: { default_mm: 200, source: 'assumption', value_mm: 200 },
    wall_height_mm: 2800,
    wall_height_source: 'derived',
  },
  job_id: 'parent',
  openings: [],
  page_index: 0,
  params_sha256: 'p',
  params_version: 'v1',
  sheet_levels: { door_height_mm: null, floor_height_mm: null, slab_thickness_mm: null },
  summary: {
    door_openings_without_host: 0,
    height_missing_count: 0,
    thickness_check_count: 0,
    total_count: 0,
    unaccounted_gap_openings: 0,
  },
  totals: [],
  view: 0,
  walls_job_id: 'w1',
  walls_sha256: 'w',
  warnings: [],
  ...patch,
});
