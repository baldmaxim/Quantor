import { describe, expect, it } from 'vitest';

import { differenceText, objectQuantitiesText, quantityText } from './format';

describe('форматирование заполнения ВОР', () => {
  it('количества объекта: единицы, неполнота и прочерк вместо 0', () => {
    expect(
      objectQuantitiesText({
        quantities: [
          { unit: 'm3', value: 12.5 },
          { unit: 'm2', value: 40 },
        ],
        incomplete: false,
      }),
    ).toBe('12,5 м³ · 40 м²');
    expect(
      objectQuantitiesText({ quantities: [{ unit: 'pcs', value: 3 }], incomplete: true }),
    ).toBe('3 шт (неполно)');
    expect(objectQuantitiesText({ quantities: [], incomplete: false })).toBe('—');
  });

  it('количество и разница: не определено - прочерк', () => {
    expect(quantityText(null, 'm3')).toBe('—');
    expect(quantityText(2, 'pcs')).toBe('2 шт');
    expect(differenceText({ difference: null, difference_percent: null })).toBe('—');
    expect(differenceText({ difference: -2, difference_percent: -22.2 })).toBe('-2 (-22,2 %)');
  });
});
