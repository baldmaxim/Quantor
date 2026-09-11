/**
 * Замер просмотрщика в настоящем браузере (Stage 2B, промт 02).
 *
 * Меряется нынешняя архитектура — до переписывания, чтобы решение о слоях и тайлах стояло на
 * числах, а не на ощущении «тормозит». Разделы используют рабочий код портала: тот же
 * pdf.js-отрисовщик, те же функции размещения, тот же слой измерений. Подставной код измерил
 * бы сам себя.
 *
 * Числа снимаются в headless Chromium на программной растеризации — это верхняя оценка.
 */

import type { PageGeometry } from '@/lib/viewer/backend';
import {
  placeRenderedPage,
  type NormalizedPoint,
  type SheetPlacement,
} from '@/lib/viewer/coordinates';
import {
  drawMeasurements,
  hitTestMeasurements,
  type MeasurementOverlayState,
  type OverlayMeasurement,
} from '@/lib/viewer/measurement-overlay';
import { resizeOverlay } from '@/lib/viewer/overlay';
import { PdfJsRenderBackend } from '@/lib/viewer/pdfjs-backend';

import {
  buildMeasurements,
  devicePixelRatio,
  errorText,
  sized,
  stats,
  type CanvasSize,
  type Stats,
  type Viewport,
} from './viewer-fixtures';

export { measurePan } from './viewer-pan';

/* ---------------------------------------------------------------- размеры и память */

export interface SizingRow {
  readonly zoom: number;
  readonly devicePixelRatio: number;
  /** Холст страницы: та же формула, что у pdf.js-отрисовщика. */
  readonly page: CanvasSize;
  /** Слой наложения во весь лист: рабочий `resizeOverlay` на отсоединённом холсте. */
  readonly overlay: CanvasSize;
  /** Стопка как сейчас: страница и три слоя во весь лист. */
  readonly stackRgbaMiB: number;
  /** Слой размером с область просмотра — вариант, который предлагает промт 03. */
  readonly viewportOverlay: CanvasSize;
}

export const measureSizing = async (
  url: string,
  pageIndex: number,
  zooms: readonly number[],
  viewport: Viewport,
): Promise<{ readonly geometry: PageGeometry; readonly rows: SizingRow[] }> => {
  const backend = await PdfJsRenderBackend.open(url);
  try {
    const geometry = await backend.geometry(pageIndex);
    const dpr = devicePixelRatio();

    const rows = zooms.map((zoom): SizingRow => {
      const page = sized(
        Math.max(1, Math.floor(geometry.width * zoom * dpr)),
        Math.max(1, Math.floor(geometry.height * zoom * dpr)),
      );
      const placed = placeRenderedPage(geometry, zoom, dpr);
      const probe = document.createElement('canvas');
      resizeOverlay(probe, placed.width, placed.height, dpr);
      const overlay = sized(probe.width, probe.height);
      resizeOverlay(probe, viewport.width, viewport.height, dpr);
      const viewportOverlay = sized(probe.width, probe.height);
      probe.width = 0;
      probe.height = 0;

      return {
        zoom,
        devicePixelRatio: dpr,
        page,
        overlay,
        stackRgbaMiB: page.rgbaMiB + overlay.rgbaMiB * 3,
        viewportOverlay,
      };
    });

    return { geometry, rows };
  } finally {
    backend.destroy();
  }
};

export interface AllocationAttempt {
  readonly ok: boolean;
  readonly ms: number;
  readonly error: string | null;
}

interface Allocated {
  readonly canvas: HTMLCanvasElement;
  readonly ok: boolean;
  readonly error: string | null;
}

/** Холст считается выделенным, только если в его дальний угол можно записать и прочитать. */
const allocate = (width: number, height: number): Allocated => {
  const canvas = document.createElement('canvas');
  try {
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext('2d');
    if (!context) return { canvas, ok: false, error: 'getContext("2d") вернул null' };
    context.fillStyle = '#ff0000';
    context.fillRect(width - 2, height - 2, 2, 2);
    const pixel = context.getImageData(width - 1, height - 1, 1, 1).data;
    const ok = pixel[0] === 255 && pixel[3] === 255;
    return { canvas, ok, error: ok ? null : `угол прочитан как [${Array.from(pixel).join(',')}]` };
  } catch (error) {
    return { canvas, ok: false, error: errorText(error) };
  }
};

const release = (canvas: HTMLCanvasElement): void => {
  canvas.width = 0;
  canvas.height = 0;
};

export interface AllocationRow {
  readonly zoom: number;
  readonly single: AllocationAttempt;
  readonly stack: AllocationAttempt;
}

export const measureAllocation = (rows: readonly SizingRow[]): AllocationRow[] =>
  rows.map((row) => {
    let started = performance.now();
    const single = allocate(row.page.width, row.page.height);
    const singleMs = performance.now() - started;
    release(single.canvas);

    // Стопка целиком живёт одновременно — именно так её держит DrawingViewport.
    started = performance.now();
    const stack = [
      allocate(row.page.width, row.page.height),
      allocate(row.overlay.width, row.overlay.height),
      allocate(row.overlay.width, row.overlay.height),
      allocate(row.overlay.width, row.overlay.height),
    ];
    const stackMs = performance.now() - started;
    const failed = stack.find((item) => !item.ok);
    for (const item of stack) release(item.canvas);

    return {
      zoom: row.zoom,
      single: { ok: single.ok, ms: singleMs, error: single.error },
      stack: { ok: !failed, ms: stackMs, error: failed?.error ?? null },
    };
  });

/* ---------------------------------------------------------------- отрисовка страницы */

export interface RenderRow {
  readonly zoom: number;
  readonly devicePixelRatio: number;
  readonly canvas: CanvasSize | null;
  readonly ms: number | null;
  readonly error: string | null;
}

export const measurePdfRender = async (
  url: string,
  pageIndex: number,
  zooms: readonly number[],
): Promise<{
  readonly pageCount: number;
  readonly warmupMs: number;
  readonly rows: RenderRow[];
}> => {
  const backend = await PdfJsRenderBackend.open(url);

  const renderAt = async (zoom: number): Promise<RenderRow> => {
    const canvas = document.createElement('canvas');
    const started = performance.now();
    try {
      await backend.render({
        pageIndex,
        scale: zoom,
        canvas,
        signal: new AbortController().signal,
      });
      canvas.getContext('2d')?.getImageData(0, 0, 1, 1);
      return {
        zoom,
        devicePixelRatio: devicePixelRatio(),
        canvas: sized(canvas.width, canvas.height),
        ms: performance.now() - started,
        error: null,
      };
    } catch (error) {
      return {
        zoom,
        devicePixelRatio: devicePixelRatio(),
        canvas: null,
        ms: null,
        error: errorText(error),
      };
    } finally {
      release(canvas);
    }
  };

  try {
    // Прогрев оплачивает запуск рабочего потока и разбор шрифтов — это не цена масштаба.
    const warm = await renderAt(0.25);
    const rows: RenderRow[] = [];
    for (const zoom of zooms) rows.push(await renderAt(zoom));
    return { pageCount: backend.pageCount, warmupMs: warm.ms ?? 0, rows };
  } finally {
    backend.destroy();
  }
};

/* ---------------------------------------------------------------- слой наложения */

const overlayState = (measurements: readonly OverlayMeasurement[]): MeasurementOverlayState => ({
  measurements,
  selectedId: measurements[0]?.id ?? null,
  hoveredId: null,
  draft: [],
  draftType: null,
  draftHover: null,
  dragOverride: null,
});

const STYLE = { colors: { accent: '#1d4ed8', danger: '#b91c1c' }, fallbackColor: '#888888' };

export interface OverlayRow {
  readonly mode: 'viewport' | 'fullPage';
  readonly primitives: number;
  readonly canvas: CanvasSize;
  readonly draw: Stats;
  readonly drawn: number;
}

interface OverlayMode {
  readonly mode: OverlayRow['mode'];
  readonly css: Viewport;
  readonly placement: SheetPlacement;
  readonly frames: number;
}

/**
 * Кадр слоя в двух режимах: холст во весь лист (как сейчас) и холст размером с область
 * просмотра (как предлагает промт 03). Фигуры в обоих случаях рисуются все, без отсечения, —
 * так видна цена именно размера холста; отсечение меряется отдельно, после индекса.
 */
export const measureOverlay = (
  geometry: Viewport,
  sizes: readonly number[],
  zoom: number,
  viewport: Viewport,
  frames: { readonly viewport: number; readonly fullPage: number },
): OverlayRow[] => {
  const dpr = devicePixelRatio();
  const placed = placeRenderedPage(geometry, zoom, dpr);
  const modes: OverlayMode[] = [
    {
      mode: 'viewport',
      css: viewport,
      // Центр листа — в центре области просмотра, как после вписывания и приближения.
      placement: {
        ...placed,
        x: viewport.width / 2 - placed.width / 2,
        y: viewport.height / 2 - placed.height / 2,
      },
      frames: frames.viewport,
    },
    {
      mode: 'fullPage',
      css: { width: placed.width, height: placed.height },
      placement: placed,
      frames: frames.fullPage,
    },
  ];

  const rows: OverlayRow[] = [];
  for (const { mode, css, placement, frames: count } of modes) {
    const canvas = document.createElement('canvas');
    resizeOverlay(canvas, css.width, css.height, dpr);
    const context = canvas.getContext('2d');
    if (!context) throw new Error(`холст ${canvas.width}×${canvas.height} не получил контекст`);

    for (const size of sizes) {
      const state = overlayState(buildMeasurements(size));
      let drawn = drawMeasurements(context, placement, state, STYLE, dpr);
      const samples: number[] = [];
      for (let frame = 0; frame < count; frame += 1) {
        const started = performance.now();
        drawn = drawMeasurements(context, placement, state, STYLE, dpr);
        // Чтение пикселя заставляет браузер закончить растеризацию до возврата.
        context.getImageData(0, 0, 1, 1);
        samples.push(performance.now() - started);
      }
      rows.push({
        mode,
        primitives: size,
        canvas: sized(canvas.width, canvas.height),
        draw: stats(samples),
        drawn,
      });
    }
    release(canvas);
  }

  return rows;
};

export const measureHitTest = (
  geometry: Viewport,
  sizes: readonly number[],
  zoom: number,
  frames: number,
): { readonly primitives: number; readonly hit: Stats }[] => {
  const placement = placeRenderedPage(geometry, zoom, devicePixelRatio());
  const probe: NormalizedPoint = { x: 0.5, y: 0.5 };

  return sizes.map((size) => {
    const measurements = buildMeasurements(size);
    hitTestMeasurements(measurements, probe, placement);
    const samples: number[] = [];
    for (let frame = 0; frame < frames; frame += 1) {
      const started = performance.now();
      hitTestMeasurements(measurements, probe, placement);
      samples.push(performance.now() - started);
    }
    return { primitives: size, hit: stats(samples) };
  });
};
