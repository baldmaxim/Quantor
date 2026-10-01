import type { CalcRuleVersionRead, CalcVkRuleNeedRead } from '@quantor/api-client';

/** Заявка и версия правила для тестов. Числа синтетические — не норма. */

export const need = (overrides: Partial<CalcVkRuleNeedRead> = {}): CalcVkRuleNeedRead => ({
  rule_key: 'vk.b1.risers.count_range',
  title: 'Число стояков В1 по квартирам на этаже',
  systems: ['В1'],
  layer: 'B',
  rule_types: ['ENGINEERING'],
  implementation_key: 'vk.risers.count_range.v1',
  formula: 'стояков = ⌈квартир на этаже / квартир на стояк⌉',
  inputs: [],
  parameters: [
    {
      name: 'per_riser_min',
      unit: 'apartment',
      meaning: 'Квартир на один стояк — нижняя граница',
      quantity: null,
    },
    {
      name: 'per_riser_max',
      unit: 'apartment',
      meaning: 'Квартир на один стояк — верхняя граница',
      quantity: null,
    },
  ],
  outputs: [],
  used_in: 'шаг structure_risers',
  blocks: 'число стояков',
  affects: [],
  gate: true,
  example: '8 кв. на этаже, 2–3 кв. на стояк → 3–4 стояка (синтетика)',
  ...overrides,
});

export const ruleVersion = (overrides: Partial<CalcRuleVersionRead> = {}): CalcRuleVersionRead => ({
  rule_key: 'vk.b1.risers.count_range',
  version: 1,
  status: 'DRAFT',
  rule_type: 'ENGINEERING',
  content: {
    title: 'Число стояков В1 по квартирам на этаже',
    description: 'Синтетика',
    rule_type: 'ENGINEERING',
    discipline: 'VK',
    applicability: {
      systems: ['В1'],
      stages: ['P'],
      scope: 'Жилые здания, стадия П',
      limitations: ['Значения параметров — только из источника версии правила.'],
    },
    inputs: [],
    parameters: [
      { name: 'per_riser_min', value: '2', unit: 'apartment', description: 'Нижняя граница' },
      { name: 'per_riser_max', value: '3', unit: 'apartment', description: 'Верхняя граница' },
    ],
    outputs: [
      { name: 'risers_min', quantity: 'riser.count_min', unit: 'riser', description: 'не меньше' },
    ],
    formula: 'стояков = ⌈квартир / квартир на стояк⌉',
    explanation: 'Синтетика',
    implementation_key: 'vk.risers.count_range.v1',
    sources: [
      {
        kind: 'ENGINEERING_METHOD',
        title: 'Методика',
        author: 'Инженер',
        reference: 'протокол',
        summary: 'суть',
      },
    ],
  },
  content_sha256: 'a'.repeat(64),
  calculation_eligible: false,
  notice: null,
  change_reason: null,
  created_by: 'u-author',
  edited_by: 'u-author',
  created_at: '2026-10-01T10:00:00Z',
  approved_by: null,
  approved_at: null,
  deprecated_by: null,
  deprecated_at: null,
  deprecation_reason: null,
  rejected_by: null,
  rejected_at: null,
  rejection_reason: null,
  legacy_provenance: [],
  reviews: [],
  ...overrides,
});
