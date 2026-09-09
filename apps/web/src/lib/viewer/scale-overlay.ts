/**
 * Отрисовка черновика калибровки: перекрестие и линия между точками.
 *
 * Отдельный слой поверх слоя областей (ADR-0015). Painter областей не расширяется
 * признаком «а это масштаб»: `Region` — свидетельство распознавалки, черновик — намерение
 * пользователя, и смешивать их в одной функции значило бы получить общий код, который
 * ломается для обоих сразу.
 *
 * Canvas2D. WebGL здесь не нужен ни при каких обстоятельствах: на слое три примитива.
 */

import type { SheetPlacement } from '@/lib/viewer/coordinates';
import { toScreenPoint } from '@/lib/viewer/coordinates';
import type { ScaleDraftState } from '@/lib/viewer/scale-draft';

export interface ScaleOverlayStyle {
  /** Цвет линии и точек. Приходит из токенов темы, а не зашит здесь. */
  readonly color: string;
}

const LINE_WIDTH = 1.5;
const POINT_RADIUS = 4;
const CROSSHAIR_LENGTH = 12;

/** Штрих резиновой линии: она ещё не результат, и выглядеть как результат не должна. */
const PENDING_DASH = [6, 4];

/**
 * Рисует черновик и возвращает число нарисованных точек.
 *
 * Возврат нужен тесту: «слой отрисовался» и «слой отрисовал то, что нужно» — разные
 * утверждения, и второе проверяется числом, а не скриншотом.
 */
export const drawScaleDraft = (
  context: CanvasRenderingContext2D,
  placement: SheetPlacement,
  state: ScaleDraftState,
  style: ScaleOverlayStyle,
  devicePixelRatio = 1,
): number => {
  const canvas = context.canvas;
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.scale(devicePixelRatio, devicePixelRatio);

  const first = state.a;
  if (first === null) {
    // Инструмент включён, но точек нет: показываем перекрестие под курсором, чтобы
    // было видно, что щелчок сейчас поставит точку, а не выберет область.
    if (state.hover !== null) {
      drawCrosshair(context, toScreenPoint(state.hover, placement), style);
    }
    return 0;
  }

  const start = toScreenPoint(first, placement);
  const endPoint = state.b ?? state.hover;
  const complete = state.b !== null;

  context.save();
  context.strokeStyle = style.color;
  context.fillStyle = style.color;
  context.lineWidth = LINE_WIDTH;

  if (endPoint !== null) {
    const end = toScreenPoint(endPoint, placement);
    // Пока вторая точка не поставлена — пунктир: линия предварительная.
    context.setLineDash(complete ? [] : PENDING_DASH);
    context.beginPath();
    context.moveTo(start.x, start.y);
    context.lineTo(end.x, end.y);
    context.stroke();
    context.setLineDash([]);

    if (complete) {
      drawPoint(context, end);
    } else {
      drawCrosshair(context, end, style);
    }
  }

  drawPoint(context, start);
  context.restore();

  return complete ? 2 : 1;
};

const drawPoint = (context: CanvasRenderingContext2D, point: { x: number; y: number }): void => {
  context.beginPath();
  context.arc(point.x, point.y, POINT_RADIUS, 0, Math.PI * 2);
  context.fill();
};

const drawCrosshair = (
  context: CanvasRenderingContext2D,
  point: { x: number; y: number },
  style: ScaleOverlayStyle,
): void => {
  context.save();
  context.strokeStyle = style.color;
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(point.x - CROSSHAIR_LENGTH, point.y);
  context.lineTo(point.x + CROSSHAIR_LENGTH, point.y);
  context.moveTo(point.x, point.y - CROSSHAIR_LENGTH);
  context.lineTo(point.x, point.y + CROSSHAIR_LENGTH);
  context.stroke();
  context.restore();
};
