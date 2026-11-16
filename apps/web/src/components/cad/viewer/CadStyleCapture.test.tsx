import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Camera } from '@/lib/viewer/camera';

import { CadStyleCapture } from './CadStyleCapture';

const PAGE = { width: 1000, height: 1000 };

const tap = (layer: HTMLElement, x: number, y: number) => {
  const init = { pointerId: 1, clientX: x, clientY: y, button: 0, pointerType: 'mouse' };
  fireEvent.pointerDown(layer, init);
  fireEvent.pointerUp(layer, init);
};

describe('CadStyleCapture', () => {
  beforeEach(() => {
    HTMLElement.prototype.setPointerCapture = vi.fn();
    HTMLElement.prototype.releasePointerCapture = vi.fn();
    HTMLElement.prototype.hasPointerCapture = vi.fn(() => false);
    HTMLCanvasElement.prototype.getContext = vi.fn(() => null);
  });
  afterEach(() => vi.restoreAllMocks());

  it('щелчок отдаёт точку в долях листа; мимо страницы - ничего; Esc выходит', () => {
    const onSample = vi.fn();
    const onExit = vi.fn();
    render(
      <CadStyleCapture
        camera={new Camera()}
        page={PAGE}
        samples={[]}
        onSample={onSample}
        onExit={onExit}
      />,
    );
    const layer = screen.getByTestId('style-capture');
    tap(layer, 250, 500);
    expect(onSample).toHaveBeenCalledWith({ x: 0.25, y: 0.5 });
    tap(layer, 1500, 500);
    expect(onSample).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  const mount = () => {
    const onSample = vi.fn();
    const onExit = vi.fn();
    render(
      <CadStyleCapture camera={new Camera()} page={PAGE} samples={[]} onSample={onSample} onExit={onExit} />,
    );
    return { layer: screen.getByTestId('style-capture'), onSample, onExit };
  };

  it('жест дальше 5 px - панорама, образца нет', () => {
    const { layer, onSample } = mount();
    const init = { pointerId: 1, button: 0, pointerType: 'mouse' };
    fireEvent.pointerDown(layer, { ...init, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(layer, { ...init, clientX: 120, clientY: 100 });
    fireEvent.pointerUp(layer, { ...init, clientX: 120, clientY: 100 });
    expect(onSample).not.toHaveBeenCalled();
  });

  it('Esc в поле ввода или при открытом диалоге режим не закрывает', () => {
    const { onExit } = mount();
    const input = document.createElement('input');
    document.body.append(input);
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onExit).not.toHaveBeenCalled();
    input.remove();

    const dialog = document.createElement('div');
    dialog.setAttribute('role', 'dialog');
    document.body.append(dialog);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onExit).not.toHaveBeenCalled();
    dialog.remove();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onExit).toHaveBeenCalledTimes(1);
  });
});
