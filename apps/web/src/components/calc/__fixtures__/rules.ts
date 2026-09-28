import type { CalcLegacyRuleRead, CalcRuleSummaryRead } from '@quantor/api-client';

/** Фабрики данных для тестов экрана «Правила». Значения синтетические. */

export const ruleSummary = (overrides: Partial<CalcRuleSummaryRead> = {}): CalcRuleSummaryRead => ({
  rule_key: 'test.riser.length',
  discipline: 'VK',
  title: 'Тестовая длина стояка',
  rule_type: 'GEOMETRY',
  systems: ['В1'],
  latest_version: 1,
  latest_status: 'DRAFT',
  approved_version: null,
  calculation_eligible: false,
  sources: ['Синтетическая тестовая фикстура'],
  notice: null,
  ...overrides,
});

export const legacyRule = (overrides: Partial<CalcLegacyRuleRead> = {}): CalcLegacyRuleRead => ({
  legacy_id: 'LEG-VK-001',
  catalog: 'VK',
  section: 'A. Геометрия',
  location: '`main.js:1`',
  code_refs: [{ file: 'main.js', lines: '1', symbol: null }],
  rule_text: 'h1 = 4,0 м — жёстко',
  class_primary: 'UNKNOWN_ORIGIN',
  class_secondary: [],
  class_raw: 'неизв',
  assumptions: 'все этажи одинаковы',
  action_raw: 'ВВОД',
  actions: ['MAKE_INPUT'],
  hazards: ['HIDDEN_DEFAULT'],
  group_ids: [],
  status: 'UNVERIFIED_LEGACY',
  calculation_eligible: false,
  notice: 'НЕ ПРОВЕРЕНО / НЕ ИСПОЛЬЗУЕТСЯ В РАСЧЁТЕ',
  ...overrides,
});
