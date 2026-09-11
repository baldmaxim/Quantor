/**
 * Замер просмотрщика в настоящем браузере (Stage 2B, промты 02–03).
 *
 * Промт 02 снял архитектуру до переписывания, промт 03 — после: решение о слоях и растре по
 * видимой части стоит на числах, а не на ощущении «тормозит» (ADR-0024, ADR-0025). Разделы
 * используют рабочий код портала: тот же pdf.js-отрисовщик, те же функции размещения, тот же
 * слой измерений. Подставной код измерил бы сам себя.
 *
 * Разделы «Холсты и память» и «Слой измерений» моделируют прежнюю стопку во весь лист — это
 * точка отсчёта. Панорама и сверка растров меряют рабочий компонент как есть.
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
import { surfaceRegionFor } from '@/lib/viewer/surface';

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

/* ---------------------------------------------------------------- резкая часть против листа */

interface RasterDiff {
  /** Пикселей, где хоть один канал разошёлся больше чем на 2 из 255. */
  readonly differing: number;
  /** Пикселей, где расхождение заметно глазом — больше 64 из 255. */
  readonly visible: number;
  readonly maxChannelDiff: number;
}

export interface RasterConsistency {
  readonly zoom: number;
  readonly devicePixelRatio: number;
  readonly page: CanvasSize;
  readonly region: CanvasSize;
  /** Угол резкой части в физических пикселях растра листа. */
  readonly offset: { readonly x: number; readonly y: number };
  /** Часть против того же куска листа. */
  readonly aligned: RasterDiff;
  /** Часть против куска листа, сдвинутого на пиксель вправо: так выглядел бы шов. */
  readonly offByOnePixel: RasterDiff;
  readonly pageMs: number;
  readonly regionMs: number;
}

/**
 * Резкая часть, нарисованная отрисовщиком, против того же куска растра во весь лист.
 *
 * Если прямоугольник части и сдвиг pdf.js разошлись хоть на пиксель, часть ляжет на подложку со
 * швом или сдвигом — ровно «оторвавшийся фрагмент» живой проверки. Нуля ждать нельзя: Skia
 * растеризует тонкий штрих в разных местах холста не бит в бит. Поэтому рядом — проба сдвига на
 * пиксель: при верном выравнивании расхождение много меньше, чем со сдвигом.
 */
export const measureRasterConsistency = async (
  url: string,
  pageIndex: number,
  zoom: number,
  viewport: Viewport,
): Promise<RasterConsistency> => {
  const backend = await PdfJsRenderBackend.open(url);
  const full = document.createElement('canvas');
  const part = document.createElement('canvas');
  try {
    const geometry = await backend.geometry(pageIndex);
    const dpr = devicePixelRatio();
    // Дробный сдвиг от центра: выравнивание по пикселям обязано справиться и с ним.
    const camera = {
      scale: zoom,
      offsetX: viewport.width / 2 - (geometry.width * zoom) / 2 + 123.4,
      offsetY: viewport.height / 2 - (geometry.height * zoom) / 2 - 56.7,
    };
    const region = surfaceRegionFor(geometry, camera, viewport, dpr);
    if (!region) throw new Error('резкая часть не построена');

    const signal = new AbortController().signal;
    let started = performance.now();
    await backend.render({ pageIndex, scale: zoom, canvas: full, signal, pixelRatio: dpr });
    const pageMs = performance.now() - started;
    started = performance.now();
    await backend.render({ pageIndex, scale: zoom, canvas: part, signal, pixelRatio: dpr, region });
    const regionMs = performance.now() - started;

    const x = Math.round(region.x * zoom * dpr);
    const y = Math.round(region.y * zoom * dpr);
    const fullContext = full.getContext('2d');
    const actual = part.getContext('2d')?.getImageData(0, 0, part.width, part.height);
    const expected = fullContext?.getImageData(x, y, part.width, part.height);
    // Кусок листа на пиксель левее: пиксель (i, j) части сравнивается с (i − 1, j) листа.
    const shifted = fullContext?.getImageData(x - 1, y, part.width, part.height);
    if (!expected || !actual || !shifted) throw new Error('пиксели растров не прочитаны');

    const compare = (reference: ImageData): RasterDiff => {
      let differing = 0;
      let visible = 0;
      let maxChannelDiff = 0;
      for (let index = 0; index < actual.data.length; index += 4) {
        let pixelDiff = 0;
        for (let channel = 0; channel < 4; channel += 1) {
          const diff = Math.abs(
            (actual.data[index + channel] ?? 0) - (reference.data[index + channel] ?? 0),
          );
          if (diff > pixelDiff) pixelDiff = diff;
        }
        if (pixelDiff > 2) differing += 1;
        if (pixelDiff > 64) visible += 1;
        if (pixelDiff > maxChannelDiff) maxChannelDiff = pixelDiff;
      }
      return { differing, visible, maxChannelDiff };
    };

    return {
      zoom,
      devicePixelRatio: dpr,
      page: sized(full.width, full.height),
      region: sized(part.width, part.height),
      offset: { x, y },
      aligned: compare(expected),
      offByOnePixel: compare(shifted),
      pageMs,
      regionMs,
    };
  } finally {
    release(full);
    release(part);
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
