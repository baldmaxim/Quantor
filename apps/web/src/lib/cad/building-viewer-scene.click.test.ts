import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import type * as THREE from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { buildViewerPlan } from './building-viewer-geometry';
import { readBuildingViewerColors } from './building-viewer-colors';
import { createBuildingViewer, type IBuildingViewer, type IBuildingViewerOptions } from './building-viewer-scene';

// WebGL в jsdom нет: renderer подменяется заглушкой, камера, OrbitControls и луч - настоящие.
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

const rect = (x0: number, y0: number, x1: number, y1: number): number[][] => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
];

const FLOOR_KEY = 'j1:0:0';

const FLOOR: CadBuilding3dFloorRead = {
  job_id: 'j1',
  revision_id: 'r1',
  document_id: 'd1',
  page_index: 0,
  view: 0,
  label: '1 этаж',
  elevation_known: true,
  base_z_mm: 0,
  floor_height_mm: 3000,
  floor_height_known: true,
  slab_thickness_mm: 200,
  slab_thickness_known: true,
  outline: rect(0, 0, 10000, 6000),
  outline_source: 'slab',
  bbox: [0, 0, 10000, 6000],
  corps: null,
  section: null,
  group_key: 'none',
  group_label: 'Корпус не указан',
  offset_mm: [0, 0],
  alignment: 'reference',
  alignment_axes: [],
  alignment_message: null,
  // Одна крупная стена на весь контур: луч в центр экрана попадает в её верх.
  walls: [{ id: 'w1', kind: 'masonry', shell: rect(0, 0, 10000, 6000) }],
};

describe('просмотрщик объекта: щелчок по этажу', () => {
  let host: HTMLDivElement;
  let viewer: IBuildingViewer;
  let canvas: HTMLCanvasElement;
  let now = 0;
  const onSelect = vi.fn<IBuildingViewerOptions['onSelect']>();
  const onOpenDetail = vi.fn<IBuildingViewerOptions['onOpenDetail']>();

  // Центр холста - в стену этажа; угол - мимо здания.
  const click = (x = 400, y = 300): void => {
    canvas.dispatchEvent(pointer('pointerdown', x, y, 1));
    canvas.dispatchEvent(pointer('pointerup', x, y));
  };

  beforeEach(() => {
    onSelect.mockReset();
    onOpenDetail.mockReset();
    now = 1000;
    vi.spyOn(performance, 'now').mockImplementation(() => now);
    host = document.createElement('div');
    document.body.appendChild(host);
    viewer = createBuildingViewer(host, {
      reducedMotion: true,
      onHover: () => undefined,
      onSelect,
      onOpenDetail,
    });
    canvas = host.querySelector('canvas') as HTMLCanvasElement;
    canvas.getBoundingClientRect = () => new DOMRect(0, 0, 800, 600);
    canvas.setPointerCapture = () => undefined;
    canvas.releasePointerCapture = () => undefined;
    canvas.hasPointerCapture = () => false;
    const plan = buildViewerPlan([FLOOR]);
    if (plan === null) throw new Error('план не построен');
    viewer.setPlan(plan, readBuildingViewerColors());
    viewer.setStyle(null, null);
  });

  afterEach(() => {
    viewer.dispose();
    host.remove();
    vi.restoreAllMocks();
  });

  it('щелчок по этажу выбирает его, повторный - снимает выбор', () => {
    click();
    expect(onSelect).toHaveBeenLastCalledWith(FLOOR_KEY);
    // Родитель применил выбор: сцена знает выбранный этаж.
    viewer.setStyle(FLOOR_KEY, null);
    now += 2000;
    click();
    expect(onSelect).toHaveBeenLastCalledWith(null);
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(onOpenDetail).not.toHaveBeenCalled();
  });

  it('щелчок в пустоту снимает выбор этажа; без выбора ничего не шлёт', () => {
    click(2, 2);
    expect(onSelect).not.toHaveBeenCalled();
    viewer.setStyle(FLOOR_KEY, null);
    click(2, 2);
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(null);
  });

  it('быстрый второй щелчок по тому же этажу - двойной, открывает этаж, а не снимает выбор', () => {
    click();
    viewer.setStyle(FLOOR_KEY, null);
    now += 100;
    click();
    expect(onOpenDetail).toHaveBeenCalledExactlyOnceWith(FLOOR_KEY);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
