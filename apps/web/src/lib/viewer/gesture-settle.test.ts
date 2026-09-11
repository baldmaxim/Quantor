import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GestureSettle } from './gesture-settle';

/**
 * Затихание жеста.
 *
 * Дефект, пойманный замером промта 03: таймер «180 мс без изменений» срабатывал посреди панорамы,
 * когда кадры сами шли дольше 180 мс, и pdf.js начинал рисовать на жесте. Кадры здесь крутятся
 * вручную, а часы подставные: так видно именно правило, а не везение таймеров.
 */

let frames: (() => void)[] = [];
let clock = 0;

/** Показывает один кадр: сначала то, что сделал жест, потом ожидавшие кадра обработчики. */
const runFrame = (advanceMs: number, gesture?: () => void): void => {
  clock += advanceMs;
  const pending = frames;
  frames = [];
  gesture?.();
  for (const callback of pending) callback();
};

beforeEach(() => {
  frames = [];
  clock = 0;
  vi.stubGlobal('requestAnimationFrame', (callback: () => void) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {
    frames = [];
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('затихание жеста', () => {
  it('жест, меняющий камеру на каждом кадре, не затихает, как бы долго ни шёл кадр', () => {
    const settled = vi.fn();
    const settle = new GestureSettle(180, settled, () => clock);

    // Двадцать кадров по 300 мс: каждый дольше паузы, и на каждом камера меняется.
    settle.change();
    for (let frame = 0; frame < 20; frame += 1) runFrame(300, () => settle.change());

    expect(settled).not.toHaveBeenCalled();
  });

  it('затихает после паузы и хотя бы двух кадров без изменений', () => {
    const settled = vi.fn();
    const settle = new GestureSettle(180, settled, () => clock);

    settle.change();
    runFrame(16);
    runFrame(16);
    // Два тихих кадра есть, паузы ещё нет.
    expect(settled).not.toHaveBeenCalled();

    for (let frame = 0; frame < 10; frame += 1) runFrame(16);
    expect(settled).toHaveBeenCalledTimes(1);
  });

  it('одного долгого тихого кадра мало — нужен второй', () => {
    const settled = vi.fn();
    const settle = new GestureSettle(180, settled, () => clock);

    settle.change();
    runFrame(400);
    expect(settled).not.toHaveBeenCalled();

    runFrame(16);
    expect(settled).toHaveBeenCalledTimes(1);
  });

  it('изменение посреди отсчёта начинает его заново', () => {
    const settled = vi.fn();
    const settle = new GestureSettle(180, settled, () => clock);

    settle.change();
    for (let frame = 0; frame < 10; frame += 1) runFrame(16);
    runFrame(16, () => settle.change());
    for (let frame = 0; frame < 5; frame += 1) runFrame(16);

    expect(settled).not.toHaveBeenCalled();
  });

  it('после затихания кадры больше не заказываются, dispose снимает ожидающий', () => {
    const settled = vi.fn();
    const settle = new GestureSettle(180, settled, () => clock);

    settle.change();
    for (let frame = 0; frame < 20; frame += 1) runFrame(16);
    expect(settled).toHaveBeenCalledTimes(1);
    expect(frames).toHaveLength(0);

    settle.change();
    settle.dispose();
    for (let frame = 0; frame < 20; frame += 1) runFrame(16);
    expect(settled).toHaveBeenCalledTimes(1);
  });
});
