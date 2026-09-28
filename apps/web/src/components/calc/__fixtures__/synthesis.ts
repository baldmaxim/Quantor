import type { CalcSystemGraph } from '@quantor/api-client';

/** Фабрика графа для тестов экрана «Структура системы». Значения синтетические. */

const scope = { building: '1', floor: '1..24', discipline: 'VK' as const, system_code: 'В1' };

export const systemGraph = (): CalcSystemGraph => ({
  graph_type: 'test.riser_structure',
  discipline: 'VK',
  system_code: 'В1',
  scope,
  scenario: 'EXPECTED',
  synthesizer_id: 'test.riser_structure',
  synthesizer_version: 1,
  nodes: [
    {
      id: 'inlet',
      semantic_type: 'INLET',
      title: 'Ввод',
      provenance: 'OBSERVED',
      scope,
      cardinality: { min: 1, max: 1 },
      support: 'Ввод указан в документации: 1',
    },
    {
      id: 'risers',
      semantic_type: 'RISER_GROUP',
      title: 'Стояки',
      provenance: 'CALCULATED',
      scope,
      cardinality: { min: 4, max: 5 },
      support: 'Необходимость стояков следует из расчёта: 4–5 ст.',
    },
    {
      id: 'typical_floors',
      semantic_type: 'TYPICAL_FLOOR_GROUP',
      title: 'Типовой этаж',
      provenance: 'OBSERVED',
      scope,
      cardinality: { min: 1, max: 1 },
      multiplicity: 24,
      support: 'Этажность по документации',
    },
  ],
  edges: [
    {
      id: 'supply_main',
      semantic_type: 'SUPPLY',
      title: 'Магистраль от ввода к стоякам',
      provenance: 'SYNTHESIZED',
      source_node: 'inlet',
      target_node: 'risers',
      support: 'По правилу топологии',
    },
  ],
  unresolved: [
    {
      key: 'risers.count',
      kind: 'COUNT_RANGE',
      title: 'Количество стояков',
      element_id: 'risers',
      known: '4–5 по расчёту',
      needed: 'утверждённое правило выбора или решение инженера',
      structural: true,
    },
  ],
  assumptions: [],
  warnings: [],
});
