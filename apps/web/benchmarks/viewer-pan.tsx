/**
 * Панорама настоящего DrawingViewport на крупном увеличении.
 *
 * Сценарий живой приёмки Stage 2A, шаг 14: лист A1 при 266 %, перетаскивание во все стороны.
 * Здесь он повторяется без человека — рабочий компонент, рабочий pdf.js-отрисовщик, камера
 * двигается каждый кадр. Меряется то, что человек называл «лагом»: интервалы кадров, длинные
 * задачи главного потока, лишние перерисовки страницы и рост памяти.
 *
 * Белые вспышки и оторвавшиеся слои автоматом не видны — это остаётся живой проверке.
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

interface FinishedRender {
  readonly scale: number;
  readonly ms: number;
  /** Оборванная отрисовка: при зуме холст отменяет прежнюю задачу, и её время не в счёт. */
  readonly completed: boolean;
}

/** Считает отрисовки страницы и их длительность, ничего не меняя в работе отрисовщика. */
class CountingBackend implements RenderBackend {
  readonly name: string;
  readonly pageCount: number;
  started = 0;
  readonly finished: FinishedRender[] = [];

  constructor(private readonly inner: RenderBackend) {
    this.name = `${inner.name} (счётчик)`;
    this.pageCount = inner.pageCount;
  }

  geometry(pageIndex: number): Promise<PageGeometry> {
    return this.inner.geometry(pageIndex);
  }

  async render(request: RenderRequest): Promise<void> {
    this.started += 1;
    const begin = performance.now();
    let completed = false;
    try {
      await this.inner.render(request);
      completed = !request.signal.aborted;
    } finally {
      this.finished.push({ scale: request.scale, ms: performance.now() - begin, completed });
    }
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
  /** Холсты стопки после приближения, до начала панорамы. */
  readonly canvases: (CanvasSize & { readonly visible: boolean })[];
  readonly stackRgbaMiB: number;
  /** Отрисовка страницы в целевом масштабе — та, что случается после каждого зума. */
  readonly zoomRenderMs: number | null;
  readonly frameIntervals: Stats;
  readonly framesPerSecond: number;
  readonly longTasks: LongTasks;
  readonly rendersDuringPan: number;
  readonly rendersAfterPan: number;
  readonly longTasksAfterPan: LongTasks;
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

const canvasesOf = (host: HTMLElement): (CanvasSize & { readonly visible: boolean })[] =>
  Array.from(host.querySelectorAll('canvas')).map((canvas) => ({
    ...sized(canvas.width, canvas.height),
    visible: getComputedStyle(canvas).display !== 'none',
  }));

export const measurePan = async (options: PanOptions): Promise<PanResult> => {
  const host = document.querySelector<HTMLDivElement>('#viewport-host');
  if (!host) throw new Error('на странице замера нет #viewport-host');

  const origin = performance.now();
  const phases: {
    zoomRendered: number | null;
    panStarted: number | null;
    panEnded: number | null;
  } = { zoomRendered: null, panStarted: null, panEnded: null };
  const backend = new CountingBackend(await PdfJsRenderBackend.open(options.url));
  const geometry = await backend.geometry(options.pageIndex);
  const camera = new Camera();
  const tools = new ToolController('select');
  const root = createRoot(host);
  const empty: ReadonlySet<string> = new Set();

  const failure = (error: string): PanResult => ({
    zoom: options.zoom,
    devicePixelRatio: devicePixelRatio(),
    durationMs: options.durationMs,
    canvases: canvasesOf(host),
    stackRgbaMiB: 0,
    zoomRenderMs: null,
    frameIntervals: stats([]),
    framesPerSecond: 0,
    longTasks: summariseLongTasks([]),
    rendersDuringPan: 0,
    rendersAfterPan: 0,
    longTasksAfterPan: summariseLongTasks([]),
    heapUsedMiB: [],
    phases,
    error,
  });

  try {
    const reported: { code: string | null } = { code: null };
    root.render(
      <DrawingViewport
        backend={backend}
        sheet={{ pageIndex: options.pageIndex, width: geometry.width, height: geometry.height }}
        regions={buildRegions(options.regions)}
        hiddenTypes={empty}
        overlayVisible
        selectedId={null}
        onSelect={() => undefined}
        camera={camera}
        tool="pointer"
        measurements={buildMeasurements(options.measurements)}
        tools={tools}
        onError={(code) => {
          reported.code = code;
        }}
      />,
    );

    // Первая отрисовка — вписанный лист.
    if (!(await waitFor(() => backend.finished.some((item) => item.completed), 120_000))) {
      return failure('первая отрисовка листа не завершилась за 120 с');
    }

    // Приближение: центр листа в центре области, как после щелчков зума.
    camera.set({
      scale: options.zoom,
      offsetX: host.clientWidth / 2 - (geometry.width * options.zoom) / 2,
      offsetY: host.clientHeight / 2 - (geometry.height * options.zoom) / 2,
    });
    // Ждём именно завершённую отрисовку в целевом масштабе: оборванная вписка тоже
    // «заканчивается», и по ней холсты снимались бы до перерисовки.
    if (!(await waitFor(() => backend.completedAt(options.zoom) !== null, 300_000))) {
      return failure(`отрисовка при ${Math.round(options.zoom * 100)} % не завершилась за 300 с`);
    }
    const zoomRenderMs = backend.completedAt(options.zoom);
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
    window.clearInterval(heapTimer);
    longTasks.stop();

    // Первый интервал — ожидание первого кадра, а не кадр панорамы.
    const frameIntervals = stats(intervals.slice(1));

    return {
      zoom: options.zoom,
      devicePixelRatio: devicePixelRatio(),
      durationMs: options.durationMs,
      canvases,
      stackRgbaMiB,
      zoomRenderMs,
      frameIntervals,
      framesPerSecond: frameIntervals.mean ? 1000 / frameIntervals.mean : 0,
      longTasks: panLongTasks,
      rendersDuringPan,
      rendersAfterPan: backend.started - rendersBefore - rendersDuringPan,
      longTasksAfterPan: summariseLongTasks(longTasks.entries.slice(afterStart)),
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
