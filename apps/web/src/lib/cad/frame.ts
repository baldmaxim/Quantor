/**
 * Кадр координат CAD: пересчёт геометрии DXF (мм) в систему просмотрщика.
 *
 * Движок называет кадр так: `pt = origin_pt + (x_mm, -y_mm) / mm_per_pdf_point`, где `pt` -
 * точки PDF от левого верхнего угла страницы уже после её поворота (display pt), а
 * `origin_pt` - положение начала координат DXF на странице. Просмотрщик хранит координаты
 * нормализованными от левого верхнего угла страницы, размер страницы берёт у отрисовщика в
 * тех же точках при масштабе 1 (ADR-0008). Поэтому здесь: делим на размер страницы и всё.
 * Поворот страницы повторно НЕ применяется - pdf.js применил `/Rotate` сам.
 *
 * Модуль без DOM и без React: ошибка здесь выглядит как «CAD не лёг на чертёж», и ловить её
 * нужно тестами, а не глазами.
 */

import type { CadFrameRead, CadPreviewPathRead } from '@quantor/api-client';

import type { NormalizedRect } from '@/lib/viewer/coordinates';

/** Подтверждённый кадр, готовый к вычислению. */
export interface ICadFrame {
  readonly originX: number;
  readonly originY: number;
  /** Миллиметров в одной точке PDF. */
  readonly mmPerPt: number;
}

/** Размер страницы в точках PDF при масштабе 1, как его видит отрисовщик. */
export interface IPageSize {
  readonly width: number;
  readonly height: number;
}

/** Охват в мм системы DXF: [minX, minY, maxX, maxY], ось Y вверх. */
export type CadBbox = readonly [number, number, number, number];

/** Путь предпросмотра в нормализованных координатах. */
export interface INormalizedPath {
  readonly layer: number;
  readonly closed: boolean;
  readonly fill: boolean;
  /** Плоский список x0, y0, x1, y1, … */
  readonly points: Float64Array;
  /** Охват пути: [minX, minY, maxX, maxY]. */
  readonly bounds: readonly [number, number, number, number];
}

const isFinitePositive = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

/**
 * Кадр из ответа API. `null` - кадр не подтверждён или данных не хватает: сравнивать с PDF
 * нельзя, и вызывающий не должен подставлять умолчания.
 */
export const frameOf = (frame: CadFrameRead): ICadFrame | null => {
  if (!frame.confirmed || frame.units !== 'mm' || !frame.origin_pt) return null;
  const [originX, originY] = frame.origin_pt;
  if (!Number.isFinite(originX) || !Number.isFinite(originY)) return null;
  if (!isFinitePositive(frame.mm_per_pdf_point)) return null;
  return { originX, originY, mmPerPt: frame.mm_per_pdf_point };
};

/** Точка DXF (мм) -> точка страницы PDF (pt от левого верхнего угла). Ось Y переворачивается. */
export const cadToPagePt = (frame: ICadFrame, x: number, y: number): [number, number] => [
  frame.originX + x / frame.mmPerPt,
  frame.originY - y / frame.mmPerPt,
];

/** Точка страницы PDF (pt) -> нормализованная точка листа. */
export const pagePtToNormalized = (page: IPageSize, x: number, y: number): [number, number] => [
  x / page.width,
  y / page.height,
];

/** Точка DXF (мм) -> нормализованная точка листа. */
export const cadToNormalized = (
  frame: ICadFrame,
  page: IPageSize,
  x: number,
  y: number,
): [number, number] => {
  const [px, py] = cadToPagePt(frame, x, y);
  return pagePtToNormalized(page, px, py);
};

/** Охват DXF (мм) -> прямоугольник страницы PDF [x0, y0, x1, y1] в pt, левый верхний угол первым. */
export const cadBboxToPageRect = (frame: ICadFrame, bbox: CadBbox): NormalizedRect => {
  const [minX, minY, maxX, maxY] = bbox;
  const [x0, y0] = cadToPagePt(frame, minX, maxY);
  const [x1, y1] = cadToPagePt(frame, maxX, minY);
  return [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1), Math.max(y0, y1)];
};

const emptyBounds = (): [number, number, number, number] => [
  Number.POSITIVE_INFINITY,
  Number.POSITIVE_INFINITY,
  Number.NEGATIVE_INFINITY,
  Number.NEGATIVE_INFINITY,
];

const convertPaths = (
  paths: readonly CadPreviewPathRead[],
  map: (x: number, y: number) => [number, number],
): INormalizedPath[] => {
  const result: INormalizedPath[] = [];
  for (const path of paths) {
    const count = Math.floor(path.points.length / 2);
    if (count < 2) continue;
    const points = new Float64Array(count * 2);
    const bounds = emptyBounds();
    for (let index = 0; index < count; index += 1) {
      const [nx, ny] = map(path.points[index * 2] ?? 0, path.points[index * 2 + 1] ?? 0);
      points[index * 2] = nx;
      points[index * 2 + 1] = ny;
      if (nx < bounds[0]) bounds[0] = nx;
      if (ny < bounds[1]) bounds[1] = ny;
      if (nx > bounds[2]) bounds[2] = nx;
      if (ny > bounds[3]) bounds[3] = ny;
    }
    result.push({ layer: path.layer, closed: path.closed, fill: path.fill, points, bounds });
  }
  return result;
};

/** Пути предпросмотра -> нормализованные координаты страницы PDF (наложение). */
export const overlayPaths = (
  paths: readonly CadPreviewPathRead[],
  frame: ICadFrame,
  page: IPageSize,
): INormalizedPath[] =>
  convertPaths(paths, (x, y) => cadToNormalized(frame, page, x, y));

/** Охват по самим путям - когда сервер не прислал `bbox`. */
export const bboxOfPaths = (paths: readonly CadPreviewPathRead[]): CadBbox | null => {
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const path of paths) {
    for (let index = 0; index + 1 < path.points.length; index += 2) {
      const x = path.points[index] ?? 0;
      const y = path.points[index + 1] ?? 0;
      if (x < minX) minX = x;
      if (y < minY) minY = y;
      if (x > maxX) maxX = x;
      if (y > maxY) maxY = y;
    }
  }
  return Number.isFinite(minX) && Number.isFinite(minY) && Number.isFinite(maxX) && Number.isFinite(maxY)
    ? [minX, minY, maxX, maxY]
    : null;
};

/** Условный лист автономного просмотра: размер в условных единицах, ось Y вниз. */
export interface IStandaloneSheet extends IPageSize {
  readonly paths: INormalizedPath[];
}

/** Длинная сторона условного листа. Камера держит масштаб в пределах 0,05-16, мм туда не лезут. */
const STANDALONE_SPAN = 1000;

/** Самая тонкая сторона охвата относительно длинной: вырожденный охват не должен давать нулевой лист. */
const MIN_ASPECT = 0.01;

/**
 * Автономный просмотр без PDF: лист - охват геометрии, ось Y DXF (вверх) переворачивается в экранную.
 *
 * Размеры листа условные, а не миллиметры: камера просмотрщика ограничивает масштаб, и охват
 * в десятки метров вышел бы за её предел. Соотношение сторон сохраняется.
 */
export const standaloneSheet = (
  paths: readonly CadPreviewPathRead[],
  bbox: CadBbox | null,
): IStandaloneSheet | null => {
  const box = bbox ?? bboxOfPaths(paths);
  if (!box) return null;
  const [minX, minY, maxX, maxY] = box;
  const span = Math.max(maxX - minX, maxY - minY);
  if (!Number.isFinite(span) || span <= 0) return null;

  const width = Math.max(maxX - minX, span * MIN_ASPECT);
  const height = Math.max(maxY - minY, span * MIN_ASPECT);
  const converted = convertPaths(paths, (x, y) => [(x - minX) / width, (maxY - y) / height]);
  return {
    width: (width / span) * STANDALONE_SPAN,
    height: (height / span) * STANDALONE_SPAN,
    paths: converted,
  };
};

/**
 * Прямоугольник контекста масштаба [x0, y0, x1, y1] (pt PDF) -> нормализованные координаты.
 * Не прямоугольник или нулевая страница - `null`.
 */
export const cropToNormalized = (
  crop: readonly number[] | null | undefined,
  page: IPageSize,
): NormalizedRect | null => {
  if (!crop || crop.length !== 4 || !isFinitePositive(page.width) || !isFinitePositive(page.height)) {
    return null;
  }
  const [x0, y0, x1, y1] = crop as [number, number, number, number];
  if (![x0, y0, x1, y1].every(Number.isFinite)) return null;
  return [
    Math.min(x0, x1) / page.width,
    Math.min(y0, y1) / page.height,
    Math.max(x0, x1) / page.width,
    Math.max(y0, y1) / page.height,
  ];
};
