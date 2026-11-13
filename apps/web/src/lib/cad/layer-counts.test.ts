import { describe, expect, it } from 'vitest';

import { layerCountsOf, NO_LAYER_COUNTS } from './layer-counts';

describe('числа вкладки «Слои»', () => {
  it('данных нет - все числа null, не 0', () => {
    expect(layerCountsOf(null)).toBe(NO_LAYER_COUNTS);
    expect(Object.values(NO_LAYER_COUNTS).every((value) => value === null)).toBe(true);
  });

  it('считает конструкции по строкам и двери; перемычек в данных нет', () => {
    const counts = layerCountsOf({
      constructions: [
        { kind: 'masonry' },
        { kind: 'masonry' },
        { kind: 'frame_partition' },
        { kind: 'monolith_wall' },
        { kind: 'monolith_pylon' },
        { kind: 'monolith_column' },
        { kind: 'floor_slab' },
      ],
      openings: [{ kind: 'door' }, { kind: 'window' }, { kind: 'gap' }, { kind: 'door' }],
    });
    expect(counts).toEqual({
      monolithVertical: 2,
      monolithColumn: 1,
      slab: 1,
      masonry: 2,
      doors: 2,
    });
  });
});
