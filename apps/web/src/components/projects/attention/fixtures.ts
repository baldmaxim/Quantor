import type {
  CadPipelineSheetRead,
  DocCandidateOut,
  DocQuestionOut,
  DocQuestionsOut,
} from '@quantor/api-client';

/** Фикстуры тестов очереди вопросов. */

export const candidate = (patch: Partial<DocCandidateOut> = {}): DocCandidateOut => ({
  id: 'c-1',
  question_code: 'clear_height',
  value: { kind: 'length_mm', display: '2700', numbers: [2700], qualifier: null, code: null },
  value_text: '2700 мм',
  quote: 'Высота помещений в свету 2700 мм',
  revision_id: 'r-1',
  page_index: 4,
  page_label: null,
  file_name: 'АР_ПЗ.pdf',
  building: '9',
  section: null,
  level: null,
  score: 40,
  occurrences: 2,
  status: 'candidate',
  versions: {},
  created_at: '2026-11-12T10:00:00Z',
  ...patch,
});

export const question = (patch: Partial<DocQuestionOut> = {}): DocQuestionOut => ({
  code: 'clear_height',
  title: 'Высота помещения в свету',
  receiver_param: 'clear_height_mm',
  value_kind: 'length_mm',
  min_mm: 2000,
  max_mm: 6000,
  options: [],
  assumption: null,
  candidates: [],
  answers: [],
  ...patch,
});

export const questionsOut = (
  questions: DocQuestionOut[],
  status: 'succeeded' | 'running' | null = 'succeeded',
): DocQuestionsOut => ({
  catalog_version: 'v1',
  questions,
  last_search:
    status === null
      ? null
      : {
          job_id: 'j-1',
          status,
          progress: 1,
          stage: null,
          error_code: null,
          created_at: '2026-11-12T10:00:00Z',
          finished_at: '2026-11-12T10:01:00Z',
          questions_found: 1,
          candidates: 1,
          revisions_total: 1,
          revisions_scanned: 1,
          revisions_no_text: 0,
          no_text_files: [],
          revisions_unreadable: 0,
          unreadable_files: [],
          versions: {},
        },
});

export const scaleFailedSheet = (pageIndex: number): CadPipelineSheetRead => ({
  page_index: pageIndex,
  page_label: null,
  title: null,
  is_plan: true,
  scale_source: null,
  calibrated: false,
  convert: {
    job_id: 'job-1',
    job_type: 'cad_pdf_convert',
    status: 'failed',
    progress: 1,
    stage: null,
    result_status: null,
    error_code: 'CAD_AUTO_SCALE_UNCONFIRMED',
    created_at: '2026-11-12T10:00:00Z',
    finished_at: '2026-11-12T10:01:00Z',
  },
  views: [],
});
