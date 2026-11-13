import { describe, expect, it } from 'vitest';

import { isSanitaryMepLayer, mepGroupCount, mepLayerCounts } from './mep-layer-counts';

const preview = {
  layers: ['M-VK-V1', 'M-SAN-BATH', 'M-SAN-WC', 'M-NODE'],
  paths: [
    { layer: 0, closed: false },
    { layer: 1, closed: true },
    { layer: 1, closed: true },
    { layer: 1, closed: false },
    { layer: 2, closed: true },
    { layer: 3, closed: true },
  ],
};

describe('числа слоёв трасс', () => {
  it('приборы - замкнутые фигуры на M-SAN-*, остальные слои без числа', () => {
    expect(mepLayerCounts(preview, ['M-VK-V1', 'M-SAN-BATH', 'M-SAN-WC', 'M-NODE'])).toEqual([
      null,
      2,
      1,
      null,
    ]);
  });

  it('слой есть в списке имён, но без фигур, - 0, а не пропуск', () => {
    expect(mepLayerCounts(preview, ['M-SAN-BASIN'])).toEqual([0]);
  });

  it('чужое имя слоя числа не получает', () => {
    expect(isSanitaryMepLayer('M-SAN-X')).toBe(false);
    expect(isSanitaryMepLayer('M-SAN-WC')).toBe(true);
    expect(mepLayerCounts(preview, ['M-SAN-X'])).toEqual([null]);
  });

  it('сумма группы по индексам; без чисел - null', () => {
    const counts = mepLayerCounts(preview, ['M-VK-V1', 'M-SAN-BATH', 'M-SAN-WC']);
    expect(mepGroupCount(counts, [1, 2])).toBe(3);
    expect(mepGroupCount(counts, [0])).toBeNull();
    expect(mepGroupCount(counts, [])).toBeNull();
  });
});
