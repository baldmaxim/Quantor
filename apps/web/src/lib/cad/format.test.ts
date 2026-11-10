import { describe, expect, it } from 'vitest';

import {
  attemptElapsedSeconds,
  holdElapsed,
  requestedPagesLabel,
  secondsSince,
  serverOffsetMs,
  viewLabel,
} from './format';

describe('страницы', () => {
  it('показывает номера страниц с единицы', () => {
    expect(viewLabel(2, 2)).toBe('Стр. 3 · вид 2');
    expect(requestedPagesLabel(null)).toBe('все плановые');
    expect(requestedPagesLabel([2, 0])).toBe('стр. 1, 3');
  });
});

describe('время по часам сервера', () => {
  it('идущая попытка считается по часам сервера, а не браузера', () => {
    const received = 1_000_000;
    // Часы сервера впереди браузера на минуту.
    const offset = serverOffsetMs(new Date(received + 60_000).toISOString(), received);
    expect(offset).toBe(60_000);
    const started = new Date(received + 60_000 - 5_000).toISOString();
    expect(attemptElapsedSeconds(started, null, true, received + 3_000, offset)).toBe(8);
  });

  it('завершённая считается по меткам сервера и не тикает', () => {
    const elapsed = attemptElapsedSeconds(
      '2026-11-09T10:00:00Z',
      '2026-11-09T10:00:42Z',
      false,
      Date.now(),
      999,
    );
    expect(elapsed).toBe(42);
  });

  it('без начала значения нет', () => {
    expect(attemptElapsedSeconds(null, null, true, 1, 0)).toBeNull();
    expect(secondsSince(null, '2026-11-09T10:00:00Z')).toBeNull();
    expect(secondsSince('2026-11-09T10:00:00Z', '2026-11-09T10:00:07Z')).toBe(7);
  });
});

describe('монотонный таймер идущей попытки', () => {
  it('не показывает меньше уже показанного для той же попытки', () => {
    const first = holdElapsed(null, 'job:1', 5, true);
    expect(first.shown).toBe(5);
    // Смещение часов уточнилось, сырое значение шагнуло назад.
    const second = holdElapsed(first.peak, 'job:1', 4.2, true);
    expect(second.shown).toBe(5);
    const third = holdElapsed(second.peak, 'job:1', 6, true);
    expect(third.shown).toBe(6);
  });

  it('другая попытка начинает с нуля, а не с чужого потолка', () => {
    const first = holdElapsed(null, 'job:1', 50, true);
    expect(holdElapsed(first.peak, 'job:2', 0.4, true).shown).toBe(0.4);
  });

  it('завершённая показывает точное значение и сбрасывает потолок', () => {
    const running = holdElapsed(null, 'job:1', 42.9, true);
    const finished = holdElapsed(running.peak, 'job:1', 42, false);
    expect(finished.shown).toBe(42);
    expect(finished.peak).toBeNull();
  });

  it('без значения - прочерк, потолок сбрасывается', () => {
    expect(holdElapsed({ key: 'a', value: 3 }, 'a', null, true)).toEqual({
      shown: null,
      peak: null,
    });
  });
});
