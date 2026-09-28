import { describe, expect, it } from 'vitest';

import { amountText } from './vk';

describe('значение позиции ВК', () => {
  it('точное, диапазон и «не определено»', () => {
    expect(amountText({ value: '45' }, 'm')).toBe('45 м');
    expect(amountText({ low: '144.4', high: '216.6' }, 'm')).toBe('144,4–216,6 м');
    expect(amountText({}, 'piece')).toBe('не определено');
  });
});
