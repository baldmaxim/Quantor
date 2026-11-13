import { describe, expect, it } from 'vitest';

import { CLICK_SLOP_PX, createClickTracker } from './floor3d-click';

describe('щелчок и перетаскивание', () => {
  it('нажатие без смещения: движения камеры нет, отпускание - щелчок', () => {
    const tracker = createClickTracker();
    tracker.down(100, 100);
    expect(tracker.move(100 + CLICK_SLOP_PX, 100)).toBe(false);
    expect(tracker.up(100, 100)).toBe(true);
  });

  it('смещение больше порога сообщается один раз и отменяет щелчок', () => {
    const tracker = createClickTracker();
    tracker.down(0, 0);
    expect(tracker.move(CLICK_SLOP_PX + 1, 0)).toBe(true);
    expect(tracker.move(CLICK_SLOP_PX + 20, 0)).toBe(false);
    // Вернулись в исходную точку: перетаскивание уже было, щелчком не считается.
    expect(tracker.up(0, 0)).toBe(false);
  });

  it('без нажатия указатель движения камеры не даёт', () => {
    const tracker = createClickTracker();
    expect(tracker.move(500, 500)).toBe(false);
    expect(tracker.up(500, 500)).toBe(false);
  });

  it('следующее нажатие начинается заново', () => {
    const tracker = createClickTracker();
    tracker.down(0, 0);
    tracker.move(50, 0);
    tracker.up(50, 0);
    tracker.down(10, 10);
    expect(tracker.up(10, 10)).toBe(true);
    tracker.down(10, 10);
    tracker.cancel();
    expect(tracker.up(10, 10)).toBe(false);
  });
});
