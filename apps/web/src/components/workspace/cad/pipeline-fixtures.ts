import type {
  CadPipelineSheetRead,
  CadPipelineStageRead,
  CadPipelineViewRead,
} from '@quantor/api-client';

import { sheetSteps, sheetSummary } from '@/lib/cad/pipeline';

import type { IWorkspaceCadPipeline } from './useWorkspaceCadPipeline';

/** Данные конвейера для тестов рабочей области. */

export const stage = (overrides: Partial<CadPipelineStageRead> = {}): CadPipelineStageRead => ({
  job_id: 'job-1',
  job_type: 'cad_pdf_convert',
  status: 'succeeded',
  progress: 1,
  stage: null,
  result_status: 'completed_requires_review',
  error_code: null,
  created_at: '2026-11-11T10:00:00Z',
  finished_at: '2026-11-11T10:01:00Z',
  ...overrides,
});

export const pipelineView = (overrides: Partial<CadPipelineViewRead> = {}): CadPipelineViewRead => ({
  page: 2,
  view: 0,
  has_dxf: true,
  approved: false,
  routes_accepted: false,
  zones_count: 3,
  walls: stage({ job_id: 'w1', job_type: 'cad_walls' }),
  zones: stage({ job_id: 'z1', job_type: 'cad_zones' }),
  routes: null,
  floor3d: null,
  ...overrides,
});

export const pipelineSheet = (
  overrides: Partial<CadPipelineSheetRead> = {},
): CadPipelineSheetRead => ({
  page_index: 2,
  page_label: null,
  title: null,
  is_plan: true,
  scale_source: 'calibration',
  calibrated: true,
  convert: stage(),
  views: [pipelineView()],
  ...overrides,
});

/** Результат хука для листа: шаги и итог считаются теми же функциями, что в хуке. */
export const pipelineOfSheet = (
  sheet: CadPipelineSheetRead | null,
  overrides: Partial<IWorkspaceCadPipeline> = {},
): IWorkspaceCadPipeline => ({
  sheet,
  sheets: sheet ? [sheet] : [],
  steps: sheet
    ? sheetSteps(sheet)
    : sheetSteps(
        pipelineSheet({ page_label: null, calibrated: false, convert: null, views: [], scale_source: null }),
      ),
  summary: sheet ? sheetSummary(sheet) : null,
  isPending: false,
  isError: false,
  refetch: () => undefined,
  startAutoZones: () => Promise.resolve(),
  startingZones: false,
  zonesError: null,
  ...overrides,
});
