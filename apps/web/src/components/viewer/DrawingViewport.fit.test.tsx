import { render } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DrawingViewport } from './DrawingViewport';
import { Camera } from '@/lib/viewer/camera';

/**
 * Вписка листа при скрытой области (clientWidth = 0): откладывается до первого ненулевого
 * размера, дальше обычный ресайз вид не перевписывает.
 */

const SHEET = { pageIndex: 0, width: 1000, height: 500 };

let size = { width: 0, height: 0 };
const callbacks: Array<() => void> = [];

class FakeResizeObserver {
  constructor(callback: () => void) {
    callbacks.push(callback);
  }
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const resize = (width: number, height: number) => {
  size = { width, height };
  act(() => {
    callbacks.forEach((callback) => callback());
  });
};

beforeEach(() => {
  size = { width: 0, height: 0 };
  callbacks.length = 0;
  vi.stubGlobal('ResizeObserver', FakeResizeObserver);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (
    this: HTMLCanvasElement,
  ) {
    return new Proxy(
      { canvas: this },
      { get: (target, key) => (key in target ? Reflect.get(target, key) : () => undefined), set: () => true },
    ) as unknown as CanvasRenderingContext2D;
  } as unknown as typeof HTMLCanvasElement.prototype.getContext);
  vi.spyOn(Element.prototype, 'clientWidth', 'get').mockImplementation(() => size.width);
  vi.spyOn(Element.prototype, 'clientHeight', 'get').mockImplementation(() => size.height);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const mount = (camera: Camera) =>
  render(
    <DrawingViewport
      backend={null}
      sheet={SHEET}
      regions={[]}
      hiddenTypes={new Set()}
      overlayVisible={false}
      selectedId={null}
      onSelect={vi.fn()}
      camera={camera}
      tool="pan"
    />,
  );

describe('вписка листа при нулевой области DrawingViewport', () => {
  it('нулевая область не вписывает, первый ненулевой размер вписывает', () => {
    const camera = new Camera();
    const fit = vi.spyOn(camera, 'fitPage');
    mount(camera);
    expect(fit).not.toHaveBeenCalled();

    resize(0, 0);
    expect(fit).not.toHaveBeenCalled();

    resize(1000, 500);
    expect(fit).toHaveBeenCalledTimes(1);
    expect(fit).toHaveBeenCalledWith({ width: 1000, height: 500 }, { width: 1000, height: 500 });
    expect(camera.getState().scale).toBeGreaterThan(0.5);
  });

  it('после вписки обычный ресайз вид не перевписывает', () => {
    const camera = new Camera();
    const fit = vi.spyOn(camera, 'fitPage');
    mount(camera);
    resize(800, 600);
    resize(1200, 700);
    expect(fit).toHaveBeenCalledTimes(1);
  });

  it('ненулевая область вписывает сразу при монтировании', () => {
    size = { width: 800, height: 600 };
    const camera = new Camera();
    const fit = vi.spyOn(camera, 'fitPage');
    mount(camera);
    expect(fit).toHaveBeenCalledTimes(1);
  });
});
