import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { buildFloor } from './building-viewer-floor';
import { buildViewerPlan } from './building-viewer-geometry';

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
      glass_z_top_mm: 2800,
      lintel_z_top_mm: 2800,
      accepted: false,
      source: 'facade',
    },
  ],
};

const entryOf = (floor: CadBuilding3dFloorRead) => {
  const plan = buildViewerPlan([floor]);
  const spec = plan?.floors[0];
  if (plan === null || spec === undefined) throw new Error('план не построен');
  const entry = buildFloor(spec, 0);
  if (entry === null) throw new Error('этаж не построен');
  return { entry, spec };
};

const yRange = (mesh: { geometry: { computeBoundingBox: () => void; boundingBox: { min: { y: number }; max: { y: number } } | null } }) => {
  mesh.geometry.computeBoundingBox();
  const box = mesh.geometry.boundingBox;
  if (box === null) throw new Error('нет габарита');
  return [box.min.y, box.max.y] as const;
};

describe('окна этажа в мешах просмотрщика', () => {
  it('подоконная часть и перемычка - один меш, стекло принятых высот и кандидатов - отдельные', () => {
    const { entry } = entryOf(FLOOR);
    expect([...entry.meshes.keys()].sort()).toEqual(['glass', 'glassCandidate', 'masonry', 'sill', 'slab']);
    for (const mesh of entry.meshes.values()) expect(mesh.userData.floorKey).toBe(entry.key);
  });

  it('подоконная часть - от верха плиты, перемычка - до верха стены, стекло - между', () => {
    const { entry, spec } = entryOf(FLOOR);
    const sill = entry.meshes.get('sill');
    const glass = entry.meshes.get('glass');
    const candidate = entry.meshes.get('glassCandidate');
    if (sill === undefined || glass === undefined || candidate === undefined) throw new Error('нет мешей окон');
    const [sillMin, sillMax] = yRange(sill);
    expect(sillMin).toBeCloseTo(spec.slabTop);
    expect(sillMax).toBeCloseTo(spec.wallTop);
    const windowSpec = spec.windows.find((item) => item.id === 'accepted');
    const [glassMin, glassMax] = yRange(glass);
    expect(glassMin).toBeCloseTo(windowSpec?.glassBottom ?? NaN);
    expect(glassMax).toBeCloseTo(windowSpec?.glassTop ?? NaN);
    // Окно кандидата без перемычки (верх окна = верх стены): стекло доходит до верха стены.
    expect(yRange(candidate)[1]).toBeCloseTo(spec.wallTop);
  });

  it('без окон мешей окон нет', () => {
    const { entry } = entryOf({ ...FLOOR, windows: null });
    expect(entry.meshes.has('sill')).toBe(false);
    expect(entry.meshes.has('glass')).toBe(false);
    expect(entry.meshes.has('glassCandidate')).toBe(false);
  });
});

const xRange = (mesh: { geometry: { computeBoundingBox: () => void; boundingBox: { min: { x: number }; max: { x: number } } | null } }) => {
  mesh.geometry.computeBoundingBox();
  const box = mesh.geometry.boundingBox;
  if (box === null) throw new Error('нет габарита');
  return [box.min.x, box.max.x] as const;
};

describe('плита из нескольких частей в мешах просмотрщика', () => {
  const bare = { ...FLOOR, walls: [], windows: null };

  it('плита и объём строятся по всем частям', () => {
    const { entry } = entryOf({ ...bare, outline_parts: [rect(14000, 0, 16000, 3000)] });
    for (const part of ['slab', 'volume'] as const) {
      const mesh = entry.meshes.get(part);
      if (mesh === undefined) throw new Error(`нет меша ${part}`);
      const [min, max] = xRange(mesh);
      expect(max - min).toBeCloseTo(16);
    }
  });

  it('без outline_parts - только основной контур', () => {
    const { entry } = entryOf(bare);
    const slab = entry.meshes.get('slab');
    if (slab === undefined) throw new Error('нет плиты');
    const [min, max] = xRange(slab);
    expect(max - min).toBeCloseTo(10);
  });
});
