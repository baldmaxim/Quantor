/**
 * Замер слоя измерений в настоящем браузере.
 *
 * Отрисовка меряется на живом Canvas2D, а не на подставном контексте: подставной измерил
 * бы обход наших структур и умолчал бы о растеризации, то есть о том, из-за чего слой
 * тормозит на самом деле.
 *
 * Каждый кадр заканчивается чтением одного пикселя. Без этого браузер вправе отложить
 * работу, и замер показал бы время постановки команд в очередь вместо времени рисования.
 *
 * Ни одной цели вроде «60 кадров в секунду» здесь нет. Сначала измеренная база, вывод —
 * потом (ADR-0015).
 */

import type { NormalizedPoint, SheetPlacement } from '@/lib/viewer/coordinates';
import type {
  MeasurementOverlayState,
  MeasurementOverlayStyle,
  OverlayMeasurement,
} from '@/lib/viewer/measurement-overlay';
import { drawMeasurements, hitTestMeasurements } from '@/lib/viewer/measurement-overlay';

export interface BenchSample {
  readonly primitives: number;
  readonly vertices: number;
  readonly frames: number;
  readonly medianMs: number;
  readonly minMs: number;
  readonly p95Ms: number;
  /** Что слой отчитался нарисовать: замер пустого экрана выглядел бы отлично. */
  readonly drawn: number;
}

export interface HeapSnapshot {
  readonly usedBytes: number;
  readonly totalBytes: number;
}

export interface OverlayBenchResult {
  readonly canvas: { readonly cssWidth: number; readonly cssHeight: number };
  readonly devicePixelRatio: number;
  readonly userAgent: string;
  readonly draw: readonly BenchSample[];
  readonly hitTest: readonly BenchSample[];
  /** Стоимость пустого кадра: очистка холста и чтение пикселя, без единой фигуры. */
  readonly overhead: BenchSample;
  readonly heapBefore: HeapSnapshot | null;
  readonly heapAfter: HeapSnapshot | null;
}

interface MemoryInfo {
  readonly usedJSHeapSize: number;
  readonly totalJSHeapSize: number;
}

const heap = (): HeapSnapshot | null => {
  const info = (performance as Performance & { memory?: MemoryInfo }).memory;
  return info ? { usedBytes: info.usedJSHeapSize, totalBytes: info.totalJSHeapSize } : null;
};

/**
 * Детерминированный генератор.
 *
 * Math.random сделал бы соседние прогоны несравнимыми: разница в числах читалась бы как
 * разница в производительности.
 */
const sequence = (seed: number): (() => number) => {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
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

/** Смесь фигур в тех же долях, что и на рабочем листе: счёта много, площадей мало. */
const buildMeasurements = (total: number): OverlayMeasurement[] => {
  const next = sequence(20260909);
  const result: OverlayMeasurement[] = [];

  for (let index = 0; index < total; index += 1) {
    const geometryType = TYPES[index % TYPES.length] ?? 'line';
    const originX = next() * 0.9;
    const originY = next() * 0.9;
    const points: NormalizedPoint[] = [];

    for (let vertex = 0; vertex < VERTICES[geometryType]; vertex += 1) {
      points.push({ x: originX + next() * 0.08, y: originY + next() * 0.08 });
    }

    result.push({
      id: `m-${index}`,
      geometryType,
      points,
      colorKey: index % 3 === 0 ? 'accent' : 'danger',
    });
  }

  return result;
};

const countVertices = (measurements: readonly OverlayMeasurement[]): number =>
  measurements.reduce((sum, item) => sum + item.points.length, 0);

const summarise = (samples: number[]): { median: number; min: number; p95: number } => {
  const sorted = [...samples].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 0
      ? ((sorted[middle - 1] ?? 0) + (sorted[middle] ?? 0)) / 2
      : (sorted[middle] ?? 0);
  const index = Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95));

  return { median, min: sorted[0] ?? 0, p95: sorted[index] ?? 0 };
};

const STYLE: MeasurementOverlayStyle = {
  colors: { accent: '#2f6fed', danger: '#d64545' },
  fallbackColor: '#888888',
};

const stateFor = (measurements: readonly OverlayMeasurement[]): MeasurementOverlayState => ({
  measurements,
  selectedId: measurements[0]?.id ?? null,
  hoveredId: measurements[1]?.id ?? null,
  draft: [],
  draftType: null,
  draftHover: null,
  dragOverride: null,
});

export const runOverlayBenchmark = (
  canvas: HTMLCanvasElement,
  sizes: readonly number[],
  frames: number,
): OverlayBenchResult => {
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas2D недоступен в этом браузере');

  const ratio = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;
  canvas.width = Math.round(cssWidth * ratio);
  canvas.height = Math.round(cssHeight * ratio);

  const placement: SheetPlacement = {
    x: 0,
    y: 0,
    width: cssWidth,
    height: cssHeight,
    rotation: 0,
  };

  const heapBefore = heap();
  const draw: BenchSample[] = [];
  const hitTest: BenchSample[] = [];

  // Пустой кадр меряется первым. Чтение пикселя само по себе стоит времени, и без этой
  // величины из результата нельзя вычесть цену самого замера.
  const empty = stateFor([]);
  for (let frame = 0; frame < 3; frame += 1) {
    drawMeasurements(context, placement, empty, STYLE, ratio);
    context.getImageData(0, 0, 1, 1);
  }

  const overheadSamples: number[] = [];
  for (let frame = 0; frame < frames; frame += 1) {
    const started = performance.now();
    drawMeasurements(context, placement, empty, STYLE, ratio);
    context.getImageData(0, 0, 1, 1);
    overheadSamples.push(performance.now() - started);
  }

  const overheadStats = summarise(overheadSamples);
  const overhead: BenchSample = {
    primitives: 0,
    vertices: 0,
    frames,
    medianMs: overheadStats.median,
    minMs: overheadStats.min,
    p95Ms: overheadStats.p95,
    drawn: 0,
  };

  for (const size of sizes) {
    const measurements = buildMeasurements(size);
    const state = stateFor(measurements);
    const vertices = countVertices(measurements);
    let drawn = 0;

    // Прогрев: первый кадр оплачивает компиляцию и загрузку шрифтов слоя.
    for (let frame = 0; frame < 3; frame += 1) {
      drawn = drawMeasurements(context, placement, state, STYLE, ratio);
    }

    const drawSamples: number[] = [];
    for (let frame = 0; frame < frames; frame += 1) {
      const started = performance.now();
      drawn = drawMeasurements(context, placement, state, STYLE, ratio);
      // Чтение пикселя заставляет браузер закончить рисование до возврата.
      context.getImageData(0, 0, 1, 1);
      drawSamples.push(performance.now() - started);
    }

    const drawStats = summarise(drawSamples);
    draw.push({
      primitives: size,
      vertices,
      frames,
      medianMs: drawStats.median,
      minMs: drawStats.min,
      p95Ms: drawStats.p95,
      drawn,
    });

    // Попадание — чистая арифметика, растеризация в него не входит. Меряется отдельно:
    // именно оно выполняется на каждое движение мыши.
    const probe: NormalizedPoint = { x: 0.5, y: 0.5 };
    for (let frame = 0; frame < 3; frame += 1) hitTestMeasurements(measurements, probe, placement);

    const hitSamples: number[] = [];
    for (let frame = 0; frame < frames; frame += 1) {
      const started = performance.now();
      hitTestMeasurements(measurements, probe, placement);
      hitSamples.push(performance.now() - started);
    }

    const hitStats = summarise(hitSamples);
    hitTest.push({
      primitives: size,
      vertices,
      frames,
      medianMs: hitStats.median,
      minMs: hitStats.min,
      p95Ms: hitStats.p95,
      drawn: 0,
    });
  }

  return {
    canvas: { cssWidth, cssHeight },
    devicePixelRatio: ratio,
    userAgent: navigator.userAgent,
    draw,
    hitTest,
    overhead,
    heapBefore,
    heapAfter: heap(),
  };
};
