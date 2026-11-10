import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Camera } from '@/lib/viewer/camera';

import { CadZoneCapture } from './CadZoneCapture';

// Лист 1000 x 1000 при масштабе 1 и нулевом смещении: пиксель = 1/1000 листа.
const PAGE = { width: 1000, height: 1000 };

const tap = (layer: HTMLElement, x: number, y: number) => {
  fireEvent.pointerDown(layer, {
    pointerId: 1,
    clientX: x,
    clientY: y,
    button: 0,
    pointerType: 'mouse',
  });
  fireEvent.pointerUp(layer, {
    pointerId: 1,
    clientX: x,
    clientY: y,
    button: 0,
    pointerType: 'mouse',
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

  const mount = (kind: 'room_apartment' | 'door') => {
    const camera = new Camera();
    const onComplete = vi.fn();
    const onExit = vi.fn();
    render(
      <CadZoneCapture
        camera={camera}
        page={PAGE}
        kind={kind}
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
});
