/**
 * Общее для замера просмотрщика: статистика, размеры холстов и детерминированные данные.
 */

import type { NormalizedPoint } from '@/lib/viewer/coordinates';
import type { OverlayMeasurement } from '@/lib/viewer/measurement-overlay';
import type { OverlayRegion } from '@/lib/viewer/overlay';

export interface Stats {
  readonly count: number;
  readonly median: number;
  readonly p95: number;
  readonly max: number;
  readonly mean: number;
}

export interface CanvasSize {
  readonly width: number;
  readonly height: number;
  readonly megapixels: number;
  readonly rgbaMiB: number;
}

export interface Viewport {
  readonly width: number;
  readonly height: number;
}

export const stats = (samples: readonly number[]): Stats => {
  const sorted = [...samples].sort((a, b) => a - b);
  const pick = (fraction: number): number =>
    sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))] ?? 0;
  const sum = sorted.reduce((total, value) => total + value, 0);
  return {
    count: sorted.length,
    median: pick(0.5),
    p95: pick(0.95),
    max: sorted[sorted.length - 1] ?? 0,
    mean: sorted.length ? sum / sorted.length : 0,
  };
};

/** RGBA — четыре байта на пиксель: столько занимает холст независимо от содержимого. */
export const sized = (width: number, height: number): CanvasSize => ({
  width,
  height,
  megapixels: (width * height) / 1e6,
  rgbaMiB: (width * height * 4) / (1024 * 1024),
});

export const devicePixelRatio = (): number => window.devicePixelRatio || 1;

export const errorText = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

export const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

export const waitFor = async (predicate: () => boolean, timeoutMs: number): Promise<boolean> => {
  const deadline = performance.now() + timeoutMs;
  while (performance.now() < deadline) {
    if (predicate()) return true;
    await sleep(50);
  }
  return predicate();
};

/** Детерминированный генератор: Math.random сделал бы соседние замеры несравнимыми. */
const sequence = (seed: number): (() => number) => {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
};

const TYPES: readonly OverlayMeasurement['geometryType'][] = [
  'count',
  'line',
  'polyline',
  'polygon',
];

const VERTICES: Readonly<Record<OverlayMeasurement['geometryType'], number>> = {
  count: 1,
  line: 2,
  polyline: 6,
  polygon: 5,
};

/** Та же смесь фигур и тот же seed, что в замере Stage 2A, — числа сопоставимы. */
export const buildMeasurements = (total: number): OverlayMeasurement[] => {
  const next = sequence(20260909);
  return Array.from({ length: total }, (_, index) => {
    const geometryType = TYPES[index % TYPES.length] ?? 'line';
    const originX = next() * 0.9;
    const originY = next() * 0.9;
    const points: NormalizedPoint[] = Array.from({ length: VERTICES[geometryType] }, () => ({
      x: originX + next() * 0.08,
      y: originY + next() * 0.08,
    }));
    return {
      id: `m-${index}`,
      geometryType,
      points,
      colorKey: index % 3 === 0 ? 'accent' : 'danger',
    };
  });
};

/** Области распознавания: прямоугольники трёх типов, как в пакете legacy-v1. */
export const buildRegions = (total: number): OverlayRegion[] => {
  const next = sequence(20260911);
  const kinds = ['text', 'image', 'stamp'];
  return Array.from({ length: total }, (_, index) => {
    const x = next() * 0.9;
    const y = next() * 0.9;
    return {
      id: `r-${index}`,
      blockType: kinds[index % kinds.length] ?? 'text',
      shapeType: 'rectangle' as const,
      coords: [x, y, x + 0.01 + next() * 0.06, y + 0.01 + next() * 0.04] as const,
      polygon: null,
    };
  });
};
