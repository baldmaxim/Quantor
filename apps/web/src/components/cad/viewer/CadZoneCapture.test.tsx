import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { CadZoneRead } from '@quantor/api-client';

import { buildSnapIndex, type ISnapIndex } from '@/lib/cad/zone-snap';
import { Camera } from '@/lib/viewer/camera';

import { CadZoneCapture } from './CadZoneCapture';

// Лист 1000 x 1000 при масштабе 1 и нулевом смещении: пиксель = 1/1000 листа.
const PAGE = { width: 1000, height: 1000 };

const zone = (patch: Partial<CadZoneRead>): CadZoneRead => ({
  id: 'z1',
  revision_id: 'r1',
  page_index: 0,
  kind: 'room_mop',
  apartment_no: null,
  room_mark: null,
  name: null,
  points: [
    [0.5, 0.5],
    [0.8, 0.5],
    [0.8, 0.8],
    [0.5, 0.8],
  ],
  door_height_mm: null,
  area_m2: null,
  perimeter_m: null,
  width_m: null,
  calibration_missing: true,
  geometry_issue: null,
  created_at: '2026-11-10T00:00:00Z',
  updated_at: '2026-11-10T00:00:00Z',
  ...patch,
});

interface ITapOptions {
  shiftKey?: boolean;
  altKey?: boolean;
}

const tap = (layer: HTMLElement, x: number, y: number, modifiers: ITapOptions = {}) => {
  fireEvent.pointerDown(layer, {
    pointerId: 1,
    clientX: x,
    clientY: y,
    button: 0,
    pointerType: 'mouse',
    ...modifiers,
  });
  fireEvent.pointerUp(layer, {
    pointerId: 1,
    clientX: x,
    clientY: y,
    button: 0,
    pointerType: 'mouse',
    ...modifiers,
  });
};

describe('CadZoneCapture', () => {
  beforeEach(() => {
    HTMLElement.prototype.setPointerCapture = vi.fn();
    HTMLElement.prototype.releasePointerCapture = vi.fn();
    HTMLElement.prototype.hasPointerCapture = vi.fn(() => false);
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null);
  });
  afterEach(() => vi.restoreAllMocks());

  const mount = (
    kind: 'room_apartment' | 'door',
    zones: readonly CadZoneRead[] = [],
    walls: ISnapIndex | null = null,
  ) => {
    const camera = new Camera();
    const onComplete = vi.fn();
    const onExit = vi.fn();
    render(
      <CadZoneCapture
        camera={camera}
        page={PAGE}
        kind={kind}
        zones={zones}
        walls={walls}
        onComplete={onComplete}
        onExit={onExit}
      />,
    );
    return { layer: screen.getByTestId('zone-capture'), onComplete, onExit, camera };
  };

  it('помещение: щелчки ставят вершины, Enter замыкает и отдаёт точки в долях листа', () => {
    const { layer, onComplete } = mount('room_apartment');
    tap(layer, 100, 100);
    tap(layer, 400, 100);
    tap(layer, 400, 400);
    expect(onComplete).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onComplete).toHaveBeenCalledWith([
      [0.1, 0.1],
      [0.4, 0.1],
      [0.4, 0.4],
    ]);
  });

  it('щелчок по первой вершине замыкает контур', () => {
    const { layer, onComplete } = mount('room_apartment');
    tap(layer, 100, 100);
    tap(layer, 400, 100);
    tap(layer, 400, 400);
    tap(layer, 103, 102);
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete.mock.calls[0]?.[0]).toHaveLength(3);
  });

  it('Backspace убирает вершину, Esc сначала отменяет черновик, затем закрывает режим', () => {
    const { layer, onComplete, onExit } = mount('room_apartment');
    tap(layer, 100, 100);
    tap(layer, 400, 100);
    tap(layer, 400, 400);
    fireEvent.keyDown(document, { key: 'Backspace' });
    fireEvent.keyDown(document, { key: 'Enter' });
    expect(onComplete).not.toHaveBeenCalled();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onExit).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it('дверь завершается второй точкой', () => {
    const { layer, onComplete } = mount('door');
    tap(layer, 100, 500);
    tap(layer, 200, 500);
    expect(onComplete).toHaveBeenCalledWith([
      [0.1, 0.5],
      [0.2, 0.5],
    ]);
  });

  it('перетаскивание двигает лист и вершину не ставит', () => {
    const { layer, onComplete, camera } = mount('door');
    fireEvent.pointerDown(layer, {
      pointerId: 1,
      clientX: 100,
      clientY: 100,
      button: 0,
      pointerType: 'mouse',
    });
    fireEvent.pointerMove(layer, {
      pointerId: 1,
      clientX: 160,
      clientY: 130,
      button: 0,
      pointerType: 'mouse',
    });
    fireEvent.pointerUp(layer, {
      pointerId: 1,
      clientX: 160,
      clientY: 130,
      button: 0,
      pointerType: 'mouse',
    });
    expect(camera.getState().offsetX).toBe(60);
    expect(camera.getState().offsetY).toBe(30);
    // Вершины нет: одного щелчка по двери мало для завершения.
    tap(layer, 300, 300);
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('клавиши в поле ввода рисование не трогают', () => {
    const { layer, onExit } = mount('room_apartment');
    tap(layer, 100, 100);
    const input = document.createElement('input');
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onExit).not.toHaveBeenCalled();
    input.remove();
  });

  describe('привязка', () => {
    const ZONES = [zone({})];

    it('вершина ставится в вершину готовой зоны, если щелчок рядом', () => {
      const { layer, onComplete } = mount('door', ZONES);
      tap(layer, 505, 496); // 5 px и 4 px от вершины (0.5, 0.5)
      tap(layer, 200, 200);
      expect(onComplete).toHaveBeenCalledWith([
        [0.5, 0.5],
        [0.2, 0.2],
      ]);
    });

    it('вершина ставится на ребро готовой зоны', () => {
      const { layer, onComplete } = mount('door', ZONES);
      tap(layer, 650, 495); // у ребра y = 0.5
      tap(layer, 200, 200);
      const first = onComplete.mock.calls[0]?.[0]?.[0];
      expect(first?.[0]).toBeCloseTo(0.65, 10);
      expect(first?.[1]).toBeCloseTo(0.5, 10);
    });

    it('Alt отключает привязку', () => {
      const { layer, onComplete } = mount('door', ZONES);
      tap(layer, 505, 496, { altKey: true });
      tap(layer, 200, 200);
      expect(onComplete).toHaveBeenCalledWith([
        [0.505, 0.496],
        [0.2, 0.2],
      ]);
    });

    it('Shift: вторая точка двери строго по горизонтали от первой', () => {
      const { layer, onComplete } = mount('door');
      tap(layer, 100, 300);
      tap(layer, 400, 320, { shiftKey: true });
      expect(onComplete).toHaveBeenCalledWith([
        [0.1, 0.3],
        [0.4, 0.3],
      ]);
    });

    it('привязка к вершине своего черновика', () => {
      const { layer, onComplete } = mount('room_apartment');
      tap(layer, 100, 100);
      tap(layer, 400, 100);
      tap(layer, 400, 400);
      tap(layer, 700, 700);
      // Рядом со второй вершиной (400, 100), но вне радиуса замыкания первой: точка = вершина.
      tap(layer, 404, 103);
      fireEvent.keyDown(document, { key: 'Enter' });
      expect(onComplete.mock.calls[0]?.[0]?.[4]).toEqual([0.4, 0.1]);
    });

    it('точка ставится в угол и на грань стены листа', () => {
      const walls = buildSnapIndex([
        {
          closed: true,
          points: [
            [0.2, 0.2],
            [0.4, 0.2],
            [0.4, 0.4],
            [0.2, 0.4],
          ],
        },
      ]);
      const { layer, onComplete } = mount('door', [], walls);
      tap(layer, 203, 198); // угол (0.2, 0.2)
      tap(layer, 300, 396); // грань y = 0.4
      const [first, second] = onComplete.mock.calls[0]?.[0] ?? [];
      expect(first).toEqual([0.2, 0.2]);
      expect(second?.[0]).toBeCloseTo(0.3, 10);
      expect(second?.[1]).toBeCloseTo(0.4, 10);
    });

    it('без стен привязки к ним нет', () => {
      const { layer, onComplete } = mount('door', [], null);
      tap(layer, 203, 198);
      tap(layer, 300, 300);
      expect(onComplete).toHaveBeenCalledWith([
        [0.203, 0.198],
        [0.3, 0.3],
      ]);
    });

    it('колесо с Shift в режиме рисования масштабирует, а не панорамирует', () => {
      const { layer, camera } = mount('door');
      fireEvent.wheel(layer, { deltaY: 100, shiftKey: true, clientX: 10, clientY: 10 });
      // Масштаб изменился: сработал зум слоя захвата, а не горизонтальная панорама viewport.
      expect(camera.getState().scale).toBeLessThan(1);
    });
  });
});
