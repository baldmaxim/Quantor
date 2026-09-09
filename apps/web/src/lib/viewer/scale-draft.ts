/**
 * Черновик калибровки масштаба: две точки, которые пользователь ставит по известному размеру.
 *
 * Императивный контроллер по образцу `Camera`, а не состояние React. Причина та же: точка
 * под курсором меняется на каждом движении мыши, и класть её в состояние значило бы
 * перерисовывать дерево компонентов десятки раз в секунду — вместе с панелями, списком
 * листов и всем, что попадётся под родителем.
 *
 * Здесь только состояние и переходы. Ни DOM, ни canvas, ни сети: отрисовкой занимается
 * слой наложения, отправкой — рабочая область. Такое разделение позволяет проверить все
 * переходы тестом, не поднимая браузер.
 */

import type { NormalizedPoint } from '@/lib/viewer/coordinates';

/** Что сейчас делает инструмент. */
export type ScaleDraftPhase =
  /** Инструмент включён, первая точка не поставлена. */
  | 'idle'
  /** Первая точка есть, вторая тянется за курсором. */
  | 'awaiting-second'
  /** Обе точки поставлены — дальше спрашиваем известный размер. */
  | 'complete';

export interface ScaleDraftState {
  readonly phase: ScaleDraftPhase;
  readonly a: NormalizedPoint | null;
  readonly b: NormalizedPoint | null;
  /** Точка под курсором. Нужна резиновой линии до второго щелчка. */
  readonly hover: NormalizedPoint | null;
}

const EMPTY: ScaleDraftState = { phase: 'idle', a: null, b: null, hover: null };

/**
 * Точки, между которыми линия вырождается в точку.
 *
 * Это не проверка масштаба — её делает сервер в точках PDF, где известен размер страницы.
 * Здесь отсекается только случайный двойной щелчок: два попадания в один пиксель.
 */
const MIN_NORMALIZED_SEPARATION = 1e-6;

export class ScaleDraft {
  private state: ScaleDraftState = EMPTY;
  private listeners = new Set<(state: ScaleDraftState) => void>();
  private frame: number | null = null;

  getState(): ScaleDraftState {
    return this.state;
  }

  subscribe(listener: (state: ScaleDraftState) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /**
   * Ставит точку.
   *
   * Первый щелчок задаёт A, второй — B. Третьего не бывает: пока черновик не подтверждён
   * или не отменён, новые щелчки игнорируются, иначе случайный клик мимо диалога молча
   * переставил бы уже выбранный размер.
   */
  pick(point: NormalizedPoint): void {
    if (this.state.phase === 'complete') return;

    if (this.state.phase === 'idle') {
      this.set({ phase: 'awaiting-second', a: point, b: null, hover: point });
      return;
    }

    const first = this.state.a;
    if (first === null) return;

    // Второй щелчок в ту же точку — почти наверняка промах или дребезг. Черновик
    // остаётся в прежней фазе, и пользователь просто ставит точку заново.
    if (this.tooClose(first, point)) return;

    this.set({ phase: 'complete', a: first, b: point, hover: point });
  }

  /** Двигает свободный конец линии. Вызывается на каждое движение указателя. */
  hover(point: NormalizedPoint | null): void {
    if (this.state.phase === 'complete') return;
    this.set({ ...this.state, hover: point });
  }

  /** Отменяет черновик целиком. Ни одного обращения к серверу при этом не происходит. */
  cancel(): void {
    if (this.state === EMPTY) return;
    this.set(EMPTY);
  }

  /**
   * Убирает последнюю поставленную точку.
   *
   * Позволяет исправить только вторую точку, не начиная заново: на чертеже попасть
   * в засечку размерной линии с первого раза удаётся не всегда.
   */
  undo(): void {
    if (this.state.phase === 'idle') return;

    if (this.state.phase === 'complete') {
      this.set({ phase: 'awaiting-second', a: this.state.a, b: null, hover: this.state.b });
      return;
    }

    this.set(EMPTY);
  }

  dispose(): void {
    if (this.frame !== null) {
      cancelFrame(this.frame);
      this.frame = null;
    }
    this.listeners.clear();
  }

  private tooClose(first: NormalizedPoint, second: NormalizedPoint): boolean {
    return (
      Math.abs(first.x - second.x) < MIN_NORMALIZED_SEPARATION &&
      Math.abs(first.y - second.y) < MIN_NORMALIZED_SEPARATION
    );
  }

  private set(next: ScaleDraftState): void {
    this.state = next;
    this.scheduleNotify();
  }

  /**
   * Не больше одного уведомления за кадр.
   *
   * Указатель шлёт события чаще, чем браузер рисует; без склейки слой наложения
   * перерисовывался бы вхолостую.
   */
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

const requestFrame = (callback: () => void): number => {
  if (typeof requestAnimationFrame === 'function') {
    return requestAnimationFrame(callback);
  }
  // Фолбэк для тестов и серверной отрисовки, где кадров нет.
  return setTimeout(callback, 16) as unknown as number;
};

const cancelFrame = (handle: number): void => {
  if (typeof cancelAnimationFrame === 'function') {
    cancelAnimationFrame(handle);
    return;
  }
  clearTimeout(handle);
};
