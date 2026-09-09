/**
 * Переходы черновика калибровки.
 *
 * Проверяется состояние, а не снимок разметки: снимок сказал бы «что-то нарисовалось»,
 * а нужно знать, что именно произошло с точками.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { NormalizedPoint } from '@/lib/viewer/coordinates';
import { ScaleDraft, type ScaleDraftState } from '@/lib/viewer/scale-draft';

const point = (x: number, y: number): NormalizedPoint => ({ x, y });

/** Уведомления склеиваются в кадр, поэтому тест их дожидается. */
const nextFrame = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 20));

describe('черновик калибровки', () => {
  let draft: ScaleDraft;

  beforeEach(() => {
    draft = new ScaleDraft();
  });

  it('начинает без точек', () => {
    expect(draft.getState().phase).toBe('idle');
    expect(draft.getState().a).toBeNull();
    expect(draft.getState().b).toBeNull();
  });

  it('первый щелчок ставит A и ждёт вторую точку', () => {
    draft.pick(point(0.25, 0.5));

    const state = draft.getState();
    expect(state.phase).toBe('awaiting-second');
    expect(state.a).toEqual(point(0.25, 0.5));
    expect(state.b).toBeNull();
  });

  it('второй щелчок завершает черновик', () => {
    draft.pick(point(0.25, 0.5));
    draft.pick(point(0.75, 0.5));

    const state = draft.getState();
    expect(state.phase).toBe('complete');
    expect(state.a).toEqual(point(0.25, 0.5));
    expect(state.b).toEqual(point(0.75, 0.5));
  });

  it('третий щелчок ничего не меняет', () => {
    // Иначе случайный клик мимо диалога молча переставил бы уже выбранный размер.
    draft.pick(point(0.25, 0.5));
    draft.pick(point(0.75, 0.5));
    draft.pick(point(0.1, 0.1));

    expect(draft.getState().b).toEqual(point(0.75, 0.5));
  });

  it('повторный щелчок в ту же точку не завершает черновик', () => {
    // Два попадания в один пиксель — почти наверняка дребезг, а не намерение.
    draft.pick(point(0.5, 0.5));
    draft.pick(point(0.5, 0.5));

    expect(draft.getState().phase).toBe('awaiting-second');
    expect(draft.getState().b).toBeNull();
  });

  it('движение указателя тянет свободный конец', () => {
    draft.pick(point(0.25, 0.5));
    draft.hover(point(0.6, 0.5));

    expect(draft.getState().hover).toEqual(point(0.6, 0.5));
    expect(draft.getState().phase).toBe('awaiting-second');
  });

  it('после завершения указатель линию больше не двигает', () => {
    draft.pick(point(0.25, 0.5));
    draft.pick(point(0.75, 0.5));
    draft.hover(point(0.1, 0.1));

    expect(draft.getState().b).toEqual(point(0.75, 0.5));
    expect(draft.getState().hover).toEqual(point(0.75, 0.5));
  });

  it('отмена возвращает черновик в исходное состояние', () => {
    draft.pick(point(0.25, 0.5));
    draft.pick(point(0.75, 0.5));

    draft.cancel();

    expect(draft.getState().phase).toBe('idle');
    expect(draft.getState().a).toBeNull();
  });

  it('отмена шага убирает вторую точку, оставляя первую', () => {
    // Попасть в засечку размерной линии с первого раза удаётся не всегда.
    draft.pick(point(0.25, 0.5));
    draft.pick(point(0.75, 0.5));

    draft.undo();

    expect(draft.getState().phase).toBe('awaiting-second');
    expect(draft.getState().a).toEqual(point(0.25, 0.5));
    expect(draft.getState().b).toBeNull();
  });

  it('отмена шага с одной точкой очищает черновик', () => {
    draft.pick(point(0.25, 0.5));

    draft.undo();

    expect(draft.getState().phase).toBe('idle');
  });

  it('отмена шага в пустом черновике ничего не делает', () => {
    draft.undo();

    expect(draft.getState().phase).toBe('idle');
  });
});

describe('уведомления подписчиков', () => {
  it('склеиваются в один кадр', async () => {
    // Указатель шлёт события чаще, чем браузер рисует: без склейки слой перерисовывался
    // бы вхолостую десятки раз в секунду.
    const draft = new ScaleDraft();
    const listener = vi.fn();
    draft.subscribe(listener);

    draft.pick({ x: 0.1, y: 0.1 });
    draft.hover({ x: 0.2, y: 0.2 });
    draft.hover({ x: 0.3, y: 0.3 });
    draft.hover({ x: 0.4, y: 0.4 });

    await nextFrame();

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener.mock.calls[0]?.[0]).toMatchObject({ hover: { x: 0.4, y: 0.4 } });
  });

  it('отписка прекращает уведомления', async () => {
    const draft = new ScaleDraft();
    const listener = vi.fn();
    const unsubscribe = draft.subscribe(listener);

    unsubscribe();
    draft.pick({ x: 0.1, y: 0.1 });
    await nextFrame();

    expect(listener).not.toHaveBeenCalled();
  });

  it('отмена в пустом черновике не будит подписчиков', async () => {
    const draft = new ScaleDraft();
    const listener = vi.fn();
    draft.subscribe(listener);

    draft.cancel();
    await nextFrame();

    expect(listener).not.toHaveBeenCalled();
  });

  it('состояние доступно сразу, не дожидаясь кадра', () => {
    // Обработчику щелчка нужно знать фазу немедленно: ждать кадра он не может.
    const draft = new ScaleDraft();
    const seen: ScaleDraftState[] = [];
    draft.subscribe((state) => seen.push(state));

    draft.pick({ x: 0.1, y: 0.1 });

    expect(draft.getState().phase).toBe('awaiting-second');
    expect(seen).toHaveLength(0);
  });
});
