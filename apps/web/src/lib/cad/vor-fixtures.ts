import type {
  CadVorCoverageGroupRead,
  CadVorCoverageRead,
  CadVorDocumentRead,
  CadVorItemRead,
} from '@quantor/api-client';

/** Синтетические данные ВОР для тестов. */

export const vorItem = (patch: Partial<CadVorItemRead> & { id: string }): CadVorItemRead => ({
  code: null,
  document_id: 'd1',
  kind_hint: null,
  name: 'Кладка стен',
  quantity: 120.5,
  row_no: 1,
  section: null,
  sheet: 'ВОР',
  thickness_hint_mm: null,
  unit: 'м3',
  ...patch,
});

export const vorDocument = (patch: Partial<CadVorDocumentRead> = {}): CadVorDocumentRead => ({
  columns: [],
  created_at: '2026-11-10T09:00:00Z',
  file_name: 'ВОР.xlsx',
  header_row: 1,
  id: 'd1',
  project_id: 'p1',
  rows_count: 42,
  sha256: 'x',
  sheet_names: ['ВОР'],
  size: 1000,
  uploaded_by: null,
  ...patch,
});

export const LINKED_ITEM = vorItem({
  id: 'i1',
  code: '2.1',
  name: 'Кладка газобетон 100 мм',
  quantity: 55,
  unit: 'м3',
});

export const coverageGroup = (
  patch: Partial<CadVorCoverageGroupRead> = {},
): CadVorCoverageGroupRead => ({
  group_key: 'masonry|100|',
  items: [],
  kind: 'masonry',
  material: null,
  status: 'not_in_vor',
  thickness_mm: 100,
  ...patch,
});

export const coverage = (patch: Partial<CadVorCoverageRead> = {}): CadVorCoverageRead => ({
  groups: [
    coverageGroup({ group_key: 'masonry|120|', thickness_mm: 120, status: 'linked', items: [LINKED_ITEM] }),
    coverageGroup(),
  ],
  has_vor: true,
  job_id: 'j1',
  not_in_vor_keys: ['a'],
  page_index: 0,
  thickness_not_in_vor: ['masonry|100|'],
  view: 1,
  vor_thicknesses: [120, 200],
  ...patch,
});
