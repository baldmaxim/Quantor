/**
 * Растр листа по видимой части: какую часть листа держать отрисованной (ADR-0025).
 *
 * Растр во весь лист на крупном увеличении — это десятки мегапикселей, и панорама упирается в
 * их композитирование: замер промта 03 показал 12 кадров/с на 266 % вообще без фигур. Поэтому
 * выше предела пикселей лист держится двумя растрами:
 *
 * - **подложка** — весь лист в масштабе предела: грубее нужного, но есть всегда, и за краем
 *   резкой части панорама не видит пустоты;
 * - **резкая часть** — видимая область с полями в масштабе камеры. Во время панорамы она только
 *   сдвигается вместе со стопкой, а перерисовывается, когда жест затих и область вышла за её
 *   край или изменился масштаб.
 *
 * Модуль чистый: ни DOM, ни pdf.js, только арифметика в координатах листа. Камера здесь — вход,
 * а не хранилище: истина координаты по-прежнему одна формула камеры (ADR-0024).
 */

import type { PageRegion } from './backend';

/** Отрисованная часть листа: прямоугольник в единицах документа и масштаб растра. */
export interface SurfaceRegion extends PageRegion {
  readonly scale: number;
}

interface PageSize {
  readonly width: number;
  readonly height: number;
}

interface CameraLike {
  readonly scale: number;
  readonly offsetX: number;
  readonly offsetY: number;
}

interface ViewportSize {
  readonly width: number;
  readonly height: number;
}

/** Поля резкой части — доля размера области просмотра с каждой стороны. */
export const SURFACE_MARGIN = 0.5;

/**
 * Предел пикселей растра во весь лист.
 *
 * Выше него лист рисуется подложкой и резкой частью. 16 Мп — это A1 при 100 % на экране с
 * плотностью 1,5 с запасом: вписанный лист и обычная работа остаются одним растром.
 */
export const FULL_PAGE_MAX_PIXELS = 16_000_000;

/**
 * Насколько подложка может быть грубее предела, прежде чем её стоит перерисовать.
 *
 * Растр, оставшийся от прежнего масштаба, служит подложкой, если он не беднее предела больше
 * чем на четверть по стороне: перерисовка ради такой разницы стоит секунды работы pdf.js.
 */
const BACKDROP_TOLERANCE = 0.75;

const EPSILON = 1e-9;

/**
 * Какая часть листа видна сейчас.
 *
 * Лист на экране начинается в точке смещения камеры и растянут масштабом; значит, левый край
 * области просмотра — это `-offsetX / scale` в координатах листа.
 */
export const visiblePageRect = (camera: CameraLike, viewport: ViewportSize): PageRegion => ({
  x: -camera.offsetX / camera.scale,
  y: -camera.offsetY / camera.scale,
  width: viewport.width / camera.scale,
  height: viewport.height / camera.scale,
});

const intersect = (rect: PageRegion, page: PageSize): PageRegion => {
  const x0 = Math.max(0, rect.x);
  const y0 = Math.max(0, rect.y);
  const x1 = Math.min(page.width, rect.x + rect.width);
  const y1 = Math.min(page.height, rect.y + rect.height);
  return { x: x0, y: y0, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) };
};

/** Масштаб, при котором весь лист укладывается в предел пикселей. */
export const fullPageScaleLimit = (
  page: PageSize,
  ratio: number,
  maxPixels = FULL_PAGE_MAX_PIXELS,
): number => Math.sqrt(maxPixels / (page.width * page.height)) / ratio;

/**
 * Лист в границах целых физических пикселей растра.
 *
 * Растр во весь лист — `floor(лист × масштаб × плотность)` пикселей: последняя дробная доля
 * пикселя не рисуется никогда. Резкая часть и проверка покрытия считают край листа так же, иначе
 * часть у правого края «не покрывала» бы эту долю и перерисовывалась бы без конца.
 */
const pixelPage = (page: PageSize, density: number): PageSize => ({
  width: Math.floor(page.width * density) / density,
  height: Math.floor(page.height * density) / density,
});

/**
 * Выравнивает прямоугольник по физическим пикселям растра.
 *
 * Край резкой части обязан лечь на границу пикселя листа в этом масштабе: тогда её пиксели —
 * ровно те, что дал бы растр во весь лист, и шва между частью и соседними пикселями нет.
 */
const alignToPixels = (
  rect: PageRegion,
  page: PageSize,
  scale: number,
  ratio: number,
): PageRegion => {
  const density = scale * ratio;
  const right = Math.floor(page.width * density);
  const bottom = Math.floor(page.height * density);
  const clampTo = (value: number, max: number) => Math.min(Math.max(value, 0), max);

  const x0 = clampTo(Math.floor(rect.x * density + EPSILON), right);
  const y0 = clampTo(Math.floor(rect.y * density + EPSILON), bottom);
  const x1 = clampTo(Math.ceil((rect.x + rect.width) * density - EPSILON), right);
  const y1 = clampTo(Math.ceil((rect.y + rect.height) * density - EPSILON), bottom);

  return {
    x: x0 / density,
    y: y0 / density,
    width: Math.max(0, x1 - x0) / density,
    height: Math.max(0, y1 - y0) / density,
  };
};

/**
 * Резкая часть для текущей камеры: видимая часть листа с полями, обрезанная по листу и
 * выровненная по пикселям.
 *
 * `null` — рисовать нечего: область просмотра ещё не разложена или лист целиком за её краем.
 * Гадать о видимой части в этих случаях не из чего, а лист во весь рост в масштабе камеры —
 * ровно та память, от которой эта часть и спасает.
 */
export const surfaceRegionFor = (
  page: PageSize,
  camera: CameraLike,
  viewport: ViewportSize,
  ratio: number,
  margin = SURFACE_MARGIN,
): SurfaceRegion | null => {
  if (viewport.width <= 0 || viewport.height <= 0) return null;

  const visible = visiblePageRect(camera, viewport);
  const padX = visible.width * margin;
  const padY = visible.height * margin;
  const padded = intersect(
    {
      x: visible.x - padX,
      y: visible.y - padY,
      width: visible.width + padX * 2,
      height: visible.height + padY * 2,
    },
    page,
  );
  if (padded.width <= 0 || padded.height <= 0) return null;

  const aligned = alignToPixels(padded, page, camera.scale, ratio);
  if (aligned.width <= 0 || aligned.height <= 0) return null;
  return { ...aligned, scale: camera.scale };
};

/**
 * Покрывает ли растр всё, что сейчас видно на листе.
 *
 * Сравнивается видимая часть листа, а не прямоугольник области просмотра: за краем листа
 * рисовать нечего, и область, выехавшая за лист, резкую часть не «обгоняет». Край листа — в
 * целых пикселях растра этого масштаба (`pixelPage`).
 */
export const surfaceCovers = (
  surface: SurfaceRegion,
  page: PageSize,
  camera: CameraLike,
  viewport: ViewportSize,
  ratio: number,
): boolean => {
  const bounds = pixelPage(page, surface.scale * ratio);
  const visible = intersect(visiblePageRect(camera, viewport), bounds);
  if (visible.width <= 0 || visible.height <= 0) return true;

  const tolerance = 1e-6;
  return (
    visible.x >= surface.x - tolerance &&
    visible.y >= surface.y - tolerance &&
    visible.x + visible.width <= surface.x + surface.width + tolerance &&
    visible.y + visible.height <= surface.y + surface.height + tolerance
  );
};

/** Готовый растр листа: какая часть, в каком масштабе и при какой плотности экрана. */
export interface RasterPiece {
  readonly region: SurfaceRegion;
  readonly ratio: number;
}

/** Растры листа, которые сейчас лежат в стопке. */
export interface RasterPieces {
  /** Весь лист: в масштабе камеры, пока он в пределе, выше — подложка. */
  readonly base: RasterPiece | null;
  /** Резкая часть выше предела. */
  readonly detail: RasterPiece | null;
}

/** Следующая отрисовка, которой не хватает виду. */
export type RasterPlan =
  | { readonly kind: 'page'; readonly region: SurfaceRegion; readonly ratio: number }
  | { readonly kind: 'detail'; readonly region: SurfaceRegion; readonly ratio: number }
  | { readonly kind: 'backdrop'; readonly region: SurfaceRegion; readonly ratio: number };

const wholePage = (page: PageSize, scale: number): SurfaceRegion => ({
  x: 0,
  y: 0,
  width: page.width,
  height: page.height,
  scale,
});

const coversWholePage = (region: SurfaceRegion, page: PageSize, ratio: number): boolean => {
  const bounds = pixelPage(page, region.scale * ratio);
  return (
    region.x <= EPSILON &&
    region.y <= EPSILON &&
    region.x + region.width >= bounds.width - 1e-6 &&
    region.y + region.height >= bounds.height - 1e-6
  );
};

/**
 * Чего не хватает виду — одна отрисовка за раз, самая нужная первой.
 *
 * - В пределе пикселей — весь лист в масштабе камеры, как было до Stage 2B.
 * - Выше предела сначала резкая часть: пользователь смотрит на видимую область. Потом подложка,
 *   если прежний растр слишком груб, чтобы закрывать края при панораме.
 * - `null` — вид полон, pdf.js не нужен. Чистая панорама внутри резкой части сюда и приходит.
 */
export const planRaster = (
  pieces: RasterPieces,
  page: PageSize,
  camera: CameraLike,
  viewport: ViewportSize,
  ratio: number,
  maxPixels = FULL_PAGE_MAX_PIXELS,
): RasterPlan | null => {
  const limit = fullPageScaleLimit(page, ratio, maxPixels);
  const { base, detail } = pieces;

  if (camera.scale <= limit) {
    const sharp = base !== null && base.ratio === ratio && base.region.scale === camera.scale;
    return sharp ? null : { kind: 'page', region: wholePage(page, camera.scale), ratio };
  }

  const detailFresh =
    detail !== null &&
    detail.ratio === ratio &&
    detail.region.scale === camera.scale &&
    surfaceCovers(detail.region, page, camera, viewport, ratio);
  if (!detailFresh) {
    const region = surfaceRegionFor(page, camera, viewport, ratio);
    if (region) return { kind: 'detail', region, ratio };
  }

  // Резкая часть закрывает весь лист (огромный экран) — подложке нечего закрывать.
  if (detailFresh && detail && coversWholePage(detail.region, page, ratio)) return null;

  const backdropFresh =
    base !== null && base.ratio === ratio && base.region.scale >= limit * BACKDROP_TOLERANCE;
  return backdropFresh ? null : { kind: 'backdrop', region: wholePage(page, limit), ratio };
};

/**
 * Можно ли не обрывать идущую отрисовку ради нового плана.
 *
 * Та же подложка или тот же лист — да. Резкая часть — да, если она в том же масштабе и всё
 * ещё покрывает вид: жест, затихший в её пределах, не должен выбрасывать почти готовый растр.
 */
export const planStillValid = (
  running: RasterPlan,
  next: RasterPlan,
  page: PageSize,
  camera: CameraLike,
  viewport: ViewportSize,
): boolean => {
  if (running.kind !== next.kind || running.ratio !== next.ratio) return false;
  if (running.region.scale !== next.region.scale) return false;
  if (running.kind !== 'detail') return true;
  return surfaceCovers(running.region, page, camera, viewport, running.ratio);
};

/** Тот же растр: вид, плотность и прямоугольник совпадают до бита. */
export const samePlan = (a: RasterPlan, b: RasterPlan): boolean =>
  a.kind === b.kind &&
  a.ratio === b.ratio &&
  a.region.scale === b.region.scale &&
  a.region.x === b.region.x &&
  a.region.y === b.region.y &&
  a.region.width === b.region.width &&
  a.region.height === b.region.height;

/**
 * CSS-размещение растра в стопке.
 *
 * Стопка разложена в CSS-пикселях масштаба `layoutScale` и растягивается преобразованием до
 * масштаба камеры. Растр любого масштаба занимает в ней свой прямоугольник листа × этот масштаб:
 * подложка растягивается браузером, резкая часть ложится пиксель в пиксель.
 */
export const pieceStyle = (region: PageRegion, layoutScale: number) => ({
  left: `${region.x * layoutScale}px`,
  top: `${region.y * layoutScale}px`,
  width: `${region.width * layoutScale}px`,
  height: `${region.height * layoutScale}px`,
});

/**
 * CSS-преобразование стопки.
 *
 * Растры разложены в масштабе `layoutScale`; камера могла с тех пор уйти. Стопка сдвигается на
 * смещение камеры и растягивается отношением масштабов — до перерисовки лист просто мылится, а
 * не прыгает.
 */
export const stackTransform = (layoutScale: number, camera: CameraLike): string =>
  `translate(${camera.offsetX}px, ${camera.offsetY}px) scale(${camera.scale / layoutScale})`;
