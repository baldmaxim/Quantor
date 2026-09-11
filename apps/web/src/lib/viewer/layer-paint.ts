/**
 * Общая подготовка холста слоя к отрисовке: весь холст или только полосы (ADR-0025).
 *
 * Слой размером с область просмотра не перерисовывается на каждом кадре панорамы: его пиксели
 * сдвигаются, а заново рисуются только открывшиеся полосы — и только если в них есть что рисовать.
 * Рисовальщики слоёв при этом не знают о сдвиге: они получают список прямоугольников, чистят и
 * ограничивают ими холст и отсекают фигуры, которые в эти прямоугольники не попадают.
 */

import type { ScreenRect } from './coordinates';

/** Прямоугольник в физических пикселях холста. Целые числа: край полосы — граница пикселя. */
export interface PixelRect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/**
 * Прямоугольники в физических пикселях → видимые прямоугольники в CSS-пикселях с запасом
 * `margin`. По ним рисовальщик отсекает фигуры — и при рисовании, и при вопросе «есть ли в полосе
 * что рисовать»: одна формула на оба случая, иначе слой мог бы пропустить фигуру, которую нарисовал
 * бы.
 */
export const visibleRects = (
  area: readonly PixelRect[],
  devicePixelRatio: number,
  margin: number,
): readonly ScreenRect[] => {
  const ratio = devicePixelRatio > 0 ? devicePixelRatio : 1;
  return area.map((rect) => ({
    x: rect.x / ratio - margin,
    y: rect.y / ratio - margin,
    width: rect.width / ratio + margin * 2,
    height: rect.height / ratio + margin * 2,
  }));
};

/**
 * Чистит холст (весь или полосы), ограничивает рисование ими и переводит контекст в
 * CSS-пиксели. Возвращает видимые прямоугольники в CSS-пикселях с запасом `margin` — по ним
 * рисовальщик отсекает фигуры.
 *
 * Состояние контекста сохраняется: рисовальщик обязан закончить вызовом `context.restore()`.
 * Полосы режутся по целым физическим пикселям, поэтому сглаживание края фигуры внутри полосы
 * то же, что при отрисовке целиком, и шва на границе полосы нет.
 */
export const beginLayerPaint = (
  context: CanvasRenderingContext2D,
  devicePixelRatio: number,
  area: readonly PixelRect[] | null,
  margin: number,
): readonly ScreenRect[] => {
  const ratio = devicePixelRatio > 0 ? devicePixelRatio : 1;
  const { canvas } = context;

  context.setTransform(1, 0, 0, 1, 0, 0);
  context.save();

  const rects = area ?? [{ x: 0, y: 0, width: canvas.width, height: canvas.height }];
  if (area) {
    context.beginPath();
    for (const rect of area) {
      context.clearRect(rect.x, rect.y, rect.width, rect.height);
      context.rect(rect.x, rect.y, rect.width, rect.height);
    }
    context.clip();
  } else {
    context.clearRect(0, 0, canvas.width, canvas.height);
  }

  context.scale(ratio, ratio);
  return visibleRects(rects, ratio, margin);
};

/** Пересекает ли охват хотя бы один из прямоугольников. */
export const boundsIntersectAny = (
  minX: number,
  minY: number,
  maxX: number,
  maxY: number,
  rects: readonly ScreenRect[],
): boolean => {
  for (const rect of rects) {
    if (
      maxX >= rect.x &&
      minX <= rect.x + rect.width &&
      maxY >= rect.y &&
      minY <= rect.y + rect.height
    ) {
      return true;
    }
  }
  return false;
};
