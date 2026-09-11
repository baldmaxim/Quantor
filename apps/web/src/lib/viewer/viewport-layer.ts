/**
 * Слой наложения размером с область просмотра, который не перерисовывается на каждом кадре
 * (ADR-0025).
 *
 * Промт 03 сначала рисовал слои заново на каждом кадре камеры. Замер показал цену: на 100 % при
 * 5000 измерений кадр вырос до 383 мс — растеризуются все видимые фигуры, и отсечение не
 * спасает, когда видна половина листа. Поэтому слой помнит, при какой камере нарисованы его
 * пиксели, и на кадре делает самое дешёвое из достаточного:
 *
 * - **сдвиг CSS** — масштаб тот же, а в открывшихся полосах рисовать нечего: холст не трогается,
 *   его сдвигает CSS-преобразование. Замер: каждое изменение холста на кадре — это ещё и
 *   передача растра композитору, и два пустых слоя, копируемых на каждом кадре, съедали треть
 *   кадра;
 * - **сдвиг пикселей** — в полосах есть фигуры: пиксели сдвигаются на целое число физических
 *   пикселей, заново рисуются только полосы, дробный остаток добирает CSS-сдвиг;
 * - **растяжение** — масштаб изменился посреди жеста: холст растягивается CSS-преобразованием
 *   до затихания жеста, как стопка страницы, и перерисовывается целиком после;
 * - **перерисовка** — первый кадр, другая плотность или размер области, сдвиг больше холста.
 *
 * Память слоя — ровно область просмотра в физических пикселях (бюджет Б1 ADR-0024): второго
 * буфера нет, сдвиг копирует холст сам в себя.
 */

import type { CameraState } from './camera';
import { placeViewportPage, type SheetPlacement } from './coordinates';
import type { PixelRect } from './layer-paint';
import { resizeOverlay } from './overlay';

/** Рисовальщик слоя. Данные слоя живут в нём, слой знает только, когда и где рисовать. */
export interface LayerPainter {
  /** Рисует весь холст (`area === null`) или только полосы. */
  paint(
    context: CanvasRenderingContext2D,
    placement: SheetPlacement,
    devicePixelRatio: number,
    area: readonly PixelRect[] | null,
  ): void;
  /**
   * Есть ли в прямоугольниках что рисовать. Обязан быть не строже `paint`: ответ «нечего» значит,
   * что `paint` в этих прямоугольниках не нарисовал бы ни пикселя.
   */
  touches(placement: SheetPlacement, devicePixelRatio: number, area: readonly PixelRect[]): boolean;
}

/** Всё, что определяет пиксели слоя, кроме данных рисовальщика. */
export interface LayerView {
  readonly camera: CameraState;
  readonly page: { readonly width: number; readonly height: number };
  /** Размер области просмотра в CSS-пикселях. */
  readonly width: number;
  readonly height: number;
  readonly ratio: number;
}

/** С какой камерой, листом и размером нарисованы пиксели слоя. */
export interface PaintedLayer {
  readonly scale: number;
  readonly offsetX: number;
  readonly offsetY: number;
  readonly pageWidth: number;
  readonly pageHeight: number;
  readonly width: number;
  readonly height: number;
  readonly ratio: number;
}

export type LayerUpdate =
  | { readonly kind: 'repaint' }
  | { readonly kind: 'stretch'; readonly transform: string }
  | {
      readonly kind: 'shift';
      /** Сдвиг пикселей в физических пикселях. Может быть нулевым: тогда меняется только CSS. */
      readonly dx: number;
      readonly dy: number;
      /** Открывшиеся полосы в физических пикселях. */
      readonly strips: readonly PixelRect[];
      /** Смещение камеры, которому соответствуют пиксели после сдвига. */
      readonly offsetX: number;
      readonly offsetY: number;
      /** CSS-сдвиг холста на дробный остаток. */
      readonly transform: string;
    };

const deviceSize = (view: LayerView) => ({
  // Та же формула, что у `resizeOverlay`: полосы обязаны лечь ровно в холст.
  width: Math.max(1, Math.floor(view.width * view.ratio)),
  height: Math.max(1, Math.floor(view.height * view.ratio)),
});

const translate = (x: number, y: number): string =>
  x === 0 && y === 0 ? '' : `translate(${x}px, ${y}px)`;

/**
 * Что сделать со слоем на кадре камеры. Чистая функция: вход — нарисованное и текущий вид.
 */
export const planLayerUpdate = (painted: PaintedLayer | null, view: LayerView): LayerUpdate => {
  if (
    painted === null ||
    painted.ratio !== view.ratio ||
    painted.width !== view.width ||
    painted.height !== view.height ||
    painted.pageWidth !== view.page.width ||
    painted.pageHeight !== view.page.height
  ) {
    return { kind: 'repaint' };
  }

  const { camera } = view;
  if (painted.scale !== camera.scale) {
    // Пиксель холста q нарисован при камере P: точка листа (q − oP) / sP. При камере C она на
    // экране в oC + sC · (q − oP) / sP — то есть холст сдвигается и растягивается в k = sC / sP.
    const k = camera.scale / painted.scale;
    return {
      kind: 'stretch',
      transform: `translate(${camera.offsetX - k * painted.offsetX}px, ${camera.offsetY - k * painted.offsetY}px) scale(${k})`,
    };
  }

  const size = deviceSize(view);
  const dx = Math.round((camera.offsetX - painted.offsetX) * view.ratio);
  const dy = Math.round((camera.offsetY - painted.offsetY) * view.ratio);
  if (Math.abs(dx) >= size.width || Math.abs(dy) >= size.height) return { kind: 'repaint' };

  const offsetX = painted.offsetX + dx / view.ratio;
  const offsetY = painted.offsetY + dy / view.ratio;

  const strips: PixelRect[] = [];
  if (dx > 0) strips.push({ x: 0, y: 0, width: dx, height: size.height });
  if (dx < 0) strips.push({ x: size.width + dx, y: 0, width: -dx, height: size.height });
  if (dy > 0) strips.push({ x: 0, y: 0, width: size.width, height: dy });
  if (dy < 0) strips.push({ x: 0, y: size.height + dy, width: size.width, height: -dy });

  return {
    kind: 'shift',
    dx,
    dy,
    strips,
    offsetX,
    offsetY,
    transform: translate(camera.offsetX - offsetX, camera.offsetY - offsetY),
  };
};

const paintedOf = (view: LayerView): PaintedLayer => ({
  scale: view.camera.scale,
  offsetX: view.camera.offsetX,
  offsetY: view.camera.offsetY,
  pageWidth: view.page.width,
  pageHeight: view.page.height,
  width: view.width,
  height: view.height,
  ratio: view.ratio,
});

/**
 * Холст слоя и память о том, как он нарисован.
 *
 * Данных слоя класс не знает: рисовальщик приходит на каждый вызов. Так слои остаются
 * логически независимыми (ADR-0015) — общий у них только способ не перерисовываться зря.
 */
export class ViewportLayer {
  private painted: PaintedLayer | null = null;
  // На холсте нет ни одной фигуры. Пустой холст незачем перерисовывать, когда сдвиг ушёл за его
  // край: в новом виде тоже может не быть ничего.
  private blank = true;

  constructor(private readonly canvas: HTMLCanvasElement) {}

  /** Как сейчас нарисован слой. Для тестов и замера. */
  getPainted(): PaintedLayer | null {
    return this.painted;
  }

  /** Перерисовывает слой целиком по текущему виду: данные изменились или жест затих. */
  repaint(view: LayerView, painter: LayerPainter): void {
    const context = this.canvas.getContext('2d');
    if (!context) return;

    const placement = placeViewportPage(view.page, view.camera);
    resizeOverlay(this.canvas, view.width, view.height, view.ratio);
    painter.paint(context, placement, view.ratio, null);
    this.painted = paintedOf(view);
    this.blank = !painter.touches(placement, view.ratio, [wholeCanvas(view)]);
    this.setTransform('');
  }

  /** Догоняет камеру на кадре: CSS, сдвиг пикселей, растяжение или перерисовка — что дешевле. */
  follow(view: LayerView, painter: LayerPainter): void {
    const update = planLayerUpdate(this.painted, view);
    if (update.kind === 'repaint') {
      if (this.stillBlank(view, painter)) {
        this.painted = paintedOf(view);
        this.setTransform('');
        return;
      }
      this.repaint(view, painter);
      return;
    }
    if (update.kind === 'stretch') {
      this.setTransform(update.transform);
      return;
    }

    const painted = this.painted;
    const context = this.canvas.getContext('2d');
    if (!painted || !context) return;

    if (update.dx !== 0 || update.dy !== 0) {
      const placement = placeViewportPage(view.page, {
        scale: painted.scale,
        offsetX: update.offsetX,
        offsetY: update.offsetY,
      });

      // В полосах рисовать нечего — пиксели остаются, где нарисованы, а холст сдвигает CSS на
      // всё расстояние от них до камеры. Полосы копятся и дорисуются разом, когда в них войдёт
      // фигура.
      if (!painter.touches(placement, view.ratio, update.strips)) {
        this.setTransform(
          translate(view.camera.offsetX - painted.offsetX, view.camera.offsetY - painted.offsetY),
        );
        return;
      }

      // Копия холста в самого себя: 'copy' заменяет всё, и открывшиеся полосы становятся
      // прозрачными. Спецификация велит копировать источник до рисования, так что чтение и
      // запись одного холста безопасны.
      context.save();
      context.setTransform(1, 0, 0, 1, 0, 0);
      context.globalCompositeOperation = 'copy';
      context.drawImage(this.canvas, update.dx, update.dy);
      context.restore();

      this.painted = { ...painted, offsetX: update.offsetX, offsetY: update.offsetY };
      painter.paint(context, placement, view.ratio, update.strips);
      this.blank = false;
    }
    this.setTransform(update.transform);
  }

  /** Жест затих: растянутый слой перерисовывается в масштабе камеры. Сдвинутый — нет. */
  settle(view: LayerView, painter: LayerPainter): void {
    if (this.painted !== null && this.painted.scale !== view.camera.scale) {
      this.repaint(view, painter);
    }
  }

  /** Забыть нарисованное: следующий кадр перерисует слой целиком. */
  invalidate(): void {
    this.painted = null;
  }

  /**
   * Холст пуст и в новом виде рисовать нечего — перерисовка ничего бы не изменила.
   *
   * Только при том же холсте и масштабе: другая плотность или размер области меняют сам холст, и
   * его нужно пересоздать.
   */
  private stillBlank(view: LayerView, painter: LayerPainter): boolean {
    const painted = this.painted;
    return (
      painted !== null &&
      this.blank &&
      painted.ratio === view.ratio &&
      painted.width === view.width &&
      painted.height === view.height &&
      painted.scale === view.camera.scale &&
      !painter.touches(placeViewportPage(view.page, view.camera), view.ratio, [wholeCanvas(view)])
    );
  }

  private setTransform(value: string): void {
    if (this.canvas.style.transform !== value) this.canvas.style.transform = value;
  }
}

/** Весь холст слоя в физических пикселях. */
const wholeCanvas = (view: LayerView): PixelRect => ({ x: 0, y: 0, ...deviceSize(view) });
