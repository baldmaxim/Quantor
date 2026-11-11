import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { buildConstructionIndex, buildShapes } from '@/lib/cad/constructions';
import { construction } from '@/lib/cad/constructions-fixtures';
import { Camera } from '@/lib/viewer/camera';

import { CadConstructionPicker } from './CadConstructionPicker';

// Лист 1000 x 1000 при масштабе 1 и нулевом смещении: пиксель = 1/1000 листа.
// Стена: x 100..600, y 488..500 px.
const PAGE = { width: 1000, height: 1000 };
const FRAME = { originX: 100, originY: 500, mmPerPt: 10 };

const press = (target: Element, x: number, y: number, type: 'pointerDown' | 'pointerUp') =>
  fireEvent[type](target, { pointerId: 1, clientX: x, clientY: y, button: 0, pointerType: 'mouse' });

const mount = (disabled = false) => {
  const camera = new Camera();
  const onPick = vi.fn();
  const onDismiss = vi.fn();
  const index = buildConstructionIndex(buildShapes([construction({ id: 'wall' })], FRAME, PAGE));
  render(
    <div data-testid="container">
      <div data-testid="viewport" />
      <div data-testid="floating" />
      <CadConstructionPicker
        camera={camera}
        page={PAGE}
        index={index}
        onPick={onPick}
        onDismiss={onDismiss}
        popover={null}
        disabled={disabled}
      />
    </div>,
  );
  return { camera, onPick, onDismiss, viewport: screen.getByTestId('viewport') };
};

describe('CadConstructionPicker: выбор щелчком', () => {
  beforeEach(() => {
    HTMLElement.prototype.setPointerCapture = vi.fn();
    HTMLElement.prototype.releasePointerCapture = vi.fn();
  });

  it('щелчок по конструкции отдаёт её и точку клика', () => {
    const { viewport, onPick } = mount();
    press(viewport, 300, 494, 'pointerDown');
    press(viewport, 302, 495, 'pointerUp');
    expect(onPick).toHaveBeenCalledWith('wall', { x: 302, y: 495 });
  });

  it('щелчок по пустому месту снимает выбор (id = null)', () => {
    const { viewport, onPick } = mount();
    press(viewport, 800, 800, 'pointerDown');
    press(viewport, 800, 800, 'pointerUp');
    expect(onPick).toHaveBeenCalledWith(null, { x: 800, y: 800 });
  });

  it('перетаскивание (4 px и больше) - панорама: выбора нет, карточка закрывается', () => {
    const { viewport, onPick, onDismiss } = mount();
    press(viewport, 300, 494, 'pointerDown');
    press(viewport, 320, 494, 'pointerUp');
    expect(onPick).not.toHaveBeenCalled();
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('событие не от холста (плавающее окно) игнорируется', () => {
    const { onPick } = mount();
    const floating = screen.getByTestId('floating');
    press(floating, 300, 494, 'pointerDown');
    press(floating, 300, 494, 'pointerUp');
    expect(onPick).not.toHaveBeenCalled();
  });

  it('выбор приостановлен - щелчок ничего не делает', () => {
    const { viewport, onPick } = mount(true);
    press(viewport, 300, 494, 'pointerDown');
    press(viewport, 300, 494, 'pointerUp');
    expect(onPick).not.toHaveBeenCalled();
  });

  it('колесо и движение камеры закрывают карточку', async () => {
    const { viewport, camera, onDismiss } = mount();
    fireEvent.wheel(viewport, { deltaY: -100 });
    expect(onDismiss).toHaveBeenCalledTimes(1);
    camera.panBy(10, 10);
    await waitFor(() => expect(onDismiss.mock.calls.length).toBeGreaterThan(1));
  });
});
