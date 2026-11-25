import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import * as THREE from 'three';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { readBuildingViewerColors } from './building-viewer-colors';
import { buildViewerPlan } from './building-viewer-geometry';
import { createBuildingViewer, type IBuildingViewer } from './building-viewer-scene';

// WebGL в jsdom нет: рендерер - заглушка, которая запоминает сцену, чтобы прочитать материалы мешей.
const rendered: { scene: THREE.Scene | null } = { scene: null };
vi.mock('three', async (importOriginal) => {
  const actual = await importOriginal<typeof THREE>();
  class FakeRenderer {
    readonly domElement = document.createElement('canvas');
    setPixelRatio(): void {}
    setClearColor(): void {}
    setSize(): void {}
    render(scene: THREE.Scene): void {
      rendered.scene = scene;
    }
    dispose(): void {}
    forceContextLoss(): void {}
  }
  return { ...actual, WebGLRenderer: FakeRenderer };
});

const rect = (x0: number, y0: number, x1: number, y1: number): number[][] => [
  [x0, y0],
  [x1, y0],
  [x1, y1],
  [x0, y1],
];

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
  walls: [{ id: 'w1', kind: 'masonry', shell: rect(0, 0, 10000, 200) }],
  windows: [
    {
      opening_id: 'accepted',
      shell: rect(3000, 0, 4000, 200),
      sill_z_bottom_mm: 0,
      glass_z_bottom_mm: 900,
      glass_z_top_mm: 2400,
      lintel_z_top_mm: 2800,
      accepted: true,
      source: 'facade',
    },
    {
      opening_id: 'candidate',
      shell: rect(6000, 0, 7000, 200),
      sill_z_bottom_mm: 0,
      glass_z_bottom_mm: 900,
      glass_z_top_mm: 2400,
      lintel_z_top_mm: 2800,
      accepted: false,
      source: 'facade',
    },
  ],
};

/** Непрозрачность мешей этажей (у вспомогательных объектов сцены ключа этажа нет). */
const opacities = (): number[] => {
  const found: number[] = [];
  rendered.scene?.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || typeof object.userData.floorKey !== 'string') return;
    found.push((object.material as THREE.MeshLambertMaterial).opacity);
  });
  return found.sort((x, y) => x - y);
};

describe('просмотрщик объекта: окна', () => {
  let host: HTMLDivElement;
  let viewer: IBuildingViewer;

  beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    viewer = createBuildingViewer(host, {
      reducedMotion: true,
      onHover: () => undefined,
      onSelect: () => undefined,
      onOpenDetail: () => undefined,
    });
    const plan = buildViewerPlan([FLOOR]);
    if (plan === null) throw new Error('план не построен');
    viewer.setPlan(plan, readBuildingViewerColors());
    viewer.setStyle(null, null);
  });

  afterEach(() => {
    viewer.dispose();
    host.remove();
    rendered.scene = null;
  });

  it('стекло принятой высоты полупрозрачно, стекло-кандидат бледнее', async () => {
    await vi.waitFor(() => expect(rendered.scene).not.toBeNull());
    // Плита, кладка и подоконная часть непрозрачны; стекло - 0.5, кандидат - 0.22.
    expect(opacities()).toEqual([0.22, 0.5, 1, 1, 1]);
  });

  it('выбранный этаж: стекло остаётся прозрачным, как и было', async () => {
    await vi.waitFor(() => expect(rendered.scene).not.toBeNull());
    viewer.setStyle('j1:0:0', null);
    await vi.waitFor(() => expect(opacities().length).toBe(5));
    expect(opacities().slice(0, 2)).toEqual([0.22, 0.5]);
  });
});
