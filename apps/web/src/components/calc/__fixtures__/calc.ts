import type {
  CalcFactRead,
  CalcFactTypeRead,
  CalcInputFactRead,
  CalcReadinessRowRead,
} from '@quantor/api-client';

/** Фабрики данных для тестов экрана «Исходные данные». Значения синтетические. */

export const factType = (overrides: Partial<CalcFactTypeRead> = {}): CalcFactTypeRead => ({
  key: 'floor.apartments_count',
  title: 'Квартир на этаже',
  description: 'Число квартир на этаже.',
  value_kind: 'COUNT',
  unit: 'apartment',
  unit_title: 'кв.',
  required_subject: ['building', 'floor'],
  allowed_subject: ['building', 'floor', 'section'],
  options: [],
  qualifier_options: [],
  customer_vor_admissible: false,
  ...overrides,
});

export const fact = (overrides: Partial<CalcFactRead> = {}): CalcFactRead => ({
  id: '11111111-1111-4111-8111-111111111111',
  project_id: '22222222-2222-4222-8222-222222222222',
  source_id: '33333333-3333-4333-8333-333333333333',
  source_class: 'APARTMENT_SCHEDULE',
  fact_type: 'floor.apartments_count',
  subject: { building: '1', floor: '2..24' },
  subject_key: 'building=1|floor=2..24',
  fact_key: 'floor.apartments_count@building=1|floor=2..24',
  value: { kind: 'COUNT', value: 9, unit: 'apartment' },
  stated_value: { kind: 'COUNT', value: 9, unit: null },
  method: 'TABLE_COUNTED',
  confidence: 'MEDIUM',
  review_status: 'UNREVIEWED',
  reviewed_by: null,
  reviewed_at: null,
  review_comment: null,
  status: 'ACTIVE',
  version: 1,
  supersedes_id: null,
  calculation_eligible: true,
  withdrawn_reason: null,
  withdrawn_at: null,
  note: 'Подсчитаны строки «Квартира №» экспликации квартир.',
  inspection_id: null,
  created_by: null,
  created_at: '2026-09-28T10:00:00Z',
  evidence: [],
  ...overrides,
});

export const inputFact = (overrides: Partial<CalcInputFactRead> = {}): CalcInputFactRead => ({
  fact: fact(),
  fact_type_title: 'Квартир на этаже',
  source_title: 'Квартирография · АР.pdf',
  usage: 'USED',
  ...overrides,
});

export const readinessRow = (
  overrides: Partial<CalcReadinessRowRead> = {},
): CalcReadinessRowRead => ({
  requirement_id: 'vk.apartments.per_floor',
  title: 'Квартиры на этажах',
  group: 'APARTMENTS',
  fact_type: 'floor.apartments_count',
  level: 'REQUIRED',
  assumption: 'NOT_ALLOWED',
  status: 'FOUND',
  reason: null,
  values: [
    {
      fact_key: 'floor.apartments_count@building=1|floor=2..24',
      subject: { building: '1', floor: '2..24' },
      state: 'SINGLE',
      value: { kind: 'COUNT', value: 9, unit: 'apartment' },
      chosen_fact_id: '11111111-1111-4111-8111-111111111111',
      source_title: 'Квартирография · АР.pdf',
      source_class: 'APARTMENT_SCHEDULE',
      method: 'TABLE_COUNTED',
      confidence: 'MEDIUM',
      conflict_id: null,
    },
  ],
  excluded_count: 0,
  derivable_from: [],
  ...overrides,
});
