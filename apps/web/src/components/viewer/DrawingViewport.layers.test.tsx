import { fireEvent, render, screen } from '@testing-library/react';
import { Profiler, act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DrawingViewport, type ViewportSheet } from './DrawingViewport';
import type { PageRegion, RenderBackend, RenderRequest } from '@/lib/viewer/backend';
import { Camera } from '@/lib/viewer/camera';
import type { OverlayRegion } from '@/lib/viewer/overlay';
import { FULL_PAGE_MAX_PIXELS, fullPageScaleLimit } from '@/lib/viewer/surface';
import { ToolController } from '@/lib/viewer/tool-controller';

/**
 * Слои по области просмотра и растр листа по видимой части (ADR-0024, ADR-0025).
 *
 * jsdom не даёт двумерного контекста и раскладки, поэтому контекст подменяется записывающим,
 * а размер области — фиксированным. Проверяется то, что ломалось или могло сломаться: память
 * слоёв и растра не растёт с масштабом, слой совпадает с листом после зума, панорама не зовёт
 * pdf.js, а за краем резкой части зовёт ровно один раз и только когда жест затих.
 */

const SHEET: ViewportSheet = { pageIndex: 0, width: 2384, height: 1684 };
const VIEWPORT = { width: 800, height: 600 };

interface Rendered {
  readonly scale: number;
  readonly region: PageRegion | null;
}

class FakeBackend implements RenderBackend {
  readonly name = 'fake';
  readonly pageCount = 1;
  readonly renders: Rendered[] = [];

  async geometry() {
    return { width: SHEET.width, height: SHEET.height, rotation: 0 as const };
  }

  /** Холст получает размер ровно той части листа, что просили, — как у pdf.js-отрисовщика. */
  async render({ scale, canvas, signal, region, pixelRatio = 1 }: RenderRequest): Promise<void> {
    if (signal.aborted) return;
    this.renders.push({ scale, region: region ?? null });
    const density = scale * pixelRatio;
    canvas.width = region ? Math.round(region.width * density) : Math.floor(SHEET.width * density);
    canvas.height = region
      ? Math.round(region.height * density)
      : Math.floor(SHEET.height * density);
  }

  destroy(): void {}
}

interface Recorded {
  readonly arcs: { x: number; y: number }[];
  readonly copies: { x: number; y: number }[];
}

const recorded = new Map<HTMLCanvasElement, Recorded>();

/**
 * Записывающий контекст: метки, копии холста в себя и полная очистка.
 *
 * Полная очистка начинает запись заново — это перерисовка слоя целиком. Очистка полосы запись не
 * трогает: пиксели вне полосы на настоящем холсте тоже остаются.
 */
const fakeContext = (canvas: HTMLCanvasElement): CanvasRenderingContext2D => {
  const record: Recorded = recorded.get(canvas) ?? { arcs: [], copies: [] };
  recorded.set(canvas, record);
  const noop = () => undefined;

  return {
    canvas,
    save: noop,
    restore: noop,
    scale: noop,
    setTransform: noop,
    rect: noop,
    clip: noop,
    clearRect: (x: number, y: number, width: number, height: number) => {
      if (x === 0 && y === 0 && width === canvas.width && height === canvas.height) {
        record.arcs.length = 0;
        record.copies.length = 0;
      }
    },
    drawImage: (_image: unknown, x: number, y: number) => record.copies.push({ x, y }),
    beginPath: noop,
    closePath: noop,
    moveTo: noop,
    lineTo: noop,
    fill: noop,
    stroke: noop,
    strokeRect: noop,
    setLineDash: noop,
    arc: (x: number, y: number) => record.arcs.push({ x, y }),
    fillRect: noop,
    fillStyle: '',
    strokeStyle: '',
    lineWidth: 1,
    globalAlpha: 1,
    globalCompositeOperation: 'source-over',
  } as unknown as CanvasRenderingContext2D;
};

/** Ждёт затихания жеста и цепочку отрисовок: резкая часть, за ней подложка. */
const settle = async (): Promise<void> => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 400));
  });
};

/** Ждёт один кадр камеры — меньше паузы затихания жеста. */
const frame = async (): Promise<void> => {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 40));
  });
};

const layer = (testId: string): HTMLCanvasElement => {
  const element = screen.getByTestId(testId);
  if (!(element instanceof HTMLCanvasElement)) throw new Error(`${testId} не холст`);
  return element;
};

const pageCanvases = (): HTMLCanvasElement[] =>
  Array.from(screen.getByTestId('viewport').firstElementChild?.querySelectorAll('canvas') ?? []);

const COUNT = {
  id: 'm1',
  geometryType: 'count' as const,
  points: [{ x: 0.5, y: 0.5 }],
  colorKey: 'accent',
};

beforeEach(() => {
  recorded.clear();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (
    this: HTMLCanvasElement,
  ) {
    return fakeContext(this);
  } as unknown as typeof HTMLCanvasElement.prototype.getContext);
  vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(VIEWPORT.width);
  vi.spyOn(Element.prototype, 'clientHeight', 'get').mockReturnValue(VIEWPORT.height);
});

afterEach(() => {
  vi.restoreAllMocks();
});

const mount = (overrides: Partial<Parameters<typeof DrawingViewport>[0]> = {}) => {
  const camera = new Camera();
  const backend = new FakeBackend();
  const tools = new ToolController('select');
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
      tools={tools}
      measurements={[COUNT]}
      {...overrides}
    />,
  );
  return { camera, backend, tools, view };
};

/** Центр листа в центре области с дробным сдвигом — округление по дороге было бы видно. */
const centered = (scale: number, shiftX = 0, shiftY = 0) => ({
  scale,
  offsetX: VIEWPORT.width / 2 - 0.5 * SHEET.width * scale + shiftX,
  offsetY: VIEWPORT.height / 2 - 0.5 * SHEET.height * scale + shiftY,
});

describe('память не растёт с масштабом', () => {
  it('слои — размер области, лист — подложка в пределе и резкая часть по области', async () => {
    const { camera, backend } = mount();
    await settle();

    await act(async () => {
      camera.set(centered(2.66));
    });
    await settle();

    // Слои — ровно размер области: память слоя от масштаба не зависит.
    for (const testId of ['regions-layer', 'measurement-layer']) {
      expect(layer(testId).width).toBe(VIEWPORT.width);
      expect(layer(testId).height).toBe(VIEWPORT.height);
    }

    // Резкая часть нарисована в масштабе камеры и не больше области с полями.
    const detail = backend.renders.find((item) => item.region !== null && item.scale === 2.66);
    expect(detail).toBeDefined();

    const [base, sharp] = pageCanvases();
    const limit = fullPageScaleLimit(SHEET, 1);
    expect(base?.width).toBe(Math.floor(SHEET.width * limit));
    expect((base?.width ?? 0) * (base?.height ?? 0)).toBeLessThanOrEqual(FULL_PAGE_MAX_PIXELS);
    expect(sharp?.width).toBeLessThanOrEqual(VIEWPORT.width * 2 + 1);
    expect(sharp?.height).toBeLessThanOrEqual(VIEWPORT.height * 2 + 1);
  });

  it('резкая часть стоит в стопке там же, где этот кусок листа', async () => {
    const { camera } = mount();
    await settle();

    await act(async () => {
      camera.set(centered(2.66, 12.5, -7.25));
    });
    await settle();

    const [, sharp] = pageCanvases();
    if (!sharp) throw new Error('резкой части нет');
    // Стопка разложена в масштабе резкой части и сдвинута ровно на смещение камеры, без
    // растяжения: угол части на экране — угол её прямоугольника листа по формуле камеры.
    const stack = screen.getByTestId('viewport').firstElementChild as HTMLElement;
    const translate = /translate\(([-\d.e]+)px, ([-\d.e]+)px\) scale\(([-\d.e]+)\)/.exec(
      stack.style.transform,
    );
    const target = centered(2.66, 12.5, -7.25);
    expect(Number(translate?.[1])).toBe(target.offsetX);
    expect(Number(translate?.[3])).toBe(1);

    // Левый край части — левый край области минус поле в 400 пикселей, выровненный вниз до
    // целого пикселя растра.
    const screenLeft = target.offsetX + Number.parseFloat(sharp.style.left);
    expect(screenLeft).toBeLessThanOrEqual(-400 + 1e-6);
    expect(screenLeft).toBeGreaterThan(-400 - 1);
  });
});

describe('слои совпадают с листом', () => {
  it('после зума слой измерений перерисован по камере, а не растянут', async () => {
    // Дефект, найденный замером промта 02: после отрисовки страницы в новом масштабе слой
    // измерений оставался в размере вписанного листа до случайной перерисовки React.
    const { camera } = mount();
    await settle();

    const target = centered(2.66, 12.5, -7.25);
    await act(async () => {
      camera.set(target);
    });
    await settle();

    const canvas = layer('measurement-layer');
    const marker = recorded.get(canvas)?.arcs.at(-1);
    // Метка на месте точки (0,5; 0,5) листа при текущей камере — формула, а не растр.
    expect(marker?.x).toBeCloseTo(target.offsetX + 0.5 * SHEET.width * 2.66, 6);
    expect(marker?.y).toBeCloseTo(target.offsetY + 0.5 * SHEET.height * 2.66, 6);
    expect(canvas.style.transform).toBe('');
  });

  it('панорама без новых фигур в кадре двигает слой одним CSS, холст не трогает', async () => {
    const { camera } = mount({ tool: 'pan' });
    await settle();
    await act(async () => {
      camera.set(centered(2));
    });
    await settle();
    const canvas = layer('measurement-layer');
    const before = recorded.get(canvas)?.arcs.at(-1);

    await act(async () => {
      camera.panBy(-150, 120);
    });
    await frame();

    const record = recorded.get(canvas);
    // Открылись правая и верхняя полосы, метка в центре в них не попала: ни копии, ни дорисовки.
    expect(record?.copies).toEqual([]);
    expect(record?.arcs.at(-1)).toEqual(before);
    // Метка на экране — место, где нарисована, плюс CSS-сдвиг холста, — совпадает с формулой.
    expect(canvas.style.transform).toBe('translate(-150px, 120px)');
    expect((before?.x ?? 0) - 150).toBeCloseTo(VIEWPORT.width / 2 - 150, 6);
    expect((before?.y ?? 0) + 120).toBeCloseTo(VIEWPORT.height / 2 + 120, 6);
  });

  it('фигура, вошедшая в кадр, дорисовывается в полосе по формуле камеры', async () => {
    // Вторая метка правее области на 100 пикселей: панорама влево на 150 вводит её в кадр.
    const target = centered(2);
    const entering = {
      ...COUNT,
      id: 'entering',
      points: [
        {
          x: (VIEWPORT.width + 100 - target.offsetX) / (SHEET.width * 2),
          y: 0.5,
        },
      ],
    };
    const { camera } = mount({ tool: 'pan', measurements: [COUNT, entering] });
    await settle();
    await act(async () => {
      camera.set(target);
    });
    await settle();
    const canvas = layer('measurement-layer');

    await act(async () => {
      camera.panBy(-150, 0);
    });
    await frame();

    const record = recorded.get(canvas);
    expect(record?.copies).toEqual([{ x: -150, y: 0 }]);
    // Последняя метка в записи — вошедшая, нарисованная в полосе на своём месте по камере.
    const drawn = record?.arcs.at(-1);
    expect(drawn?.x).toBeCloseTo(VIEWPORT.width + 100 - 150, 6);
    expect(canvas.style.transform).toBe('');
  });

  it('невидимые измерения не рисуются', async () => {
    const far = { ...COUNT, id: 'far', points: [{ x: 0.99, y: 0.99 }] };
    const { camera } = mount({ measurements: [COUNT, far] });
    await settle();

    // Приближение к центру: угол листа далеко за краем области.
    await act(async () => {
      camera.set(centered(4));
    });
    await settle();

    const arcs = recorded.get(layer('measurement-layer'))?.arcs ?? [];
    expect(arcs).toHaveLength(1);
    expect(arcs[0]?.x).toBeCloseTo(VIEWPORT.width / 2, 6);
  });
});

describe('pdf.js на панораме', () => {
  const zoomIn = async () => {
    const mounted = mount({ tool: 'pan' });
    await settle();
    await act(async () => {
      mounted.camera.set(centered(2.66));
    });
    await settle();
    return mounted;
  };

  it('панорама в пределах резкой части не рисует ничего даже после паузы', async () => {
    const { camera, backend } = await zoomIn();
    const rendersBefore = backend.renders.length;

    // Поля — половина области с каждой стороны: 400 × 300 пикселей.
    for (let step = 0; step < 6; step += 1) {
      await act(async () => {
        camera.panBy(-60, 45);
      });
      await frame();
    }
    await settle();

    expect(backend.renders.length).toBe(rendersBefore);
  });

  it('за краем резкой части — ни одной отрисовки во время жеста и ровно одна после', async () => {
    const { camera, backend } = await zoomIn();
    const rendersBefore = backend.renders.length;

    // Жест дальше полей, кадр за кадром быстрее паузы затихания.
    for (let step = 0; step < 12; step += 1) {
      await act(async () => {
        camera.panBy(-60, 0);
      });
      await frame();
    }
    expect(backend.renders.length).toBe(rendersBefore);

    await settle();
    const after = backend.renders.slice(rendersBefore);
    expect(after).toHaveLength(1);
    expect(after[0]?.region).not.toBeNull();
    expect(after[0]?.scale).toBe(2.66);
  });
});

describe('наведение на область', () => {
  const REGION: OverlayRegion = {
    id: 'r1',
    blockType: 'text',
    shapeType: 'rectangle',
    coords: [0, 0, 1, 1],
    polygon: null,
  };

  it('подсвечивает область без единого коммита React', async () => {
    const commits: string[] = [];
    const camera = new Camera();

    render(
      <Profiler id="viewport" onRender={(_id, phase) => commits.push(phase)}>
        <DrawingViewport
          backend={new FakeBackend()}
          sheet={SHEET}
          regions={[REGION]}
          hiddenTypes={new Set()}
          overlayVisible
          selectedId={null}
          onSelect={vi.fn()}
          camera={camera}
          tool="pointer"
        />
      </Profiler>,
    );
    await settle();
    const before = commits.length;

    const viewport = screen.getByTestId('viewport');
    // Первое движение попадает в область, дальше курсор уходит за лист и возвращается.
    for (const clientX of [100, -5000, 100, -5000]) {
      fireEvent.pointerMove(viewport, { clientX, clientY: 100 });
    }
    await settle();

    expect(commits.length - before).toBe(0);
    expect(viewport.dataset.hover).toBeUndefined();

    fireEvent.pointerMove(viewport, { clientX: 100, clientY: 100 });
    expect(viewport.dataset.hover).toBe('region');
  });
});
