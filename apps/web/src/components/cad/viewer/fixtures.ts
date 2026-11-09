import type {
  CadFrameRead,
  CadJobRead,
  CadPreviewRead,
  CadScaleRead,
  CadViewDiagnosticsRead,
} from '@quantor/api-client';

/** Данные для тестов панели вида. Только синтетика. */

export const JOB_ID = '11111111-1111-4111-8111-111111111111';
export const SHA = 'a'.repeat(64);

export const FRAME_OK: CadFrameRead = {
  confirmed: true,
  reason: null,
  units: 'mm',
  origin_pt: [37.5, 700],
  mm_per_pdf_point: 35.28,
};

export const FRAME_NO: CadFrameRead = {
  confirmed: false,
  reason: 'Масштаб не подтверждён размерной проверкой: кадр координат не установлен.',
  units: null,
  origin_pt: null,
  mm_per_pdf_point: null,
};

export const scale = (patch: Partial<CadScaleRead> = {}): CadScaleRead => ({
  status: 'dimension_checks_passed',
  passed: true,
  method: 'dimension_chains',
  mm_per_pdf_point: 35.28,
  scale_denominator: 100,
  printed_scale_labels: [100],
  printed_scale_consistent: true,
  fit_controls: 4,
  heldout_controls: 2,
  fit_chains: 4,
  heldout_chains: 2,
  fit_and_holdout_chains_disjoint: true,
  independent_axes: true,
  anchored_conflicts: 0,
  unassociated_numeric_labels: 0,
  release_allowed: true,
  hold_reasons: [],
  context_crop_pt: [0, 0, 500, 400],
  controls: [
    {
      chain_id: 7,
      role: 'fit',
      label_mm: 3000,
      length_pt: 85,
      fitted_measured_mm: 2999.5,
      residual_mm: -0.5,
      tolerance_mm: 5,
      within_tolerance: true,
      axis_angle_deg: 0,
      endpoints_pt: [],
    },
    {
      chain_id: null,
      role: 'holdout',
      label_mm: null,
      length_pt: null,
      fitted_measured_mm: null,
      residual_mm: null,
      tolerance_mm: null,
      within_tolerance: false,
      axis_angle_deg: null,
      endpoints_pt: [],
    },
  ],
  ...patch,
});

export const diagnostics = (
  patch: Partial<CadViewDiagnosticsRead> = {},
): CadViewDiagnosticsRead => ({
  job_id: JOB_ID,
  attempt: 1,
  page_index: 0,
  legacy_pdf_page: 1,
  view: 1,
  status: 'needs_review',
  scale_status: 'dimension_checks_passed',
  result_status: 'completed_requires_review',
  files: [
    { name: 'views/p001_v01/plan_candidates.dxf', sha256: SHA, size: 2048 },
    { name: 'views/p001_v01/scale.json', sha256: 'b'.repeat(64), size: 512 },
  ],
  dxf: { name: 'views/p001_v01/plan_candidates.dxf', sha256: SHA, size: 2048 },
  preview_available: true,
  scale: scale(),
  frame: FRAME_OK,
  checks: null,
  review_required: true,
  engineering_acceptance: 'not_accepted',
  ...patch,
});

export const preview = (patch: Partial<CadPreviewRead> = {}): CadPreviewRead => ({
  job_id: JOB_ID,
  attempt: 1,
  page_index: 0,
  view: 1,
  units: 'mm',
  dxf_sha256: SHA,
  layers: ['WALLS', 'DOORS'],
  paths: [
    { layer: 0, closed: false, fill: false, points: [0, 0, 1000, 0, 1000, 1000] },
    { layer: 1, closed: true, fill: true, points: [0, 0, 100, 0, 100, 100] },
  ],
  point_count: 6,
  truncated: false,
  flatten_mm: 0.5,
  bbox: [0, 0, 1000, 1000],
  frame: FRAME_OK,
  ...patch,
});

export const job = (patch: Partial<CadJobRead> = {}): CadJobRead =>
  ({
    job_id: JOB_ID,
    revision_id: '22222222-2222-4222-8222-222222222222',
    result_attempt: 1,
    attempt: 1,
    ...patch,
  }) as CadJobRead;
