/**
 * Камера просмотрщика: масштаб и смещение холста.
 *
 * Панорамирование и зум происходят десятки раз в секунду. Если гнать каждый кадр через
 * состояние React, перерисовывается всё дерево, и на листе с сотнями областей это
 * превращается в рывки (ADR-0004).
 *
 * Поэтому состояние камеры живёт здесь, меняется императивно, а подписчики получают
 * уведомление не чаще одного раза за кадр. React владеет панелями и элементами
 * управления; трансформациями владеет камера.
 */

import { clamp } from './coordinates';

export interface CameraState {
  /** Масштаб отрисовки: 1 — сто процентов. */
  readonly scale: number;
  /** Смещение левого верхнего угла листа в пикселях области отрисовки. */
  readonly offsetX: number;
  readonly offsetY: number;
}

export interface Viewport {
  readonly width: number;
  readonly height: number;
}

export interface ContentSize {
  readonly width: number;
  readonly height: number;
}

export type CameraListener = (state: CameraState) => void;

/** Пределы масштаба. Ниже нижнего лист превращается в точку, выше верхнего — в пиксели. */
export const MIN_SCALE = 0.05;
export const MAX_SCALE = 16;

/** Шаг зума кнопками. Множитель, а не слагаемое: иначе на малом масштабе шаг огромен. */
export const ZOOM_STEP = 1.25;

/** Поля вокруг листа при вписывании, чтобы он не упирался в края области. */
const FIT_PADDING = 24;

export class Camera {
  private state: CameraState = { scale: 1, offsetX: 0, offsetY: 0 };
  private readonly listeners = new Set<CameraListener>();
  private frame: number | null = null;

  getState(): CameraState {
    return this.state;
  }

  /**
   * Подписка на изменения.
   *
   * Уведомления объединяются в кадр: за один жест мыши приходит столько же обновлений,
   * сколько кадров успел показать браузер, а не столько, сколько пришло событий.
   */
  subscribe(listener: CameraListener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Сдвигает холст. Вызывается на каждое движение указателя. */
  panBy(deltaX: number, deltaY: number): void {
    this.apply({
      scale: this.state.scale,
      offsetX: this.state.offsetX + deltaX,
      offsetY: this.state.offsetY + deltaY,
    });
  }

  /**
   * Меняет масштаб, удерживая точку под курсором на месте.
   *
   * Это единственный способ зума, который не раздражает: без якоря лист уезжает
   * из-под курсора, и пользователь всякий раз доводит его вручную.
   */
  zoomAt(anchor: { x: number; y: number }, factor: number): void {
    const scale = clamp(this.state.scale * factor, MIN_SCALE, MAX_SCALE);
    const applied = scale / this.state.scale;

    this.apply({
      scale,
      offsetX: anchor.x - (anchor.x - this.state.offsetX) * applied,
      offsetY: anchor.y - (anchor.y - this.state.offsetY) * applied,
    });
  }

  zoomIn(viewport: Viewport): void {
    this.zoomAt({ x: viewport.width / 2, y: viewport.height / 2 }, ZOOM_STEP);
  }

  zoomOut(viewport: Viewport): void {
    this.zoomAt({ x: viewport.width / 2, y: viewport.height / 2 }, 1 / ZOOM_STEP);
  }

  /** Вписывает лист целиком. */
  fitPage(content: ContentSize, viewport: Viewport): void {
    if (content.width <= 0 || content.height <= 0) return;

    const scale = clamp(
      Math.min(
        (viewport.width - FIT_PADDING * 2) / content.width,
        (viewport.height - FIT_PADDING * 2) / content.height,
      ),
      MIN_SCALE,
      MAX_SCALE,
    );
    this.apply(centered(content, viewport, scale));
  }

  /** Вписывает лист по ширине — основной режим чтения чертежа. */
  fitWidth(content: ContentSize, viewport: Viewport): void {
    if (content.width <= 0) return;

    const scale = clamp((viewport.width - FIT_PADDING * 2) / content.width, MIN_SCALE, MAX_SCALE);
    const placed = centered(content, viewport, scale);
    // По вертикали прижимаем к верху: читают чертёж сверху вниз.
    this.apply({ ...placed, offsetY: FIT_PADDING });
  }

  /** Сбрасывает вид к вписанному листу. */
  reset(content: ContentSize, viewport: Viewport): void {
    this.fitPage(content, viewport);
  }

  /** Ставит состояние напрямую — при смене листа, чтобы не анимировать переход. */
  set(state: CameraState): void {
    this.apply({
      scale: clamp(state.scale, MIN_SCALE, MAX_SCALE),
      offsetX: state.offsetX,
      offsetY: state.offsetY,
    });
  }

  /** Освобождает подписчиков и отменяет запланированный кадр. */
  dispose(): void {
    this.listeners.clear();
    if (this.frame !== null) {
      cancelFrame(this.frame);
      this.frame = null;
    }
  }

  private apply(next: CameraState): void {
    if (
      next.scale === this.state.scale &&
      next.offsetX === this.state.offsetX &&
      next.offsetY === this.state.offsetY
    ) {
      return;
    }
    this.state = next;
    this.scheduleNotify();
  }

  private scheduleNotify(): void {
    if (this.frame !== null) return;
    this.frame = requestFrame(() => {
      this.frame = null;
      for (const listener of this.listeners) {
        listener(this.state);
      }
    });
  }
}

const centered = (content: ContentSize, viewport: Viewport, scale: number): CameraState => ({
  scale,
  offsetX: (viewport.width - content.width * scale) / 2,
  offsetY: (viewport.height - content.height * scale) / 2,
});

/**
 * Планирование кадра.
 *
 * В браузере это requestAnimationFrame; в тестах и на сервере его нет, и подмена
 * на таймер позволяет проверять камеру, не поднимая DOM.
 */
const requestFrame = (callback: () => void): number =>
  typeof requestAnimationFrame === 'function'
    ? requestAnimationFrame(callback)
    : (setTimeout(callback, 16) as unknown as number);

const cancelFrame = (handle: number): void => {
  if (typeof cancelAnimationFrame === 'function') {
    cancelAnimationFrame(handle);
  } else {
    clearTimeout(handle);
  }
};
