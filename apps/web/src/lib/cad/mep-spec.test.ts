import { describe, expect, it } from 'vitest';

import { CANDIDATE_SCHEMA, parseCandidate } from './mep-candidate';
import { buildSpec, eomSpecSystems, qtyText, sizeText } from './mep-spec';

const candidate = (routes: Record<string, unknown>) => {
  const parsed = parseCandidate({
    schema: CANDIDATE_SCHEMA,
    status: 'candidate_requires_review',
    elevation: {
      floor_elevation_mm: { value: 0, source: 'observed' },
      floor_height_mm: { value: 3000, source: 'observed' },
    },
    routes: { totals: { len3d_m: 0 }, ...routes },
  });
  if (parsed === null) throw new Error('кандидат не разобран');
  return parsed;
};

describe('общая спецификация', () => {
  it('механика: системы по генератору, слой по Ø и сечениям, остаток без размера', () => {
    const spec = buildSpec(
      candidate({
        layers: { 'M-VK-K2': { system: 'storm' }, 'M-OV-VMOP': { system: 'vent' }, 'M-VK-V1': { system: 'water' } },
        by_layer: {
          'M-VK-K2': { len3d_m: 3 },
          'M-OV-VMOP': { len3d_m: 4 },
          'M-VK-V1': { len3d_m: 6 },
        },
        by_layer_dims: {
          'M-VK-V1': { by_dn_mm: { '32': { len3d_m: 2 }, '20': { len3d_m: 3 } } },
          'M-OV-VMOP': { by_size: { '400x200': { len3d_m: 4 } } },
        },
        by_system: { storm: { len3d_m: 3 }, vent: { len3d_m: 4 }, water: { len3d_m: 6 } },
      }),
      [],
    );
    expect(spec.map((system) => system.label)).toEqual(['Водоснабжение', 'Водосток', 'Вентиляция']);
    const [water, storm, vent] = spec;
    expect(water?.summary).toBe('6,00 м');
    expect(water?.rows.map((row) => `${row.item}: ${row.qty}`)).toEqual([
      'Водопровод В1, Ø20 мм: 3,00',
      'Водопровод В1, Ø32 мм: 2,00',
      'Водопровод В1, размер не определён: 1,00',
    ]);
    // Водосток К2 в панели «Слои» - группа «Канализация», но система - по генератору.
    expect(storm?.rows.map((row) => row.item)).toEqual(['Водосток К2']);
    expect(vent?.rows.map((row) => row.item)).toEqual(['Вытяжка МОП, 400×200 мм']);
  });

  it('ЭОМ и СС: группы по системе в порядке генератора, после механики', () => {
    const spec = buildSpec(candidate({ by_layer: { 'M-OV-T1': { len3d_m: 1 } } }), [
      { system: 'ЭОМ: питающие линии', item: 'ППГнг(А)-HF 5×6', unit: 'м', qty: 12.345, formula: 'по трассе' },
      { system: 'СС: оборудование', item: 'Шкаф СС', unit: 'шт', qty: 1 },
      { system: 'ЭОМ: питающие линии', item: 'Труба ПВХ Ø40', unit: 'м', qty: 10 },
    ]);
    expect(spec.map((system) => `${system.source}:${system.label}`)).toEqual([
      'mep:Отопление',
      'eom:ЭОМ: питающие линии',
      'eom:СС: оборудование',
    ]);
    const [, feed] = spec;
    expect(feed?.summary).toBe('2 поз.');
    expect(feed?.rows[0]).toMatchObject({ qty: '12,35', unit: 'м', hint: 'по трассе' });
  });

  it('пусто без кандидата и ведомости; форматы', () => {
    expect(buildSpec(null, [])).toEqual([]);
    expect(eomSpecSystems([])).toEqual([]);
    expect(sizeText('400x200')).toBe('400×200 мм');
    expect(sizeText('Ø200')).toBe('Ø200 мм');
    expect(qtyText(3)).toBe('3');
  });
});
