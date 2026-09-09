/**
 * Императивная обёртка над машиной состояний инструментов.
 *
 * Машина чистая и ничего не знает о кадрах; холсту нужна подписка. Обёртка — единственное
 * место, где они встречаются: она держит текущее состояние, склеивает уведомления в кадр
 * и отдаёт наружу готовые фигуры.
 *
 * Состояние живёт здесь, а не в React, по той же причине, что и камера: точка под курсором
 * меняется на каждом движении мыши, и перерисовывать ей дерево компонентов значило бы
 * ронять частоту кадров вместе со всеми панелями (ADR-0004).
 */

import {
  applyToolEvent,
  initialToolState,
  type CompletedShape,
  type ToolEvent,
  type ToolMode,
  type ToolState,
  type VertexDrag,
} from '@/lib/viewer/tool-machine';

export interface ToolControllerHandlers {
  /** Фигура завершена и должна быть сохранена. */
  readonly onCompleted?: (shape: CompletedShape) => void;
  /** Перетаскивание вершины закончено: пора записать геометрию. */
  readonly onVertexDragged?: (drag: VertexDrag) => void;
}

export class ToolController {
  private state: ToolState;
  private listeners = new Set<(state: ToolState) => void>();
  private frame: number | null = null;
  private handlers: ToolControllerHandlers = {};

  constructor(mode: ToolMode = 'select') {
    this.state = initialToolState(mode);
  }

  getState(): ToolState {
    return this.state;
  }

  /**
   * Подключает обработчики завершения.
   *
   * Отдельно от конструктора: рабочая область пересоздаёт замыкания на каждый рендер,
   * а контроллер должен пережить их все.
   */
  setHandlers(handlers: ToolControllerHandlers): void {
    this.handlers = handlers;
  }

  subscribe(listener: (state: ToolState) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Прогоняет событие через машину и уведомляет подписчиков, если состояние изменилось. */
  send(event: ToolEvent): void {
    const transition = applyToolEvent(this.state, event);
    const changed = transition.state !== this.state;
    this.state = transition.state;

    if (changed) this.scheduleNotify();

    // Обработчики зовутся синхронно: сохранение не должно ждать кадра отрисовки.
    if (transition.completed) this.handlers.onCompleted?.(transition.completed);
    if (transition.draggedVertex) this.handlers.onVertexDragged?.(transition.draggedVertex);
  }

  dispose(): void {
    if (this.frame !== null) {
      cancelFrame(this.frame);
      this.frame = null;
    }
    this.listeners.clear();
    this.handlers = {};
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
