import type { SheetPassportExtractSummary, SheetPassportOut } from '@quantor/api-client';

/** Строка паспорта листа для тестов; поля переопределяются точечно. */
export const passportRow = (patch: Partial<SheetPassportOut> = {}): SheetPassportOut => ({
  id: 'sp-1',
  project_id: 'p-1',
  revision_id: 'r-1',
  document_id: 'd-1',
  document_name: 'АР.pdf',
  page_index: 2,
  file_name: 'АР.pdf',
  section_mark: 'АР',
  sheet_kind: 'floor_plan',
  stage: 'П',
  building: '9',
  section: '3',
  level_from: '1',
  level_to: '14',
  level_from_ordinal: 1,
  level_to_ordinal: 14,
  elevation_m: 3.6,
  code: 'АР-03',
  sheet_number: '3',
  title: 'План типового этажа',
  status: 'candidate',
  evidence: {
    section_mark: { source: 'stamp', snippet: 'Раздел АР' },
    title: { source: 'title', snippet: 'План типового этажа' },
  },
  versions: {},
  confirmed_by: null,
  confirmed_at: null,
  created_at: '2026-11-11T10:00:00Z',
  updated_at: '2026-11-11T10:00:00Z',
  ...patch,
});

/** Итог разбора листов для тестов панели; поля переопределяются точечно. */
export const extractSummary = (
  patch: Partial<SheetPassportExtractSummary> = {},
): SheetPassportExtractSummary => ({
  job_id: 'j-1',
  status: 'succeeded',
  progress: 1,
  stage: 'passport',
  error_code: null,
  created_at: '2026-11-11T10:00:00Z',
  finished_at: '2026-11-11T10:01:00Z',
  files_total: 3,
  files_parsed: 2,
  pages: 7,
  created: 5,
  updated: 2,
  skipped_reviewed: 1,
  error_count: 0,
  errors: [],
  versions: {},
  ...patch,
});
