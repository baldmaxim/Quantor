import type { CalcElement, CalcPolyline, TenderViewLayerRead } from '@quantor/api-client';

import { cadToNormalized, type ICadFrame, type IPageSize } from '@/lib/cad/frame';

import type { ITenderRef, ITenderSource } from './info';
import type { ITenderMark, ITenderPaintData, ITenderPath } from './painter';

/**
 * Геометрия слоя «Расчёты» в кадре вида: перевод в нормализованные координаты листа для наложения
 * на PDF (тот же путь, что у трасс движка, `lib/cad/frame.ts`). Координаты расчёта - мм DXF вида,
 * ось Y вверх (формат обмена, ADR-0051).
 */

/** Поля слоя, нужные для источника объектов: версия и репозиторий расчёта. */
export type TenderSourceFields = Pick<
  TenderViewLayerRead,
  'calc_id' | 'version_id' | 'title' | 'number' | 'label' | 'system' | 'discipline' | 'base_stale'
>;

/** Слой «Расчёты»: источник и геометрия на одном виде (вид листа или вид здания). */
export interface ITenderLayerData extends TenderSourceFields {
  readonly polylines: readonly CalcPolyline[];
  readonly elements: readonly CalcElement[];
}

/** Источник объектов слоя: версия и репозиторий расчёта. */
export const sourceOf = (layer: TenderSourceFields): ITenderSource => ({
  calcId: layer.calc_id,
  versionId: layer.version_id,
  title: layer.title,
  number: layer.number,
  label: layer.label,
  system: layer.system,
  discipline: layer.discipline,
  baseStale: layer.base_stale,
});

/** Подпись строки слоя в панели: «Отопление жилой части · №3 v3». */
export const layerTitle = (layer: Pick<TenderViewLayerRead, 'title' | 'number' | 'label'>): string =>
  `${layer.title} · №${layer.number} ${layer.label}`.trim();

const finite = (...values: readonly number[]): boolean => values.every(Number.isFinite);

/** Подпись `mark` показывается только у объектов, где она задана и не пуста. */
const markOf = (value: string | null | undefined): string | null =>
  value !== null && value !== undefined && value.trim() !== '' ? value.trim() : null;

const pathOf = (
  polyline: CalcPolyline,
  ref: ITenderRef,
  color: string,
  frame: ICadFrame,
  page: IPageSize,
): ITenderPath | null => {
  const flat: number[] = [];
  const bounds: [number, number, number, number] = [
    Number.POSITIVE_INFINITY,
    Number.POSITIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
    Number.NEGATIVE_INFINITY,
  ];
  for (const point of polyline.pts) {
    if (!finite(point[0], point[1])) continue;
    const [nx, ny] = cadToNormalized(frame, page, point[0], point[1]);
    flat.push(nx, ny);
    if (nx < bounds[0]) bounds[0] = nx;
    if (ny < bounds[1]) bounds[1] = ny;
    if (nx > bounds[2]) bounds[2] = nx;
    if (ny > bounds[3]) bounds[3] = ny;
  }
  if (flat.length < 2) return null;
  return {
    kind: polyline.kind,
    points: Float64Array.from(flat),
    bounds,
    label: markOf(polyline.mark),
    color,
    ref,
  };
};

const markOfElement = (
  element: CalcElement,
  ref: ITenderRef,
  color: string,
  frame: ICadFrame,
  page: IPageSize,
): ITenderMark | null => {
  const [x, y] = element.pos;
  if (!finite(x, y)) return null;
  const [nx, ny] = cadToNormalized(frame, page, x, y);
  // Направление оси на экране: ось Y листа смотрит вниз, ось DXF - вверх.
  let dx = 1;
  let dy = 0;
  if (element.axis) {
    const length = Math.hypot(element.axis[0], element.axis[1]);
    if (length > 0) {
      dx = element.axis[0] / length;
      dy = -element.axis[1] / length;
    }
  }
  return { type: element.type, x: nx, y: ny, dx, dy, label: markOf(element.mark), color, ref };
};

export interface ITenderPaintInput {
  /** Слои, которые показаны (скрытые отфильтрованы). */
  readonly layers: readonly ITenderLayerData[];
  readonly frame: ICadFrame;
  readonly page: IPageSize;
  /** Цвет системы по её коду (токен темы, уже прочитанный). */
  readonly colorOf: (system: string) => string;
  readonly accent: string;
  readonly halo: string;
  readonly selected: ITenderRef | null;
}

/** Данные наложения слоя «Расчёты»; `null` - рисовать нечего. */
export const buildTenderPaintData = (input: ITenderPaintInput): ITenderPaintData | null => {
  const { frame, page } = input;
  if (!(page.width > 0) || !(page.height > 0)) return null;
  const paths: ITenderPath[] = [];
  const marks: ITenderMark[] = [];
  for (const layer of input.layers) {
    const source = sourceOf(layer);
    const color = input.colorOf(layer.system);
    for (const polyline of layer.polylines) {
      const ref: ITenderRef = { source, object: { kind: 'polyline', data: polyline } };
      const path = pathOf(polyline, ref, color, frame, page);
      if (path !== null) paths.push(path);
    }
    for (const element of layer.elements) {
      const ref: ITenderRef = { source, object: { kind: 'element', data: element } };
      const mark = markOfElement(element, ref, color, frame, page);
      if (mark !== null) marks.push(mark);
    }
  }
  if (paths.length === 0 && marks.length === 0) return null;
  return {
    paths,
    marks,
    aspect: page.height / page.width,
    accent: input.accent,
    halo: input.halo,
    selected: input.selected,
  };
};
