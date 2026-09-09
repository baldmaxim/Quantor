import { fireEvent, render, screen } from '@testing-library/react';
import { Profiler, act } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { DrawingViewport, type ViewportSheet } from './DrawingViewport';
import { Camera } from '@/lib/viewer/camera';
import { ScaleDraft } from '@/lib/viewer/scale-draft';
import { ToolController } from '@/lib/viewer/tool-controller';
import type { RenderBackend, RenderRequest } from '@/lib/viewer/backend';

/**
 * Холст рабочей области.
 *
 * jsdom не даёт двумерный контекст, поэтому проверяется не картинка, а то, что и должно
 * проверяться автоматически: реакция на жесты и то, что отрисовка не перезапускает сама
 * себя. Оба дефекта уже случались и с экрана выглядели одинаково — «зум не работает».
 */

// Лист A1 после /Rotate 90 — то, что отдаёт pdf.js для эталонного пакета.
const SHEET: ViewportSheet = { pageIndex: 72, width: 2384, height: 1684 };

class FakeBackend implements RenderBackend {
  readonly name = 'fake';
  readonly pageCount = 77;
  renders: number[] = [];

  async geometry() {
    return { width: SHEET.width, height: SHEET.height, rotation: 0 as const };
  }

  async render({ scale, canvas, signal }: RenderRequest): Promise<void> {
    if (signal.aborted) return;
    this.renders.push(scale);
    canvas.width = Math.floor(SHEET.width * scale);
    canvas.height = Math.floor(SHEET.height * scale);
  }

  destroy(): void {}
}

/**
 * Отрисовщик, который не заканчивает работу сам.
 *
 * Нужен, чтобы поймать наложение задач: настоящий pdf.js рисует не мгновенно, а
 * `FakeBackend` возвращается в том же тике и потому наложиться физически не может.
 */
class SlowBackend implements RenderBackend {
  readonly name = 'slow';
  readonly pageCount = 77;
  /** Наибольшее число одновременно живых, то есть неотменённых, задач. */
  maxLive = 0;
  private readonly inFlight: AbortSignal[] = [];

  async geometry() {
    return { width: SHEET.width, height: SHEET.height, rotation: 0 as const };
  }

  async render({ signal }: RenderRequest): Promise<void> {
    this.inFlight.push(signal);
    const live = this.inFlight.filter((item) => !item.aborted).length;
    this.maxLive = Math.max(this.maxLive, live);
    // Задача не завершается: её обязан оборвать сам холст, а не время.
    await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve()));
  }

  destroy(): void {}
}

const scaleOf = (element: HTMLElement): number => {
  const match = /scale\(([\d.]+)\)/.exec(element.style.transform);
  return match?.[1] ? Number(match[1]) : 1;
};

/**
 * Ждёт кадр анимации.
 *
 * Камера объединяет уведомления в кадр — за жест приходит столько обновлений, сколько
 * браузер успел показать кадров. Значит, стили меняются не в том же тике, что событие.
 */
const flushFrame = async (): Promise<void> => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 32));
  });
};

const stackOf = (): HTMLElement => {
  const viewport = screen.getByTestId('viewport');
  const stack = viewport.firstElementChild;
  if (!(stack instanceof HTMLElement)) throw new Error('стопка холстов не найдена');
  return stack;
};

const setup = (overrides: Partial<Parameters<typeof DrawingViewport>[0]> = {}) => {
  const camera = new Camera();
  const backend = new FakeBackend();

  const view = render(
    <DrawingViewport
      backend={backend}
      sheet={SHEET}
      regions={[]}
      hiddenTypes={new Set()}
      overlayVisible
      selectedId={null}
      onSelect={vi.fn()}
      camera={camera}
      tool="pointer"
      {...overrides}
    />,
  );

  return { camera, backend, view };
};

describe('холст рабочей области', () => {
  it('колесо меняет масштаб стопки холстов', async () => {
    const { camera } = setup();
    await flushFrame();
    const scaleBefore = camera.getState().scale;
    const styleBefore = scaleOf(stackOf());

    // Прокрутка вверх — приближение.
    await act(async () => {
      fireEvent.wheel(screen.getByTestId('viewport'), { deltaY: -100 });
    });
    await flushFrame();

    expect(camera.getState().scale).toBeGreaterThan(scaleBefore);
    // Масштаб применяется стилями сразу, не дожидаясь перерисовки PDF: иначе жест
    // выглядит так, будто зума нет вовсе.
    expect(scaleOf(stackOf())).toBeGreaterThan(styleBefore);
  });

  it('прокрутка вниз отдаляет', async () => {
    const { camera } = setup();
    const viewport = screen.getByTestId('viewport');

    // Отходим от нижнего предела: в jsdom область нулевая, и вписанный лист сразу
    // упирается в минимальный масштаб.
    await act(async () => {
      for (let tick = 0; tick < 5; tick += 1) fireEvent.wheel(viewport, { deltaY: -100 });
    });
    await flushFrame();
    const scaleBefore = camera.getState().scale;
    const styleBefore = scaleOf(stackOf());

    await act(async () => {
      fireEvent.wheel(viewport, { deltaY: 100 });
    });
    await flushFrame();

    expect(camera.getState().scale).toBeLessThan(scaleBefore);
    expect(scaleOf(stackOf())).toBeLessThan(styleBefore);
  });

  it('перерисовка не перезапускается на каждый рендер родителя', async () => {
    // Регрессия: объект листа пересоздавался на каждый рендер, эффект отрисовки видел
    // новую зависимость, обрывал начатую задачу и запускал новую. Рендер при этом
    // случался на каждый щелчок колеса — и страница не дорисовывалась никогда.
    const { backend, camera, view } = setup();
    const initial = backend.renders.length;

    for (let repeat = 0; repeat < 5; repeat += 1) {
      await act(async () => {
        view.rerender(
          <DrawingViewport
            backend={backend}
            // Новый объект с теми же значениями — ровно то, что делал родитель.
            sheet={{ ...SHEET }}
            regions={[]}
            hiddenTypes={new Set()}
            overlayVisible
            selectedId={null}
            onSelect={vi.fn()}
            camera={camera}
            tool="pointer"
            // Обработчик приходит стрелкой, как из рабочей области: его новая ссылка
            // не должна ничего перезапускать.
            onViewChange={() => undefined}
          />,
        );
      });
    }

    expect(backend.renders.length).toBe(initial);
  });

  it('две отрисовки не идут по одному холсту разом', async () => {
    // Регрессия, найденная живым открытием чертежа: первая вписка листа и перерисовка
    // после зума шли параллельно, каждая со своим AbortController, и обе звали render()
    // на одном холсте. pdf.js 6 отвечает на это отказом, и лист не открывался вовсе —
    // с экрана это выглядело как PDF_RENDER_FAILED на ровном месте.
    const backend = new SlowBackend();
    setup({ backend });
    await flushFrame();

    fireEvent.wheel(screen.getByTestId('viewport'), { deltaY: -100 });
    // Перерисовка по зуму отложена на RERENDER_DELAY_MS; ждём заведомо дольше.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 260));
    });

    expect(backend.maxLive).toBe(1);
  });

  it('колесо с Shift двигает лист по горизонтали, не меняя масштаб', async () => {
    const { camera } = setup();
    await flushFrame();
    const before = camera.getState();

    await act(async () => {
      fireEvent.wheel(screen.getByTestId('viewport'), { deltaY: 120, shiftKey: true });
    });

    const after = camera.getState();
    expect(after.scale).toBe(before.scale);
    expect(after.offsetX).toBeLessThan(before.offsetX);
    expect(after.offsetY).toBe(before.offsetY);
  });

  it('средняя кнопка панорамирует любым инструментом', async () => {
    // В AutoCAD и Revit лист двигают нажатым колесом. Инструмент при этом не меняют.
    const { camera } = setup({ tool: 'pointer' });
    const viewport = screen.getByTestId('viewport');
    await flushFrame();
    const before = camera.getState();

    await act(async () => {
      fireEvent.pointerDown(viewport, { button: 1, pointerId: 2, clientX: 100, clientY: 100 });
      fireEvent.pointerMove(viewport, { pointerId: 2, clientX: 130, clientY: 150 });
    });

    const after = camera.getState();
    expect(after.offsetX - before.offsetX).toBeCloseTo(30, 5);
    expect(after.offsetY - before.offsetY).toBeCloseTo(50, 5);
  });

  it('панорамирование не трогает масштаб', async () => {
    const { camera } = setup({ tool: 'pan' });
    const viewport = screen.getByTestId('viewport');
    const before = camera.getState();

    await act(async () => {
      fireEvent.pointerDown(viewport, { button: 0, pointerId: 1, clientX: 100, clientY: 100 });
      fireEvent.pointerMove(viewport, { pointerId: 1, clientX: 160, clientY: 140 });
    });

    const after = camera.getState();
    expect(after.scale).toBe(before.scale);
    expect(after.offsetX - before.offsetX).toBeCloseTo(60, 5);
    expect(after.offsetY - before.offsetY).toBeCloseTo(40, 5);
  });
});

describe('инструмент масштаба на холсте', () => {
  it('щелчки ставят две точки, не обращаясь к серверу', async () => {
    // Черновик живёт в памяти до подтверждения: сеть трогается один раз, кнопкой.
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const draft = new ScaleDraft();
    setup({ tool: 'scale', scaleDraft: draft });
    await flushFrame();

    // В jsdom контейнер нулевого размера, поэтому лист вписан в очень мелкий масштаб:
    // координаты берутся из фактической ширины холста, а не из вымышленных пикселей.
    const viewport = screen.getByTestId('viewport');
    const width = stackOf().querySelectorAll('canvas')[0]?.clientWidth || 1;
    fireEvent.pointerDown(viewport, { button: 0, clientX: 0, clientY: 0 });
    fireEvent.pointerDown(viewport, { button: 0, clientX: width, clientY: 0 });

    expect(draft.getState().phase).toBe('complete');
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('движение указателя не обращается к серверу и не перерисовывает страницу', async () => {
    // Самая дорогая ошибка этого экрана: перерисовка PDF на каждое движение мыши.
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const draft = new ScaleDraft();
    const { backend } = setup({ tool: 'scale', scaleDraft: draft });
    await flushFrame();
    const rendersBefore = backend.renders.length;

    const viewport = screen.getByTestId('viewport');
    fireEvent.pointerDown(viewport, { button: 0, clientX: 10, clientY: 10 });
    for (let step = 0; step < 20; step += 1) {
      fireEvent.pointerMove(viewport, { clientX: 20 + step * 5, clientY: 30 });
    }
    await flushFrame();

    expect(backend.renders.length).toBe(rendersBefore);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(draft.getState().hover).not.toBeNull();
    fetchSpy.mockRestore();
  });

  it('точки хранятся нормализованными и переживают зум', async () => {
    // Нормализованная точка не зависит от масштаба вида: иначе калибровка «поехала» бы
    // от одного поворота колеса между двумя щелчками.
    const draft = new ScaleDraft();
    setup({ tool: 'scale', scaleDraft: draft });
    await flushFrame();

    const viewport = screen.getByTestId('viewport');
    fireEvent.pointerDown(viewport, { button: 0, clientX: 100, clientY: 50 });
    const first = draft.getState().a;

    fireEvent.wheel(viewport, { deltaY: -100, clientX: 100, clientY: 50 });
    await flushFrame();

    expect(draft.getState().a).toEqual(first);
  });

  it('слой черновика скрыт, пока инструмент не выбран', async () => {
    const draft = new ScaleDraft();
    const { view } = setup({ tool: 'pointer', scaleDraft: draft });
    await flushFrame();

    expect(screen.getByTestId('scale-layer').className).toContain('hidden');

    view.rerender(
      <DrawingViewport
        backend={new FakeBackend()}
        sheet={SHEET}
        regions={[]}
        hiddenTypes={new Set()}
        overlayVisible
        selectedId={null}
        onSelect={vi.fn()}
        camera={new Camera()}
        tool="scale"
        scaleDraft={draft}
      />,
    );

    expect(screen.getByTestId('scale-layer').className).not.toContain('hidden');
  });

  it('выбор области инструментом масштаба не срабатывает', async () => {
    // Иначе щелчок по штампу выбирал бы область вместо постановки точки.
    const draft = new ScaleDraft();
    const onSelect = vi.fn();
    setup({ tool: 'scale', scaleDraft: draft, onSelect });
    await flushFrame();

    fireEvent.pointerDown(screen.getByTestId('viewport'), {
      button: 0,
      clientX: 30,
      clientY: 30,
    });

    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe('слой измерений', () => {
  const wallMeasurement = {
    id: 'm1',
    geometryType: 'line' as const,
    points: [
      { x: 0.1, y: 0.5 },
      { x: 0.9, y: 0.5 },
    ],
    colorKey: 'accent',
  };

  it('рисование не перерисовывает страницу и не ходит в сеть', async () => {
    // Самая дорогая ошибка этого экрана: перерисовка PDF на каждое движение мыши.
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const tools = new ToolController('polygon');
    const { backend } = setup({ tools });
    await flushFrame();
    const rendersBefore = backend.renders.length;

    const viewport = screen.getByTestId('viewport');
    fireEvent.pointerDown(viewport, { button: 0, clientX: 0, clientY: 0 });
    for (let step = 0; step < 20; step += 1) {
      fireEvent.pointerMove(viewport, { clientX: step, clientY: step });
    }
    await flushFrame();

    expect(backend.renders.length).toBe(rendersBefore);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('выбор измерения не перерисовывает страницу', async () => {
    const tools = new ToolController('select');
    const { backend } = setup({ tools, measurements: [wallMeasurement] });
    await flushFrame();
    const rendersBefore = backend.renders.length;

    tools.send({ type: 'selectMeasurement', measurementId: 'm1' });
    await flushFrame();

    expect(backend.renders.length).toBe(rendersBefore);
  });

  it('перетаскивание вершины не перерисовывает страницу и не ходит в сеть', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const tools = new ToolController('select');
    const { backend } = setup({ tools, measurements: [wallMeasurement] });
    await flushFrame();
    const rendersBefore = backend.renders.length;

    tools.send({
      type: 'startVertexDrag',
      measurementId: 'm1',
      vertexIndex: 0,
      points: wallMeasurement.points,
    });
    for (let step = 0; step < 15; step += 1) {
      tools.send({ type: 'moveVertex', point: { x: 0.2 + step * 0.01, y: 0.5 } });
    }
    await flushFrame();

    expect(backend.renders.length).toBe(rendersBefore);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it('геометрия уходит наружу один раз, по отпусканию', async () => {
    const dragged = vi.fn();
    const tools = new ToolController('select');
    tools.setHandlers({ onVertexDragged: dragged });
    setup({ tools, measurements: [wallMeasurement] });
    await flushFrame();

    tools.send({
      type: 'startVertexDrag',
      measurementId: 'm1',
      vertexIndex: 0,
      points: wallMeasurement.points,
    });
    tools.send({ type: 'moveVertex', point: { x: 0.3, y: 0.5 } });
    tools.send({ type: 'moveVertex', point: { x: 0.4, y: 0.5 } });

    expect(dragged).not.toHaveBeenCalled();

    tools.send({ type: 'finishVertexDrag' });

    expect(dragged).toHaveBeenCalledTimes(1);
    expect(dragged.mock.calls[0]?.[0].points[0]).toEqual({ x: 0.4, y: 0.5 });
  });

  it('завершённая фигура отдаётся один раз', async () => {
    const completed = vi.fn();
    const tools = new ToolController('count');
    tools.setHandlers({ onCompleted: completed });
    setup({ tools });
    await flushFrame();

    const viewport = screen.getByTestId('viewport');
    fireEvent.pointerDown(viewport, { button: 0, clientX: 0, clientY: 0 });

    expect(completed).toHaveBeenCalledTimes(1);
    expect(completed.mock.calls[0]?.[0].mode).toBe('count');
  });

  it('слой скрыт, пока инструменты не подключены', async () => {
    setup({});
    await flushFrame();

    expect(screen.getByTestId('measurement-layer').className).toContain('hidden');
  });

  it('рисование не порождает ни одного коммита React', async () => {
    // Отсутствие перерисовки PDF уже проверено выше. Здесь другое утверждение: дерево
    // React вообще не коммитится, пока идёт жест. Одно не следует из другого — состояние
    // могло бы меняться и приводить к коммиту, не задевая холст страницы (ADR-0004).
    const commits: string[] = [];
    const camera = new Camera();
    const tools = new ToolController('polygon');

    render(
      <Profiler id="viewport" onRender={(_id, phase) => commits.push(phase)}>
        <DrawingViewport
          backend={new FakeBackend()}
          sheet={SHEET}
          regions={[]}
          hiddenTypes={new Set()}
          overlayVisible
          selectedId={null}
          onSelect={vi.fn()}
          camera={camera}
          tool="pointer"
          tools={tools}
        />
      </Profiler>,
    );
    await flushFrame();
    const before = commits.length;

    const viewport = screen.getByTestId('viewport');
    fireEvent.pointerDown(viewport, { button: 0, clientX: 10, clientY: 10 });
    for (let step = 0; step < 40; step += 1) {
      fireEvent.pointerMove(viewport, { clientX: 10 + step, clientY: 10 + step });
    }
    await flushFrame();

    expect(commits.length - before).toBe(0);
  });

  it('тысяча измерений отрисовывается без ошибки', async () => {
    // Не замер производительности — тот делает промт 14. Здесь только проверка, что слой
    // вообще работает на объёме, а не падает на сотой фигуре.
    const many = Array.from({ length: 1000 }, (_, index) => ({
      id: `m${index}`,
      geometryType: 'count' as const,
      points: [{ x: (index % 100) / 100, y: Math.floor(index / 100) / 10 }],
      colorKey: 'accent',
    }));

    const tools = new ToolController('select');
    expect(() => setup({ tools, measurements: many })).not.toThrow();
    await flushFrame();
  });
});
