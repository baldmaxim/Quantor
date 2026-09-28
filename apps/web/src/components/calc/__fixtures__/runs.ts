import type { CalcResultTraceRead, CalcRunSummaryRead } from '@quantor/api-client';

/** Фабрики данных для тестов экрана «Запуски». Значения синтетические. */

export const runSummary = (overrides: Partial<CalcRunSummaryRead> = {}): CalcRunSummaryRead => ({
  id: '44444444-4444-4444-8444-444444444444',
  project_id: '22222222-2222-4222-8222-222222222222',
  calculator_id: 'test.vertical_length',
  calculator_version: 1,
  calculator_title: 'ДЕМО: вертикальная длина — проверка ядра, не расчёт ВК',
  scenario: 'EXPECTED',
  status: 'SUCCEEDED',
  results_count: 2,
  blocking: null,
  result_sha256: 'a'.repeat(64),
  created_by: null,
  created_at: '2026-09-28T10:00:00Z',
  ...overrides,
});

export const resultTrace = (): CalcResultTraceRead => ({
  run_id: '44444444-4444-4444-8444-444444444444',
  result_key: 'demo.vertical_length',
  text: 'Вертикальная длина (демо) = 79,2 м. Высота этажа 3,3 м × 24 эт. = 79,2 м',
  root: {
    kind: 'RESULT',
    key: 'demo.vertical_length',
    title: 'Вертикальная длина (демо)',
    value: '79.2',
    unit: 'm',
    text: 'Вертикальная длина (демо) = 79,2 м',
    children: [
      {
        kind: 'STEP',
        key: 'vertical_length',
        title: 'Вертикальная длина',
        value: '79.2',
        unit: 'm',
        text: 'Высота этажа 3,3 м × 24 эт. = 79,2 м',
        children: [
          {
            kind: 'RULE',
            key: 'test.geometry.vertical_length@1',
            title: 'Тест: вертикальная длина',
            text: 'GEOMETRY; формула: L = h × n',
            children: [],
          },
          {
            kind: 'FACT',
            key: 'floor.height@building=1|floor=2..24',
            title: 'Высота этажа',
            value: '3.3',
            unit: 'm',
            text: 'Высота этажа: 3,3 м (заявлено: 3300 мм)',
            children: [],
          },
        ],
      },
    ],
  },
});
