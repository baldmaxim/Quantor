import { describe, expect, it, vi } from 'vitest';

import { mepLayersOf } from './mep-side';

const preview = {
  layers: ['M-VK-V1', 'M-SAN-WC'],
  paths: [
    { layer: 0, closed: false },
    { layer: 1, closed: true },
  ],
};

describe('mepLayersOf: числа приборов', () => {
  it('с превью трасс у слоёв приборов число, у трасс null', () => {
    const result = mepLayersOf(preview.layers, 0, vi.fn(), preview);
    expect(result?.counts).toEqual([null, 1]);
  });

  it('без превью чисел нет', () => {
    expect(mepLayersOf(preview.layers, 0, vi.fn())?.counts).toBeUndefined();
  });
});
