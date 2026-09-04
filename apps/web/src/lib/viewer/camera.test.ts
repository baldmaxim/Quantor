import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Camera, MAX_SCALE, MIN_SCALE, ZOOM_STEP, type CameraState } from './camera';

const VIEWPORT = { width: 1200, height: 800 };
const SHEET = { width: 2481, height: 3509 };

/** Прогоняет запланированный кадр: уведомления камеры объединяются в кадр. */
const flushFrame = async (): Promise<void> => {
  await vi.advanceTimersByTimeAsync(32);
};

describe('камера', () => {
  let camera: Camera;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('requestAnimationFrame', undefined);
    vi.stubGlobal('cancelAnimationFrame', undefined);
    camera = new Camera();
  });

  afterEach(() => {
    camera.dispose();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('начинает со стопроцентного масштаба', () => {
    expect(camera.getState()).toEqual({ scale: 1, offsetX: 0, offsetY: 0 });
  });

  it('панорамирование складывает смещения', () => {
    camera.panBy(10, -20);
    camera.panBy(5, 5);

    expect(camera.getState()).toMatchObject({ offsetX: 15, offsetY: -15 });
  });

  describe('зум', () => {
    it('удерживает точку под курсором на месте', () => {
      // Без якоря лист уезжает из-под курсора, и его каждый раз доводят вручную.
      const anchor = { x: 400, y: 300 };
      const before = camera.getState();
      const pointBefore = {
        x: (anchor.x - before.offsetX) / before.scale,
        y: (anchor.y - before.offsetY) / before.scale,
      };

      camera.zoomAt(anchor, 2);

      const after = camera.getState();
      expect(after.offsetX + pointBefore.x * after.scale).toBeCloseTo(anchor.x, 6);
      expect(after.offsetY + pointBefore.y * after.scale).toBeCloseTo(anchor.y, 6);
    });

    it('не опускается ниже нижнего предела', () => {
      for (let step = 0; step < 100; step += 1) {
        camera.zoomAt({ x: 0, y: 0 }, 1 / ZOOM_STEP);
      }

      expect(camera.getState().scale).toBe(MIN_SCALE);
    });

    it('не поднимается выше верхнего предела', () => {
      for (let step = 0; step < 100; step += 1) {
        camera.zoomAt({ x: 0, y: 0 }, ZOOM_STEP);
      }

      expect(camera.getState().scale).toBe(MAX_SCALE);
    });

    it('кнопки зумируют относительно центра области', () => {
      camera.zoomIn(VIEWPORT);

      expect(camera.getState().scale).toBeCloseTo(ZOOM_STEP);
    });
  });

  describe('вписывание', () => {
    it('целиком помещает лист в область', () => {
      camera.fitPage(SHEET, VIEWPORT);
      const { scale, offsetX, offsetY } = camera.getState();

      expect(SHEET.width * scale).toBeLessThanOrEqual(VIEWPORT.width);
      expect(SHEET.height * scale).toBeLessThanOrEqual(VIEWPORT.height);
      expect(offsetX).toBeGreaterThanOrEqual(0);
      expect(offsetY).toBeGreaterThanOrEqual(0);
    });

    it('по ширине занимает всю ширину и прижимает лист к верху', () => {
      camera.fitWidth(SHEET, VIEWPORT);
      const { scale, offsetY } = camera.getState();

      expect(SHEET.width * scale).toBeCloseTo(VIEWPORT.width - 48);
      expect(offsetY).toBe(24);
    });

    it('сброс возвращает лист целиком', () => {
      camera.fitWidth(SHEET, VIEWPORT);
      const zoomed = camera.getState();

      camera.reset(SHEET, VIEWPORT);

      expect(camera.getState().scale).toBeLessThan(zoomed.scale);
    });

    it('пустой лист не ломает камеру', () => {
      camera.fitPage({ width: 0, height: 0 }, VIEWPORT);

      expect(camera.getState().scale).toBe(1);
    });
  });

  describe('подписка', () => {
    it('за кадр приходит одно уведомление независимо от числа движений', async () => {
      // Ради этого камера и существует: иначе каждое движение мыши перерисовывало бы
      // всё дерево React.
      const listener = vi.fn();
      camera.subscribe(listener);

      for (let step = 0; step < 50; step += 1) {
        camera.panBy(1, 1);
      }
      await flushFrame();

      expect(listener).toHaveBeenCalledTimes(1);
      expect(listener).toHaveBeenCalledWith(expect.objectContaining({ offsetX: 50, offsetY: 50 }));
    });

    it('отписка прекращает уведомления', async () => {
      const listener = vi.fn();
      const unsubscribe = camera.subscribe(listener);

      unsubscribe();
      camera.panBy(10, 10);
      await flushFrame();

      expect(listener).not.toHaveBeenCalled();
    });

    it('движение без изменения состояния не будит подписчиков', async () => {
      const listener = vi.fn();
      camera.subscribe(listener);

      camera.panBy(0, 0);
      await flushFrame();

      expect(listener).not.toHaveBeenCalled();
    });

    it('подписчик получает актуальное состояние, а не промежуточное', async () => {
      const states: CameraState[] = [];
      camera.subscribe((state) => states.push(state));

      camera.panBy(100, 0);
      camera.panBy(0, 100);
      camera.zoomAt({ x: 0, y: 0 }, 2);
      await flushFrame();

      expect(states).toHaveLength(1);
      expect(states[0]?.scale).toBe(2);
    });
  });

  it('масштаб, поставленный напрямую, ограничивается пределами', () => {
    camera.set({ scale: 1000, offsetX: 0, offsetY: 0 });

    expect(camera.getState().scale).toBe(MAX_SCALE);
  });
});
