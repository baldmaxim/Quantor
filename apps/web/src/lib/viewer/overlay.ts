/**
 * Слой распознанных областей.
 *
 * Отдельный холст поверх страницы, а не элементы DOM: на листе сотни областей, и столько
 * узлов заставляют браузер пересчитывать раскладку на каждом кадре панорамирования
 * (ADR-0004).
 *
 * Взят двумерный холст, а не WebGL: для сотен прямоугольников он справляется с запасом,
 * а WebGL-слой — это ещё одна тяжёлая зависимость в бандле рабочей области. Когда на лист
 * придут тысячи примитивов будущих обмеров, сюда встанет пространственный индекс и
 * упрощение по масштабу; рисование вынесено в отдельную функцию именно для этого.
 *
 * Слой измерений будет отдельным слоем и не переиспользует эти объекты: Region — это
 * свидетельство, а не намерение (ADR-0008).
 */

import {
  toScreenPolygon,
  toScreenRect,
  type NormalizedRect,
  type SheetPlacement,
} from './coordinates';

export interface OverlayRegion {
  readonly id: string;
  readonly blockType: string;
  readonly shapeType: 'rectangle' | 'polygon';
  readonly coords: NormalizedRect;
  readonly polygon: readonly (readonly [number, number])[] | null;
}

export interface OverlayStyle {
  /** Цвет по типу области. Значения приходят из токенов темы, а не задаются здесь. */
  readonly colors: Readonly<Record<string, string>>;
  readonly fallbackColor: string;
}

export interface OverlayState {
  readonly regions: readonly OverlayRegion[];
  readonly hiddenTypes: ReadonlySet<string>;
  readonly selectedId: string | null;
  readonly hoveredId: string | null;
}

const LINE_WIDTH = 1.5;
const SELECTED_LINE_WIDTH = 2.5;
const FILL_ALPHA = 0.14;
const HOVER_ALPHA = 0.2;
const SELECTED_ALPHA = 0.28;

/**
 * Рисует слой целиком.
 *
 * Функция чистая относительно холста: она не хранит состояния и не подписывается
 * на события. Это позволяет вызывать её из кадра анимации сколько угодно часто.
 */
export const drawOverlay = (
  context: CanvasRenderingContext2D,
  placement: SheetPlacement,
  state: OverlayState,
  style: OverlayStyle,
  devicePixelRatio = 1,
): number => {
  const { canvas } = context;
  context.save();
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.scale(devicePixelRatio, devicePixelRatio);

  let drawn = 0;

  for (const region of state.regions) {
    if (state.hiddenTypes.has(region.blockType)) continue;

    const color = style.colors[region.blockType] ?? style.fallbackColor;
    const selected = region.id === state.selectedId;
    const hovered = region.id === state.hoveredId;

    context.strokeStyle = color;
    context.fillStyle = color;
    context.globalAlpha = selected ? SELECTED_ALPHA : hovered ? HOVER_ALPHA : FILL_ALPHA;
    context.lineWidth = selected ? SELECTED_LINE_WIDTH : LINE_WIDTH;

    if (region.shapeType === 'polygon' && region.polygon && region.polygon.length >= 3) {
      drawPolygon(context, region.polygon, placement);
    } else {
      drawRect(context, region.coords, placement);
    }

    drawn += 1;
  }

  context.restore();
  return drawn;
};

const drawRect = (
  context: CanvasRenderingContext2D,
  coords: NormalizedRect,
  placement: SheetPlacement,
): void => {
  const rect = toScreenRect(coords, placement);
  context.fillRect(rect.x, rect.y, rect.width, rect.height);
  context.globalAlpha = 1;
  context.strokeRect(rect.x, rect.y, rect.width, rect.height);
};

const drawPolygon = (
  context: CanvasRenderingContext2D,
  polygon: readonly (readonly [number, number])[],
  placement: SheetPlacement,
): void => {
  const points = toScreenPolygon(polygon, placement);
  const first = points[0];
  if (!first) return;

  context.beginPath();
  context.moveTo(first.x, first.y);
  for (const point of points.slice(1)) context.lineTo(point.x, point.y);
  context.closePath();

  context.fill();
  context.globalAlpha = 1;
  context.stroke();
};

/** Подгоняет размер холста под область отрисовки с учётом плотности экрана. */
export const resizeOverlay = (
  canvas: HTMLCanvasElement,
  width: number,
  height: number,
  devicePixelRatio = 1,
): void => {
  const targetWidth = Math.max(1, Math.floor(width * devicePixelRatio));
  const targetHeight = Math.max(1, Math.floor(height * devicePixelRatio));

  if (canvas.width !== targetWidth) canvas.width = targetWidth;
  if (canvas.height !== targetHeight) canvas.height = targetHeight;

  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
};
