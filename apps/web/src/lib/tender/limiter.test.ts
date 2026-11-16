import { describe, expect, it } from 'vitest';

import { createLimiter } from './limiter';

describe('ограничитель запросов', () => {
  it('одновременно идёт не больше предела, остальные ждут очереди', async () => {
    const limiter = createLimiter(6);
    let active = 0;
    let peak = 0;
    const task = async (index: number): Promise<number> => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 2));
      active -= 1;
      return index;
    };
    const results = await Promise.all(
      Array.from({ length: 20 }, (_, index) => limiter.run(() => task(index))),
    );
    expect(peak).toBe(6);
    expect(results).toEqual(Array.from({ length: 20 }, (_, index) => index));
  });

  it('отказ одного запроса не останавливает очередь', async () => {
    const limiter = createLimiter(1);
    const failed = limiter.run(() => Promise.reject(new Error('сбой')));
    const next = limiter.run(() => Promise.resolve('ok'));
    await expect(failed).rejects.toThrow('сбой');
    await expect(next).resolves.toBe('ok');
  });
});
