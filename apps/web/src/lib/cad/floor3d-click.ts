/**
 * Различение щелчка и перетаскивания камеры по смещению указателя. `OrbitControls` шлёт событие
 * `start` уже на pointerdown, поэтому «камера пошла» определяется не им, а смещением указателя
 * после нажатия: иначе щелчок по выбранному элементу гасил бы выбор до pointerup.
 */

/** Порог, после которого нажатие считается перетаскиванием, px. */
export const CLICK_SLOP_PX = 6;

export interface IClickTracker {
  down: (x: number, y: number) => void;
  /** Указатель сдвинулся: `true` один раз за нажатие - в момент, когда смещение впервые превысило порог. */
  move: (x: number, y: number) => boolean;
  /** Указатель отпущен: `true` - это щелчок (порог не превышен), нажатие сбрасывается. */
  up: (x: number, y: number) => boolean;
  cancel: () => void;
}

export const createClickTracker = (slopPx: number = CLICK_SLOP_PX): IClickTracker => {
  let start: { x: number; y: number } | null = null;
  let dragging = false;
  const far = (x: number, y: number): boolean =>
    start !== null && Math.hypot(x - start.x, y - start.y) > slopPx;
  return {
    down: (x, y) => {
      start = { x, y };
      dragging = false;
    },
    move: (x, y) => {
      if (start === null || dragging || !far(x, y)) return false;
      dragging = true;
      return true;
    },
    up: (x, y) => {
      const click = start !== null && !dragging && !far(x, y);
      start = null;
      dragging = false;
      return click;
    },
    cancel: () => {
      start = null;
      dragging = false;
    },
  };
};
