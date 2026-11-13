import type * as THREE from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createFloor3dEngine, type IFloor3dEngine, type IFloor3dEngineOptions } from './floor3d-engine';
import { CLICK_SLOP_PX } from './floor3d-click';
import { floor3dFixture } from './floor3d-fixtures';
import { buildFloor3dPlan } from './floor3d-geometry';
import { buildFloor3dRoutes, readFloor3dRouteColors } from './floor3d-routes';
import { buildFloor3dScene, readFloor3dColors } from './floor3d-scene';

// WebGL в jsdom нет: renderer подменяется заглушкой, а камера, OrbitControls и обработчики указателя
// остаются настоящими - проверяется именно связка `start` у OrbitControls с выбором и снятием выбора.
vi.mock('three', async (importOriginal) => {
  const actual = await importOriginal<typeof THREE>();
  class FakeRenderer {
    readonly domElement = document.createElement('canvas');
    setPixelRatio(): void {}
    setClearColor(): void {}
    setSize(): void {}
    render(): void {}
    dispose(): void {}
    forceContextLoss(): void {}
  }
  return { ...actual, WebGLRenderer: FakeRenderer };
});

const pointer = (type: string, x: number, y: number, buttons = 0): Event =>
  Object.assign(new MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0, buttons }), {
    pointerId: 1,
    pointerType: 'mouse',
    isPrimary: true,
  });

describe('движок 3D этажа: щелчок и перетаскивание', () => {
  let host: HTMLDivElement;
  let engine: IFloor3dEngine;
  let canvas: HTMLCanvasElement;
  const onPick = vi.fn<IFloor3dEngineOptions['onPick']>();
  const onPickMep = vi.fn<IFloor3dEngineOptions['onPickMep']>();
  const onMove = vi.fn<IFloor3dEngineOptions['onMove']>();

  beforeEach(() => {
    onPick.mockReset();
    onPickMep.mockReset();
    onMove.mockReset();
    host = document.createElement('div');
    document.body.appendChild(host);
    engine = createFloor3dEngine(host, {
      reducedMotion: true,
      onPick,
      onPickMep,
      onMove,
      onMeasure: () => undefined,
      onSnap: () => undefined,
    });
    canvas = host.querySelector('canvas') as HTMLCanvasElement;
    canvas.getBoundingClientRect = () => new DOMRect(0, 0, 800, 600);
    canvas.setPointerCapture = () => undefined;
    canvas.releasePointerCapture = () => undefined;
    canvas.hasPointerCapture = () => false;
    engine.setModel(buildFloor3dScene(buildFloor3dPlan(floor3dFixture()), readFloor3dColors(), { showSlabCap: false }));
  });

  afterEach(() => {
    engine.dispose();
    host.remove();
  });

  it('щелчок без смещения не считается движением камеры, выбор приходит один раз', () => {
    // Раньше onMove вызывался уже на pointerdown (`start` OrbitControls) и гасил выбор до pointerup.
    canvas.dispatchEvent(pointer('pointerdown', 400, 300, 1));
    expect(onMove).not.toHaveBeenCalled();
    canvas.dispatchEvent(pointer('pointermove', 400 + CLICK_SLOP_PX, 300, 1));
    canvas.dispatchEvent(pointer('pointerup', 400, 300));
    expect(onMove).not.toHaveBeenCalled();
    expect(onPick).toHaveBeenCalledTimes(1);
  });

  it('перетаскивание дальше порога - одно «камера пошла» и никакого выбора', () => {
    canvas.dispatchEvent(pointer('pointerdown', 400, 300, 1));
    canvas.dispatchEvent(pointer('pointermove', 400 + CLICK_SLOP_PX + 2, 300, 1));
    canvas.dispatchEvent(pointer('pointermove', 460, 320, 1));
    canvas.dispatchEvent(pointer('pointerup', 460, 320));
    expect(onMove).toHaveBeenCalledTimes(1);
    expect(onPick).not.toHaveBeenCalled();
  });

  it('щелчок по трассе - onPickMep с индексом полилинии, без onPick', () => {
    const plan = buildFloor3dPlan(floor3dFixture());
    // Крупный воздуховод через центр этажа: центральный луч изометрии попадает в него раньше плиты.
    const routes = buildFloor3dRoutes(
      [
        {
          layer: 'M-OV-VMOP',
          pts: [
            [2000, 3000, 1500],
            [8000, 3000, 1500],
          ],
          shape: 'rect',
          w_mm: 3000,
          h_mm: 3000,
        },
      ],
      readFloor3dRouteColors(),
      { center: plan.center, baseZMm: 3000 },
    );
    engine.setRoutes(routes);
    for (const category of ['masonry', 'monolith', 'frame_partition', 'door'] as const) {
      engine.setCategoryVisible(category, false);
    }
    canvas.dispatchEvent(pointer('pointerdown', 400, 300, 1));
    canvas.dispatchEvent(pointer('pointerup', 400, 300));
    expect(onPickMep).toHaveBeenCalledWith({ kind: 'route', index: 0 }, { x: 400, y: 300 });
    expect(onPick).not.toHaveBeenCalled();
    // Слой скрыт - трасса в выбор не входит.
    routes.setLayerVisible('M-OV-VMOP', false);
    canvas.dispatchEvent(pointer('pointerdown', 400, 300, 1));
    canvas.dispatchEvent(pointer('pointerup', 400, 300));
    expect(onPickMep).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledTimes(1);
  });

  it('колесо - камера пошла', () => {
    canvas.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, clientX: 400, clientY: 300 }));
    expect(onMove).toHaveBeenCalledTimes(1);
  });
});
