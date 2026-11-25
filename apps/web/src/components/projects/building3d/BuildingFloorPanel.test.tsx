import type { CadBuilding3dWindowRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { windowsSummary } from './BuildingFloorPanel';

const window = (accepted: boolean): CadBuilding3dWindowRead => ({
  opening_id: `o-${accepted ? 'a' : 'c'}`,
  shell: [
    [0, 0],
    [1000, 0],
    [1000, 200],
  ],
  sill_z_bottom_mm: 0,
  glass_z_bottom_mm: 900,
  glass_z_top_mm: 2400,
  lintel_z_top_mm: 2800,
  accepted,
  source: 'facade',
});

describe('строка «Окна» панели этажа', () => {
  it('принятые и кандидаты считаются отдельно', () => {
    expect(windowsSummary([window(true), window(true), window(false)])).toBe('принятые 2, кандидаты 1');
  });

  it('окон нет - нули, не «—»', () => {
    expect(windowsSummary([])).toBe('принятые 0, кандидаты 0');
  });

  it('окна не запрошены - «—», не ноль', () => {
    expect(windowsSummary(null)).toBe('—');
    expect(windowsSummary(undefined)).toBe('—');
  });
});
