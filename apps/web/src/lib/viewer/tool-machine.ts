/**
 * Машина состояний инструментов обмера.
 *
 * Чистое ядро взаимодействия: не знает ни о DOM, ни о canvas, ни о сети, ни о TanStack
 * Query. На вход приходят смысловые события в нормализованных координатах, на выходе —
 * состояние черновика. Всё, что происходит на экране, строится поверх.
 *
 * Разделение не косметическое. Логика рисования — это десяток переходов, каждый из которых
 * можно сломать; проверить их в браузере вместе с отрисовкой и сетью почти невозможно,
 * а здесь каждый закрывается табличным тестом.
 *
 * ## Почему точки нормализованные
 *
 * Черновик переживает зум и панорамирование: пользователь ставит первую вершину, приближает
 * лист, ставит вторую. Если бы точки хранились в экранных пикселях, фигура «поехала» бы от
 * одного поворота колеса (ADR-0008).
 */

import type { NormalizedPoint } from '@/lib/viewer/coordinates';

/** Что сейчас делает пользователь. */
export type ToolMode = 'select' | 'pan' | 'scale' | 'count' | 'line' | 'polyline' | 'polygon';

/** Режимы, которые рисуют геометрию обмера. Остальные — навигация и выбор. */
export const DRAWING_MODES: readonly ToolMode[] = ['count', 'line', 'polyline', 'polygon'];

/** Сколько вершин нужно, чтобы фигуру можно было завершить. */
const MIN_POINTS: Record<string, number> = { count: 1, line: 2, polyline: 2, polygon: 3 };

/** Сколько вершин завершают фигуру автоматически. У остальных завершение явное. */
const AUTO_COMPLETE_AT: Record<string, number> = { count: 1, line: 2 };

/**
 * Точки ближе этого расстояния считаются одной.
 *
 * Отсекает дребезг и случайный двойной щелчок. Не проверка геометрии: та живёт на сервере,
 * где известен размер страницы.
 */
const MIN_SEPARATION = 1e-6;

export interface ToolState {
  readonly mode: ToolMode;
  /** Вершины черновика в порядке постановки. Пусто — рисование не начато. */
  readonly points: readonly NormalizedPoint[];
  /** Точка под курсором: за ней тянется предварительное звено. */
  readonly hover: NormalizedPoint | null;
  /** Выбранное сохранённое измерение. Не часть черновика: их можно иметь одновременно. */
  readonly selectedId: string | null;
  /** Перетаскиваемая вершина выбранного измерения. */
  readonly drag: VertexDrag | null;
  /**
   * Временное панорамирование: зажат пробел.
   *
   * Отдельно от режима намеренно — отпустив пробел, пользователь возвращается к своему
   * инструменту с несломанным черновиком.
   */
  readonly panOverride: boolean;
}

export interface VertexDrag {
  readonly measurementId: string;
  readonly vertexIndex: number;
  readonly points: readonly NormalizedPoint[];
}

/** Готовая фигура: то, что уходит наружу на сохранение. */
export interface CompletedShape {
  readonly mode: ToolMode;
  readonly points: readonly NormalizedPoint[];
}

export type ToolEvent =
  | { readonly type: 'setMode'; readonly mode: ToolMode }
  | { readonly type: 'pointerDown'; readonly point: NormalizedPoint }
  | { readonly type: 'pointerMove'; readonly point: NormalizedPoint | null }
  | { readonly type: 'finish' }
  | { readonly type: 'cancel' }
  | { readonly type: 'backspace' }
  | { readonly type: 'selectMeasurement'; readonly measurementId: string | null }
  | {
      readonly type: 'startVertexDrag';
      readonly measurementId: string;
      readonly vertexIndex: number;
      readonly points: readonly NormalizedPoint[];
    }
  | { readonly type: 'moveVertex'; readonly point: NormalizedPoint }
  | { readonly type: 'finishVertexDrag' }
  | { readonly type: 'setPanOverride'; readonly pressed: boolean };

/** Результат перехода: новое состояние и то, что готово уйти наружу. */
export interface ToolTransition {
  readonly state: ToolState;
  /** Заполнено — фигура завершена и должна быть сохранена. */
  readonly completed: CompletedShape | null;
  /** Заполнено — перетаскивание закончено, геометрию нужно записать. */
  readonly draggedVertex: VertexDrag | null;
}

export const initialToolState = (mode: ToolMode = 'select'): ToolState => ({
  mode,
  points: [],
  hover: null,
  selectedId: null,
  drag: null,
  panOverride: false,
});

const isDrawing = (mode: ToolMode): boolean => DRAWING_MODES.includes(mode);

const tooClose = (first: NormalizedPoint, second: NormalizedPoint): boolean =>
  Math.abs(first.x - second.x) < MIN_SEPARATION && Math.abs(first.y - second.y) < MIN_SEPARATION;

const finite = (point: NormalizedPoint): boolean =>
  Number.isFinite(point.x) && Number.isFinite(point.y);

const inSheet = (point: NormalizedPoint): boolean =>
  point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1;

/** Точка годится в черновик: конечна и лежит на листе. */
const acceptable = (point: NormalizedPoint): boolean => finite(point) && inSheet(point);

const still = (state: ToolState): ToolTransition => ({
  state,
  completed: null,
  draggedVertex: null,
});

/**
 * Единственный переход машины.
 *
 * Чистая функция: то же состояние и то же событие всегда дают тот же результат. Отсюда и
 * возможность проверить все ветки таблицей, не поднимая браузер.
 */
export const applyToolEvent = (state: ToolState, event: ToolEvent): ToolTransition => {
  switch (event.type) {
    case 'setMode': {
      if (event.mode === state.mode) return still(state);
      // Смена инструмента отбрасывает черновик: точки, поставленные линией, ничего
      // не значат для многоугольника.
      return still({ ...initialToolState(event.mode), selectedId: state.selectedId });
    }

    case 'setPanOverride':
      return still({ ...state, panOverride: event.pressed });

    case 'selectMeasurement':
      // Выбор не трогает черновик: можно тянуть вершину и одновременно видеть выбранное.
      return still({ ...state, selectedId: event.measurementId });

    case 'pointerDown': {
      // Панорамирование и выбор рисованием не занимаются.
      if (state.panOverride || !isDrawing(state.mode)) return still(state);
      if (!acceptable(event.point)) return still(state);

      const last = state.points.at(-1);
      // Повтор той же точки — дребезг, а не вершина.
      if (last && tooClose(last, event.point)) return still(state);

      const points = [...state.points, event.point];
      const autoAt = AUTO_COMPLETE_AT[state.mode];

      if (autoAt !== undefined && points.length >= autoAt) {
        // Счёт и линия завершаются сами: у них известно, сколько точек нужно.
        return {
          state: { ...initialToolState(state.mode), selectedId: state.selectedId },
          completed: { mode: state.mode, points },
          draggedVertex: null,
        };
      }

      return still({ ...state, points, hover: event.point });
    }

    case 'pointerMove': {
      if (state.drag !== null) return still(state);
      if (!isDrawing(state.mode)) return still(state);
      return still({ ...state, hover: event.point });
    }

    case 'finish': {
      if (!isDrawing(state.mode)) return still(state);

      const minimum = MIN_POINTS[state.mode] ?? 1;
      // Незавершаемая фигура не сбрасывается: пользователь дощёлкивает недостающие
      // вершины, а не начинает заново.
      if (state.points.length < minimum) return still(state);

      return {
        state: { ...initialToolState(state.mode), selectedId: state.selectedId },
        completed: { mode: state.mode, points: state.points },
        draggedVertex: null,
      };
    }

    case 'cancel': {
      // Отмена во время перетаскивания возвращает вершину на место: геометрия на сервере
      // не менялась, значит и на экране меняться не должна.
      if (state.drag !== null) {
        return still({ ...state, drag: null });
      }
      return still({ ...initialToolState(state.mode), selectedId: state.selectedId });
    }

    case 'backspace': {
      if (!isDrawing(state.mode) || state.points.length === 0) return still(state);
      return still({ ...state, points: state.points.slice(0, -1) });
    }

    case 'startVertexDrag': {
      if (event.vertexIndex < 0 || event.vertexIndex >= event.points.length) {
        return still(state);
      }
      return still({
        ...state,
        selectedId: event.measurementId,
        drag: {
          measurementId: event.measurementId,
          vertexIndex: event.vertexIndex,
          points: [...event.points],
        },
      });
    }

    case 'moveVertex': {
      const drag = state.drag;
      if (drag === null) return still(state);
      if (!acceptable(event.point)) return still(state);

      const points = [...drag.points];
      points[drag.vertexIndex] = event.point;
      return still({ ...state, drag: { ...drag, points } });
    }

    case 'finishVertexDrag': {
      const drag = state.drag;
      if (drag === null) return still(state);
      // Наружу уходит один раз — по отпусканию кнопки. Обращение к серверу на каждое
      // движение указателя превратило бы правку вершины в поток запросов.
      return { state: { ...state, drag: null }, completed: null, draggedVertex: drag };
    }

    default:
      return still(state);
  }
};
