import type { MepScenarioRead, Vertex } from '@quantor/api-client';

import { originOf, type NetworkOrigin } from '@/lib/mep/trace';
import type { NormalizedPoint, SheetPlacement } from '@/lib/viewer/coordinates';
import { toScreenPoint } from '@/lib/viewer/coordinates';
import { hitTestMeasurements, type OverlayMeasurement } from '@/lib/viewer/measurement-overlay';

/**
 * Лист эксперимента на Canvas2D (ADR-0015): evidence П и сгенерированная сеть в одних
 * нормализованных координатах листа. Попадание указателя считает существующий `hitTestMeasurements`.
 *
 * Слой evidence и слой сети — разные фигуры. Сгенерированная геометрия рисуется только своим
 * стилем происхождения и никогда стилем «наблюдено на П».
 */

export type MepLayer = 'evidence' | 'network';
export type ShapeStyle = 'observed' | 'original' | NetworkOrigin;

export interface IMepShape extends OverlayMeasurement {
  readonly layer: MepLayer;
  readonly style: ShapeStyle;
}

/** Штрих линии по происхождению: форма различима и без цвета. */
export const DASH: Readonly<Record<ShapeStyle, readonly number[]>> = {
  observed: [],
  original: [3, 3],
  evidence: [],
  human: [],
  rule: [8, 4],
  prior: [2, 4],
  unresolved: [8, 3, 2, 3],
};

/** Токены темы для каждого стиля; hex в компоненте запрещён. */
export const STYLE_TOKEN: Readonly<Record<ShapeStyle, string>> = {
  // Наблюдённое на П — синим и прямоугольниками; сгенерированное по нему — другим цветом и кругами.
  observed: '--region-text',
  // Исходное предсказание модели до исправления человеком — серый пунктир, не evidence.
  original: '--muted',
  evidence: '--success',
  human: '--text',
  rule: '--region-image',
  prior: '--region-stamp',
  unresolved: '--sheet-ink-danger',
};

const A_SERIES = 1 / Math.SQRT2;

/** Высота к ширине листа: по снимку калибровки, иначе пропорция A-формата. */
export const sheetAspect = (scenario: MepScenarioRead): number => {
  const snapshot = scenario.evidence.sheets[0]?.calibration;
  if (!snapshot) {
    return A_SERIES;
  }
  const ratio = Number(snapshot.display_height_pt) / Number(snapshot.display_width_pt);
  return Number.isFinite(ratio) && ratio > 0 ? ratio : A_SERIES;
};

const pair = (value: readonly number[]): NormalizedPoint => ({
  x: value[0] ?? 0,
  y: value[1] ?? 0,
});

const planar = (vertex: Vertex): NormalizedPoint | null =>
  vertex.x === null || vertex.x === undefined || vertex.y === null || vertex.y === undefined
    ? null
    : { x: vertex.x, y: vertex.y };

export const evidenceShapes = (scenario: MepScenarioRead): readonly IMepShape[] =>
  scenario.evidence.elements.map((element) => {
    const base = {
      id: element.id,
      layer: 'evidence' as const,
      style: 'observed' as const,
      colorKey: 'observed',
    };
    const geometry = element.geometry;
    switch (geometry.kind) {
      case 'point':
        return { ...base, geometryType: 'count', points: [pair(geometry.point)] };
      case 'bbox': {
        const [x0, y0] = geometry.min;
        const [x1, y1] = geometry.max;
        const ring = [
          { x: x0, y: y0 },
          { x: x1, y: y0 },
          { x: x1, y: y1 },
          { x: x0, y: y1 },
        ];
        return { ...base, geometryType: 'polygon', points: ring };
      }
      case 'polyline':
        return { ...base, geometryType: 'polyline', points: geometry.points.map(pair) };
      case 'polygon':
        return {
          ...base,
          geometryType: 'polygon',
          points: geometry.outer.map(pair),
          holes: (geometry.holes ?? []).map((ring) => ring.map(pair)),
        };
    }
  });

/**
 * Исходное предсказание модели для исправленного человеком evidence: призрак на листе рядом с
 * исправленной геометрией. Идентификатор с суффиксом, чтобы выбор вёл к самому элементу.
 */
export const ORIGINAL_SUFFIX = '#original';

export const originalShape = (scenario: MepScenarioRead, elementId: string): IMepShape | null => {
  const element = scenario.evidence.elements.find((item) => item.id === elementId);
  if (!element?.original) {
    return null;
  }
  const [shape] = evidenceShapes({
    ...scenario,
    evidence: {
      ...scenario.evidence,
      elements: [{ ...element, geometry: element.original.geometry }],
    },
  });
  return shape
    ? { ...shape, id: `${element.id}${ORIGINAL_SUFFIX}`, style: 'original', colorKey: 'original' }
    : null;
};

/**
 * Сеть на листе. Узлы и вершины без плановых координат (только отметка или уровень) на плане не
 * рисуются — у них нет места на листе, и придумывать его нельзя.
 */
export const networkShapes = (scenario: MepScenarioRead): readonly IMepShape[] => {
  const shapes: IMepShape[] = [];
  for (const segment of scenario.network.segments ?? []) {
    const points = segment.path.map(planar).filter((p): p is NormalizedPoint => p !== null);
    if (points.length >= 2) {
      const style = originOf(segment.derivation);
      shapes.push({
        id: segment.id,
        layer: 'network',
        style,
        colorKey: style,
        geometryType: 'polyline',
        points,
      });
    }
  }
  for (const node of scenario.network.nodes) {
    const point = planar(node.position);
    if (point) {
      const style = originOf(node.derivation);
      shapes.push({
        id: node.id,
        layer: 'network',
        style,
        colorKey: style,
        geometryType: 'count',
        points: [point],
      });
    }
  }
  return shapes;
};

export const hitTestShapes = (
  shapes: readonly IMepShape[],
  point: NormalizedPoint,
  placement: SheetPlacement,
): IMepShape | null => {
  const hit = hitTestMeasurements(shapes, point, placement, 8);
  return hit ? (shapes.find((shape) => shape.id === hit.id) ?? null) : null;
};

export interface IDrawState {
  readonly shapes: readonly IMepShape[];
  readonly dimmed: ReadonlySet<MepLayer>;
  readonly selectedId: string | null;
  readonly relatedIds: ReadonlySet<string>;
  readonly colors: Readonly<Record<ShapeStyle | 'page' | 'pageInk' | 'focus', string>>;
}

export const drawSheet = (
  context: CanvasRenderingContext2D,
  placement: SheetPlacement,
  state: IDrawState,
  devicePixelRatio: number,
): void => {
  context.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  context.clearRect(0, 0, context.canvas.width, context.canvas.height);
  context.fillStyle = state.colors.page;
  context.fillRect(placement.x, placement.y, placement.width, placement.height);
  context.strokeStyle = state.colors.pageInk;
  context.globalAlpha = 0.35;
  context.lineWidth = 1;
  context.strokeRect(placement.x, placement.y, placement.width, placement.height);

  // Невыбранное — снизу, связанное с выбором — выше, выбранное — сверху.
  const rank = (shape: IMepShape) =>
    shape.id === state.selectedId ? 2 : state.relatedIds.has(shape.id) ? 1 : 0;
  const ordered = [...state.shapes].sort((a, b) => rank(a) - rank(b));

  for (const shape of ordered) {
    const emphasis = rank(shape);
    const color = state.colors[shape.style];
    context.globalAlpha = state.dimmed.has(shape.layer) && emphasis === 0 ? 0.25 : 1;
    context.strokeStyle = color;
    context.fillStyle = color;
    context.setLineDash([...DASH[shape.style]]);
    context.lineWidth = emphasis === 2 ? 3.5 : emphasis === 1 ? 2.5 : 1.75;
    const screen = shape.points.map((point) => toScreenPoint(point, placement));

    if (shape.geometryType === 'count') {
      const [center] = screen;
      if (!center) continue;
      const size = emphasis === 2 ? 7 : 5;
      context.beginPath();
      if (shape.layer === 'evidence') {
        context.rect(center.x - size, center.y - size, size * 2, size * 2);
        context.stroke();
      } else {
        context.arc(center.x, center.y, size, 0, Math.PI * 2);
        context.fill();
      }
    } else {
      context.beginPath();
      screen.forEach((point, index) =>
        index === 0 ? context.moveTo(point.x, point.y) : context.lineTo(point.x, point.y),
      );
      if (shape.geometryType === 'polygon') context.closePath();
      context.stroke();
    }

    if (emphasis === 2) {
      context.setLineDash([]);
      context.globalAlpha = 0.9;
      context.strokeStyle = state.colors.focus;
      context.lineWidth = 1;
      const xs = screen.map((p) => p.x);
      const ys = screen.map((p) => p.y);
      const pad = 10;
      context.strokeRect(
        Math.min(...xs) - pad,
        Math.min(...ys) - pad,
        Math.max(...xs) - Math.min(...xs) + pad * 2,
        Math.max(...ys) - Math.min(...ys) + pad * 2,
      );
    }
  }
  context.globalAlpha = 1;
  context.setLineDash([]);
};
