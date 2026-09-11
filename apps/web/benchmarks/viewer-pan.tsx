/**
 * Панорама настоящего DrawingViewport на крупном увеличении.
 *
 * Сценарий живой приёмки Stage 2A, шаг 14: лист A1 при 266 %, перетаскивание во все стороны.
 * Здесь он повторяется без человека — рабочий компонент, рабочий pdf.js-отрисовщик, камера
 * двигается каждый кадр. Меряется то, что человек называл «лагом»: интервалы кадров, длинные
 * задачи главного потока, лишние перерисовки страницы и рост памяти.
 *
 * После панорамы слои сверяются побитно с перерисовкой целиком: старые фрагменты и сдвиг
 * слоя относительно камеры видны автоматом. То, как это выглядит глазами на настоящем экране
 * с аппаратным ускорением, остаётся живой проверке.
 */

import { createRoot } from 'react-dom/client';

import { DrawingViewport } from '@/components/viewer/DrawingViewport';
import type { PageGeometry, RenderBackend, RenderRequest } from '@/lib/viewer/backend';
import { Camera } from '@/lib/viewer/camera';
import { PdfJsRenderBackend } from '@/lib/viewer/pdfjs-backend';
import { ToolController } from '@/lib/viewer/tool-controller';

import {
  buildMeasurements,
  buildRegions,
  devicePixelRatio,
  errorText,
  sized,
  sleep,
  stats,
  waitFor,
  type CanvasSize,
  type Stats,
} from './viewer-fixtures';

export interface FinishedRender {
  readonly scale: number;
  readonly ms: number;
  /** Оборванная отрисовка: при зуме холст отменяет прежнюю задачу, и её время не в счёт. */
  readonly completed: boolean;
  /** Часть листа (резкая часть) или весь лист (лист в масштабе либо подложка). */
  readonly kind: 'region' | 'page';
  readonly canvas: CanvasSize;
  /** Начало от старта сценария, мс. */
  readonly startedAt: number;
}

/** Считает отрисовки страницы и их длительность, ничего не меняя в работе отрисовщика. */
class CountingBackend implements RenderBackend {
  readonly name: string;
  readonly pageCount: number;
  started = 0;
  inFlight = 0;
  lastActivity = performance.now();
  readonly finished: FinishedRender[] = [];

  constructor(
    private readonly inner: RenderBackend,
    private readonly origin: number,
  ) {
    this.name = `${inner.name} (счётчик)`;
    this.pageCount = inner.pageCount;
  }

  geometry(pageIndex: number): Promise<PageGeometry> {
    return this.inner.geometry(pageIndex);
  }

  async render(request: RenderRequest): Promise<void> {
    this.started += 1;
    this.inFlight += 1;
    this.lastActivity = performance.now();
    const begin = performance.now();
    let completed = false;
    try {
      await this.inner.render(request);
      completed = !request.signal.aborted;
    } finally {
      this.inFlight -= 1;
      this.lastActivity = performance.now();
      this.finished.push({
        scale: request.scale,
        ms: performance.now() - begin,
        completed,
        kind: request.region ? 'region' : 'page',
        canvas: sized(request.canvas.width, request.canvas.height),
        startedAt: begin - this.origin,
      });
    }
  }

  /** Отрисовщик простаивает не меньше `quietMs`: цепочка «резкая часть → подложка» закончилась. */
  idleFor(quietMs: number): boolean {
    return this.inFlight === 0 && performance.now() - this.lastActivity >= quietMs;
  }

  /** Время последней завершённой отрисовки в заданном масштабе либо `null`. */
  completedAt(scale: number): number | null {
    const found = this.finished.filter((item) => item.completed && item.scale === scale);
    return found[found.length - 1]?.ms ?? null;
  }

  destroy(): void {
    this.inner.destroy();
  }
}

export interface PanOptions {
  readonly url: string;
  readonly pageIndex: number;
  readonly zoom: number;
  readonly measurements: number;
  readonly regions: number;
  readonly durationMs: number;
  readonly settleMs: number;
}

export interface LongTasks {
  readonly count: number;
  readonly totalMs: number;
  readonly maxMs: number;
}

export interface PanResult {
  readonly zoom: number;
  readonly devicePixelRatio: number;
  readonly durationMs: number;
  /** Холсты после приближения, до начала панорамы: растры листа и слои. */
  readonly canvases: (CanvasSize & { readonly visible: boolean; readonly role: string })[];
  readonly stackRgbaMiB: number;
  /** Отрисовка в целевом масштабе — та, что случается после каждого зума. */
  readonly zoomRenderMs: number | null;
  /** Все отрисовки от вписки до конца сценария. */
  readonly renders: readonly FinishedRender[];
  readonly frameIntervals: Stats;
  readonly framesPerSecond: number;
  readonly longTasks: LongTasks;
  readonly rendersDuringPan: number;
  readonly rendersAfterPan: number;
  readonly longTasksAfterPan: LongTasks;
  /** Слои после панорамы против перерисовки целиком: пустой — проверка не выполнялась. */
  readonly layerConsistency: readonly LayerConsistency[];
  /** Куча JS раз в секунду. Холсты в неё не входят: их память живёт вне кучи. */
  readonly heapUsedMiB: readonly number[];
  /** Границы фаз от начала сценария, мс: по ним память процессов делится на фазы. */
  readonly phases: {
    readonly zoomRendered: number | null;
    readonly panStarted: number | null;
    readonly panEnded: number | null;
  };
  readonly error: string | null;
}

interface MemoryInfo {
  readonly usedJSHeapSize: number;
}

const heapMiB = (): number | null => {
  const info = (performance as Performance & { memory?: MemoryInfo }).memory;
  return info ? info.usedJSHeapSize / (1024 * 1024) : null;
};

const summariseLongTasks = (entries: readonly PerformanceEntry[]): LongTasks => ({
  count: entries.length,
  totalMs: entries.reduce((total, entry) => total + entry.duration, 0),
  maxMs: entries.reduce((max, entry) => Math.max(max, entry.duration), 0),
});

const collectLongTasks = (): {
  readonly entries: PerformanceEntry[];
  readonly stop: () => void;
} => {
  const entries: PerformanceEntry[] = [];
  if (!PerformanceObserver.supportedEntryTypes.includes('longtask')) {
    return { entries, stop: () => undefined };
  }
  const observer = new PerformanceObserver((list) => entries.push(...list.getEntries()));
  observer.observe({ type: 'longtask' });
  return { entries, stop: () => observer.disconnect() };
};

const canvasesOf = (
  host: HTMLElement,
): (CanvasSize & { readonly visible: boolean; readonly role: string })[] =>
  Array.from(host.querySelectorAll('canvas')).map((canvas, index) => ({
    ...sized(canvas.width, canvas.height),
    visible: getComputedStyle(canvas).display !== 'none',
    // Слои помечены атрибутом; растры листа — нет, и первый из них всегда весь лист.
    role: canvas.dataset.testid ?? (index === 0 ? 'лист' : 'резкая часть'),
  }));

interface PixelDiff {
  /** Пикселей, где хоть один канал разошёлся больше чем на 2 из 255. */
  readonly differing: number;
  /** Пикселей, где расхождение заметно глазом — больше 64 из 255. */
  readonly visible: number;
  readonly maxChannelDiff: number;
}

/**
 * Попиксельное расхождение двух снимков; `b` сдвинут на (`dx`, `dy`): пиксель (x, y) снимка `a`
 * сравнивается с (x − dx, y − dy) снимка `b`. Края, куда сдвиг заводит за снимок, не считаются.
 */
const pixelDiff = (a: ImageData, b: ImageData, dx = 0, dy = 0): PixelDiff => {
  let differing = 0;
  let visible = 0;
  let maxChannelDiff = 0;
  const { width, height } = a;
  for (let y = Math.max(0, dy); y < Math.min(height, height + dy); y += 1) {
    for (let x = Math.max(0, dx); x < Math.min(width, width + dx); x += 1) {
      const i = (y * width + x) * 4;
      const j = ((y - dy) * width + (x - dx)) * 4;
      let diff = 0;
      for (let channel = 0; channel < 4; channel += 1) {
        const value = Math.abs((a.data[i + channel] ?? 0) - (b.data[j + channel] ?? 0));
        if (value > diff) diff = value;
      }
      if (diff > 2) differing += 1;
      if (diff > 64) visible += 1;
      if (diff > maxChannelDiff) maxChannelDiff = diff;
    }
  }
  return { differing, visible, maxChannelDiff };
};

/**
 * Слой после панорамы против того же слоя, нарисованного целиком при той же камере.
 *
 * Панорама сдвигает пиксели и дорисовывает полосы. Старый фрагмент, шов на границе полосы или
 * накопившийся сдвиг разойдутся с отрисовкой целиком — это то, что человек увидел бы как «хвосты»
 * и оторвавшиеся фигуры. Нуля ждать нельзя: Skia растеризует штрих в разных местах холста не бит
 * в бит, поэтому рядом — порог шума (один сдвиг) и проба сдвига на пиксель: при верном
 * выравнивании расхождение с перерисовкой на уровне шума и много меньше, чем со сдвигом.
 */
export interface LayerConsistency {
  readonly layer: string;
  readonly pixels: number;
  /** Непрозрачных пикселей после панорамы: сравнение пустых слоёв ничего не доказывает. */
  readonly inked: number;
  readonly afterPan: PixelDiff;
  /** Один сдвиг на целое число пикселей — порог шума растеризации. */
  readonly singleShift: PixelDiff;
  /** Перерисовка, сдвинутая на пиксель вправо: так выглядело бы расхождение на пиксель. */
  readonly offByOnePixel: PixelDiff;
}

const LAYER_IDS = ['regions-layer', 'measurement-layer'] as const;

const snapshotLayers = (host: HTMLElement): Map<string, ImageData> => {
  const shots = new Map<string, ImageData>();
  for (const id of LAYER_IDS) {
    const canvas = host.querySelector<HTMLCanvasElement>(`[data-testid="${id}"]`);
    const context = canvas?.getContext('2d');
    if (canvas && context) shots.set(id, context.getImageData(0, 0, canvas.width, canvas.height));
  }
  return shots;
};

const compareLayers = (
  afterPan: ReadonlyMap<string, ImageData>,
  whole: ReadonlyMap<string, ImageData>,
  singleShift: ReadonlyMap<string, ImageData>,
): LayerConsistency[] =>
  LAYER_IDS.flatMap((layer) => {
    const panned = afterPan.get(layer);
    const reference = whole.get(layer);
    const shifted = singleShift.get(layer);
    if (!panned || !reference || !shifted) return [];
    let inked = 0;
    for (let index = 3; index < panned.data.length; index += 4) {
      if ((panned.data[index] ?? 0) > 0) inked += 1;
    }
    return [
      {
        layer,
        pixels: panned.width * panned.height,
        inked,
        afterPan: pixelDiff(panned, reference),
        singleShift: pixelDiff(shifted, reference),
        offByOnePixel: pixelDiff(panned, reference, 1, 0),
      },
    ];
  });

const nextFrame = (): Promise<void> =>
  new Promise((resolve) => requestAnimationFrame(() => resolve()));

/**
 * Доводит камеру до целого числа физических пикселей от того положения, в котором нарисованы
 * пиксели слоёв.
 *
 * Слой после сдвига держит дробный остаток CSS-сдвигом холста: `translate(камера − нарисованное)`.
 * По нему видно, при какой камере лежат пиксели, — не зная внутреннего состояния слоя. После
 * доводки остаток нулевой, и перерисовка целиком при этой камере сравнима с пикселями побитно.
 */
const snapLayersToPixels = async (
  host: HTMLElement,
  camera: Camera,
  ratio: number,
): Promise<void> => {
  const canvas = host.querySelector<HTMLCanvasElement>(`[data-testid="${LAYER_IDS[0]}"]`);
  const match = /translate\(([-\d.e]+)px, ([-\d.e]+)px\)/.exec(canvas?.style.transform ?? '');
  const residualX = match ? Number(match[1]) : 0;
  const residualY = match ? Number(match[2]) : 0;
  const state = camera.getState();
  const paintedX = state.offsetX - residualX;
  const paintedY = state.offsetY - residualY;
  camera.set({
    scale: state.scale,
    offsetX: paintedX + Math.round((state.offsetX - paintedX) * ratio) / ratio,
    offsetY: paintedY + Math.round((state.offsetY - paintedY) * ratio) / ratio,
  });
  await nextFrame();
  await nextFrame();
};

export const measurePan = async (options: PanOptions): Promise<PanResult> => {
  const host = document.querySelector<HTMLDivElement>('#viewport-host');
  if (!host) throw new Error('на странице замера нет #viewport-host');

  const origin = performance.now();
  const phases: {
    zoomRendered: number | null;
    panStarted: number | null;
    panEnded: number | null;
  } = { zoomRendered: null, panStarted: null, panEnded: null };
  const backend = new CountingBackend(await PdfJsRenderBackend.open(options.url), origin);
  const geometry = await backend.geometry(options.pageIndex);
  const camera = new Camera();
  const tools = new ToolController('select');
  const root = createRoot(host);
  const empty: ReadonlySet<string> = new Set();
  const sheet = { pageIndex: options.pageIndex, width: geometry.width, height: geometry.height };
  const reported: { code: string | null } = { code: null };

  /** Рабочий компонент с данными сценария. Новые массивы с теми же фигурами — полная перерисовка. */
  const mount = (
    regions: ReturnType<typeof buildRegions>,
    measurements: ReturnType<typeof buildMeasurements>,
  ) =>
    root.render(
      <DrawingViewport
        backend={backend}
        sheet={sheet}
        regions={regions}
        hiddenTypes={empty}
        overlayVisible
        selectedId={null}
        onSelect={() => undefined}
        camera={camera}
        tool="pointer"
        measurements={measurements}
        tools={tools}
        onError={(code) => {
          reported.code = code;
        }}
      />,
    );

  const failure = (error: string): PanResult => ({
    zoom: options.zoom,
    devicePixelRatio: devicePixelRatio(),
    durationMs: options.durationMs,
    canvases: canvasesOf(host),
    stackRgbaMiB: 0,
    zoomRenderMs: null,
    renders: backend.finished,
    frameIntervals: stats([]),
    framesPerSecond: 0,
    longTasks: summariseLongTasks([]),
    rendersDuringPan: 0,
    rendersAfterPan: 0,
    longTasksAfterPan: summariseLongTasks([]),
    layerConsistency: [],
    heapUsedMiB: [],
    phases,
    error,
  });

  try {
    const regions = buildRegions(options.regions);
    const measurements = buildMeasurements(options.measurements);
    mount(regions, measurements);

    // Первая отрисовка — вписанный лист.
    if (!(await waitFor(() => backend.finished.some((item) => item.completed), 120_000))) {
      return failure('первая отрисовка листа не завершилась за 120 с');
    }

    // Приближение: центр листа в центре области, как после щелчков зума.
    const zoomCamera = {
      scale: options.zoom,
      offsetX: host.clientWidth / 2 - (geometry.width * options.zoom) / 2,
      offsetY: host.clientHeight / 2 - (geometry.height * options.zoom) / 2,
    };
    camera.set(zoomCamera);
    // Ждём завершённую отрисовку в целевом масштабе, а затем тишину отрисовщика: выше предела
    // пикселей за резкой частью идёт подложка, и холсты снимаются после обеих.
    if (!(await waitFor(() => backend.completedAt(options.zoom) !== null, 300_000))) {
      return failure(`отрисовка при ${Math.round(options.zoom * 100)} % не завершилась за 300 с`);
    }
    const zoomRenderMs = backend.completedAt(options.zoom);
    if (!(await waitFor(() => backend.idleFor(600), 300_000))) {
      return failure('отрисовщик не затих за 300 с после зума');
    }
    phases.zoomRendered = performance.now() - origin;
    await sleep(options.settleMs);
    if (reported.code) return failure(`отрисовщик сообщил ошибку ${reported.code}`);

    const canvases = canvasesOf(host);
    const stackRgbaMiB = canvases.reduce((total, canvas) => total + canvas.rgbaMiB, 0);

    const longTasks = collectLongTasks();
    const heap: number[] = [];
    const heapTimer = window.setInterval(() => {
      const value = heapMiB();
      if (value !== null) heap.push(value);
    }, 1000);

    const rendersBefore = backend.started;
    const intervals: number[] = [];
    // Амплитуда в пределах листа: панорама за край мерила бы пустой фон.
    const amplitudeX = Math.max(0, (geometry.width * options.zoom - host.clientWidth) / 2 - 50);
    const amplitudeY = Math.max(0, (geometry.height * options.zoom - host.clientHeight) / 2 - 50);

    phases.panStarted = performance.now() - origin;
    await new Promise<void>((resolve) => {
      const start = performance.now();
      let last = start;
      let previousX = 0;
      let previousY = 0;

      const tick = (now: number) => {
        intervals.push(now - last);
        last = now;
        const seconds = (now - start) / 1000;
        // Фигура Лиссажу: лист уходит во все стороны и с разной скоростью.
        const x = Math.sin(seconds * 0.9) * amplitudeX;
        const y = Math.sin(seconds * 1.3 + 0.7) * amplitudeY;
        camera.panBy(x - previousX, y - previousY);
        previousX = x;
        previousY = y;
        if (now - start < options.durationMs) requestAnimationFrame(tick);
        else resolve();
      };
      requestAnimationFrame(tick);
    });

    phases.panEnded = performance.now() - origin;
    const rendersDuringPan = backend.started - rendersBefore;
    const panLongTasks = summariseLongTasks(longTasks.entries);
    const afterStart = longTasks.entries.length;
    await sleep(options.settleMs);
    const rendersAfterPan = backend.started - rendersBefore - rendersDuringPan;
    const longTasksAfterPan = summariseLongTasks(longTasks.entries.slice(afterStart));
    window.clearInterval(heapTimer);
    longTasks.stop();

    // Слои после панорамы против перерисовки целиком при той же камере.
    const ratio = devicePixelRatio();
    const repaintWhole = async () => {
      // Холсты стираются перед перерисовкой: не случись она, сравнение покажет пустоту, а не
      // ложное совпадение.
      for (const id of LAYER_IDS) {
        const canvas = host.querySelector<HTMLCanvasElement>(`[data-testid="${id}"]`);
        canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
      }
      mount([...regions], [...measurements]);
      // Коммит React и эффекты перерисовки — не в том же кадре, что render().
      await sleep(200);
      await nextFrame();
    };

    await snapLayersToPixels(host, camera, ratio);
    const afterPan = snapshotLayers(host);
    await repaintWhole();
    const whole = snapshotLayers(host);

    // Порог шума: тот же слой, нарисованный целиком со сдвигом на целое число пикселей и один
    // раз сдвинутый обратно. Skia растеризует штрих в разных местах холста не бит в бит, и
    // расхождения после панорамы честно сравнивать с этим уровнем, а не с нулём.
    const base = camera.getState();
    camera.set({ ...base, offsetX: base.offsetX - 37 / ratio, offsetY: base.offsetY - 23 / ratio });
    await nextFrame();
    await nextFrame();
    await repaintWhole();
    camera.set(base);
    await nextFrame();
    await nextFrame();
    const singleShift = snapshotLayers(host);

    const layerConsistency = compareLayers(afterPan, whole, singleShift);

    // Первый интервал — ожидание первого кадра, а не кадр панорамы.
    const frameIntervals = stats(intervals.slice(1));

    return {
      zoom: options.zoom,
      devicePixelRatio: ratio,
      durationMs: options.durationMs,
      canvases,
      stackRgbaMiB,
      zoomRenderMs,
      renders: backend.finished,
      frameIntervals,
      framesPerSecond: frameIntervals.mean ? 1000 / frameIntervals.mean : 0,
      longTasks: panLongTasks,
      rendersDuringPan,
      rendersAfterPan,
      longTasksAfterPan,
      layerConsistency,
      heapUsedMiB: heap,
      phases,
      error: null,
    };
  } catch (error) {
    return failure(errorText(error));
  } finally {
    root.unmount();
    backend.destroy();
    tools.dispose();
    camera.dispose();
  }
};
