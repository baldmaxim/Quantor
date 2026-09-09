/**
 * Переходы машины инструментов.
 *
 * Табличные тесты, а не снимки: снимок сказал бы «что-то отрисовалось», а нужно знать,
 * что именно произошло с вершинами. Каждая ветка перехода закрыта отдельно, включая
 * недопустимые последовательности событий.
 */

import { describe, expect, it } from 'vitest';

import type { NormalizedPoint } from '@/lib/viewer/coordinates';
import {
  applyToolEvent,
  initialToolState,
  type ToolEvent,
  type ToolMode,
  type ToolState,
} from '@/lib/viewer/tool-machine';

const p = (x: number, y: number): NormalizedPoint => ({ x, y });

/** Прогоняет цепочку событий и возвращает последний переход. */
const run = (mode: ToolMode, events: ToolEvent[]) => {
  let state: ToolState = initialToolState(mode);
  let transition = applyToolEvent(state, { type: 'setMode', mode });
  for (const event of events) {
    transition = applyToolEvent(state, event);
    state = transition.state;
  }
  return { state, transition };
};

describe('выбор режима', () => {
  it('смена инструмента отбрасывает черновик', () => {
    // Точки, поставленные линией, ничего не значат для многоугольника.
    const { state } = run('polygon', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.2, 0.2) },
      { type: 'setMode', mode: 'line' },
    ]);

    expect(state.mode).toBe('line');
    expect(state.points).toHaveLength(0);
  });

  it('повторный выбор того же инструмента черновик не трогает', () => {
    const { state } = run('polygon', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'setMode', mode: 'polygon' },
    ]);

    expect(state.points).toHaveLength(1);
  });

  it('выбранное измерение переживает смену инструмента', () => {
    const { state } = run('select', [
      { type: 'selectMeasurement', measurementId: 'm1' },
      { type: 'setMode', mode: 'count' },
    ]);

    expect(state.selectedId).toBe('m1');
  });
});

describe('счёт', () => {
  it('завершается с первого щелчка', () => {
    const { transition, state } = run('count', [{ type: 'pointerDown', point: p(0.5, 0.5) }]);

    expect(transition.completed).toEqual({ mode: 'count', points: [p(0.5, 0.5)] });
    // Черновик сброшен: следующая метка начинается с нуля.
    expect(state.points).toHaveLength(0);
  });

  it('щелчки подряд дают отдельные метки', () => {
    let state = initialToolState('count');
    const completed = [];
    for (const point of [p(0.1, 0.1), p(0.2, 0.2), p(0.3, 0.3)]) {
      const step = applyToolEvent(state, { type: 'pointerDown', point });
      state = step.state;
      if (step.completed) completed.push(step.completed);
    }

    expect(completed).toHaveLength(3);
  });
});

describe('линия', () => {
  it('завершается на втором щелчке', () => {
    const { transition } = run('line', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.9, 0.1) },
    ]);

    expect(transition.completed?.points).toEqual([p(0.1, 0.1), p(0.9, 0.1)]);
  });

  it('после первой точки ещё не завершена', () => {
    const { transition, state } = run('line', [{ type: 'pointerDown', point: p(0.1, 0.1) }]);

    expect(transition.completed).toBeNull();
    expect(state.points).toHaveLength(1);
  });
});

describe('ломаная', () => {
  it('сама не завершается', () => {
    const { transition, state } = run('polyline', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.5, 0.1) },
      { type: 'pointerDown', point: p(0.9, 0.4) },
    ]);

    expect(transition.completed).toBeNull();
    expect(state.points).toHaveLength(3);
  });

  it('завершается явно и отдаёт все вершины', () => {
    const { transition } = run('polyline', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.5, 0.1) },
      { type: 'finish' },
    ]);

    expect(transition.completed?.points).toHaveLength(2);
  });

  it('одна точка не завершает и не сбрасывает черновик', () => {
    // Пользователь дощёлкивает недостающую вершину, а не начинает заново.
    const { transition, state } = run('polyline', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'finish' },
    ]);

    expect(transition.completed).toBeNull();
    expect(state.points).toHaveLength(1);
  });
});

describe('многоугольник', () => {
  it('меньше трёх вершин не завершается', () => {
    const { transition, state } = run('polygon', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.9, 0.1) },
      { type: 'finish' },
    ]);

    expect(transition.completed).toBeNull();
    expect(state.points).toHaveLength(2);
  });

  it('три вершины завершаются', () => {
    const { transition } = run('polygon', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.9, 0.1) },
      { type: 'pointerDown', point: p(0.9, 0.9) },
      { type: 'finish' },
    ]);

    expect(transition.completed?.points).toHaveLength(3);
  });

  it('первая вершина не дублируется при завершении', () => {
    // Замыкание — свойство типа, а не данных: дублирующая точка ломала бы счёт вершин.
    const { transition } = run('polygon', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.9, 0.1) },
      { type: 'pointerDown', point: p(0.9, 0.9) },
      { type: 'finish' },
    ]);

    const points = transition.completed?.points ?? [];
    expect(points).toHaveLength(3);
    expect(points.at(-1)).not.toEqual(points[0]);
  });
});

describe('недопустимые точки', () => {
  it.each([
    ['вне листа справа', p(1.5, 0.5)],
    ['вне листа слева', p(-0.1, 0.5)],
    ['не число', p(Number.NaN, 0.5)],
    ['бесконечность', p(Number.POSITIVE_INFINITY, 0.5)],
  ])('%s не становится вершиной', (_name, point) => {
    const { state } = run('polygon', [{ type: 'pointerDown', point }]);

    expect(state.points).toHaveLength(0);
  });

  it('повтор той же точки не добавляет вершину', () => {
    // Два попадания в один пиксель — дребезг, а не намерение.
    const { state } = run('polygon', [
      { type: 'pointerDown', point: p(0.5, 0.5) },
      { type: 'pointerDown', point: p(0.5, 0.5) },
    ]);

    expect(state.points).toHaveLength(1);
  });

  it('углы листа допустимы', () => {
    // Обмер по краю чертежа — обычное дело.
    const { state } = run('polygon', [
      { type: 'pointerDown', point: p(0, 0) },
      { type: 'pointerDown', point: p(1, 1) },
    ]);

    expect(state.points).toHaveLength(2);
  });
});

describe('отмена и шаг назад', () => {
  it('отмена очищает черновик', () => {
    const { state } = run('polygon', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.5, 0.5) },
      { type: 'cancel' },
    ]);

    expect(state.points).toHaveLength(0);
    expect(state.mode).toBe('polygon');
  });

  it('отмена не сбрасывает выбранное измерение', () => {
    const { state } = run('polygon', [
      { type: 'selectMeasurement', measurementId: 'm1' },
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'cancel' },
    ]);

    expect(state.selectedId).toBe('m1');
  });

  it('шаг назад убирает последнюю вершину', () => {
    const { state } = run('polygon', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'pointerDown', point: p(0.5, 0.5) },
      { type: 'backspace' },
    ]);

    expect(state.points).toEqual([p(0.1, 0.1)]);
  });

  it('шаг назад в пустом черновике ничего не делает', () => {
    const { state } = run('polygon', [{ type: 'backspace' }]);

    expect(state.points).toHaveLength(0);
  });
});

describe('временное панорамирование', () => {
  it('не ломает черновик', () => {
    // Отпустив пробел, пользователь возвращается к своему инструменту.
    const { state } = run('polygon', [
      { type: 'pointerDown', point: p(0.1, 0.1) },
      { type: 'setPanOverride', pressed: true },
      { type: 'setPanOverride', pressed: false },
    ]);

    expect(state.points).toHaveLength(1);
    expect(state.mode).toBe('polygon');
  });

  it('пока зажат пробел, щелчок не ставит вершину', () => {
    const { state } = run('polygon', [
      { type: 'setPanOverride', pressed: true },
      { type: 'pointerDown', point: p(0.5, 0.5) },
    ]);

    expect(state.points).toHaveLength(0);
  });
});

describe('перетаскивание вершины', () => {
  const shape = [p(0.1, 0.1), p(0.9, 0.1), p(0.9, 0.9)];

  it('меняет только выбранную вершину', () => {
    const { state } = run('select', [
      { type: 'startVertexDrag', measurementId: 'm1', vertexIndex: 1, points: shape },
      { type: 'moveVertex', point: p(0.5, 0.5) },
    ]);

    expect(state.drag?.points).toEqual([p(0.1, 0.1), p(0.5, 0.5), p(0.9, 0.9)]);
  });

  it('отдаёт геометрию один раз, по отпусканию', () => {
    // Обращение к серверу на каждое движение превратило бы правку в поток запросов.
    let state = initialToolState('select');
    const events: ToolEvent[] = [
      { type: 'startVertexDrag', measurementId: 'm1', vertexIndex: 0, points: shape },
      { type: 'moveVertex', point: p(0.2, 0.2) },
      { type: 'moveVertex', point: p(0.3, 0.3) },
      { type: 'moveVertex', point: p(0.4, 0.4) },
    ];
    let dragged = 0;
    for (const event of events) {
      const step = applyToolEvent(state, event);
      state = step.state;
      if (step.draggedVertex) dragged += 1;
    }

    expect(dragged).toBe(0);

    const finished = applyToolEvent(state, { type: 'finishVertexDrag' });

    expect(finished.draggedVertex?.points[0]).toEqual(p(0.4, 0.4));
    expect(finished.state.drag).toBeNull();
  });

  it('отмена возвращает вершину на место', () => {
    // Геометрия на сервере не менялась — значит и на экране меняться не должна.
    const { state } = run('select', [
      { type: 'startVertexDrag', measurementId: 'm1', vertexIndex: 0, points: shape },
      { type: 'moveVertex', point: p(0.4, 0.4) },
      { type: 'cancel' },
    ]);

    expect(state.drag).toBeNull();
  });

  it('несуществующий индекс вершины игнорируется', () => {
    const { state } = run('select', [
      { type: 'startVertexDrag', measurementId: 'm1', vertexIndex: 9, points: shape },
    ]);

    expect(state.drag).toBeNull();
  });

  it('движение вершины без начатого перетаскивания ничего не делает', () => {
    const { state } = run('select', [{ type: 'moveVertex', point: p(0.5, 0.5) }]);

    expect(state.drag).toBeNull();
  });

  it('вершину нельзя вытащить за пределы листа', () => {
    const { state } = run('select', [
      { type: 'startVertexDrag', measurementId: 'm1', vertexIndex: 0, points: shape },
      { type: 'moveVertex', point: p(1.5, 0.5) },
    ]);

    expect(state.drag?.points[0]).toEqual(p(0.1, 0.1));
  });
});

describe('режимы без рисования', () => {
  it.each(['select', 'pan', 'scale'] as const)('%s не ставит вершин', (mode) => {
    const { state } = run(mode, [{ type: 'pointerDown', point: p(0.5, 0.5) }]);

    expect(state.points).toHaveLength(0);
  });

  it('завершение в режиме выбора ничего не отдаёт', () => {
    const { transition } = run('select', [{ type: 'finish' }]);

    expect(transition.completed).toBeNull();
  });
});
