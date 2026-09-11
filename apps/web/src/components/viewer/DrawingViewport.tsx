'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { cx } from '@/components/ui';
import { usePageRaster } from '@/components/viewer/usePageRaster';
import { useViewportInput } from '@/components/viewer/useViewportInput';
import { useViewportLayers } from '@/components/viewer/useViewportLayers';
import type { RenderBackend } from '@/lib/viewer/backend';
import type { Camera, CameraState } from '@/lib/viewer/camera';
import { GestureSettle } from '@/lib/viewer/gesture-settle';
import type { OverlayRegion } from '@/lib/viewer/overlay';
import type { ScaleDraft } from '@/lib/viewer/scale-draft';
import type { OverlayMeasurement } from '@/lib/viewer/measurement-overlay';
import { ShapeIndex } from '@/lib/viewer/shape-index';
import type { ToolController } from '@/lib/viewer/tool-controller';

/** Инструменты, которые понимает холст. Остальные живут выше и сюда не доходят. */
export type ViewportTool = 'pointer' | 'pan' | 'scale';

/**
 * Холст рабочей области: страница документа и слои наложения.
 *
 * Страница — растры pdf.js в стопке, которая двигается CSS-преобразованием: весь лист, пока он
 * укладывается в предел пикселей, выше — подложка и резкая часть по видимой области
 * (`usePageRaster`, ADR-0025). Слои областей, черновика масштаба и измерений — холсты размером
 * с область просмотра поверх стопки; на кадре камеры их пиксели сдвигаются, а дорисовываются
 * только открывшиеся полосы (`useViewportLayers`). До Stage 2B слои лежали в стопке во весь
 * лист: на A1 при 266 % это 64 Мп на каждый, и панорама упиралась в их композитирование.
 *
 * Панорамирование и зум идут мимо состояния React: камера хранит трансформацию, а этот
 * компонент подписан на неё и двигает стопку стилями. Через состояние React каждое движение
 * мыши перерисовывало бы панели и список областей (ADR-0004).
 */

/**
 * Страница, готовая к отрисовке.
 *
 * Размер — в единицах документа при масштабе 1, то есть ровно то, что вернул отрисовщик.
 * Поворота здесь нет намеренно: pdf.js применяет `/Rotate` сам, и координаты областей
 * записаны в той же конечной системе.
 */
export interface ViewportSheet {
  readonly pageIndex: number;
  readonly width: number;
  readonly height: number;
}

interface IDrawingViewportProps {
  backend: RenderBackend | null;
  sheet: ViewportSheet | null;
  regions: readonly OverlayRegion[];
  hiddenTypes: ReadonlySet<string>;
  overlayVisible: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  camera: Camera;
  tool: ViewportTool;
  /**
   * Черновик калибровки. Приходит снаружи, потому что подтверждать его будет рабочая
   * область: холст только рисует и ставит точки.
   */
  scaleDraft?: ScaleDraft | null;
  /** Сохранённые измерения текущего листа. */
  measurements?: readonly OverlayMeasurement[];
  /** Контроллер инструментов обмера. Приходит снаружи: холст рисует и шлёт события. */
  tools?: ToolController | null;
  /** Цвета строк обмера по ключу палитры. */
  measurementColors?: Readonly<Record<string, string>>;
  onViewChange?: (state: CameraState) => void;
  onError?: (code: string) => void;
}

/** Холст слоя перекрывает область просмотра, а не лист; сдвигается от левого верхнего угла. */
const LAYER_CLASS = 'pointer-events-none absolute top-0 left-0 origin-top-left';

/**
 * Пауза после последнего изменения вида, после которой жест считается затихшим: недостающий
 * растр листа рисуется, растянутые зумом слои перерисовываются резкими.
 */
const SETTLE_DELAY_MS = 180;

// Общие пустые значения: новый объект на каждый рендер пересоздавал бы функции отрисовки.
const NO_MEASUREMENTS: readonly OverlayMeasurement[] = [];
const NO_COLORS: Readonly<Record<string, string>> = {};

export const DrawingViewport = ({
  backend,
  sheet,
  regions,
  hiddenTypes,
  overlayVisible,
  selectedId,
  onSelect,
  camera,
  tool,
  scaleDraft = null,
  measurements = NO_MEASUREMENTS,
  tools = null,
  measurementColors = NO_COLORS,
  onViewChange,
  onError,
}: IDrawingViewportProps) => {
  const host = useRef<HTMLDivElement>(null);
  const stack = useRef<HTMLDivElement>(null);
  // Растры страницы живут внутри этого контейнера и меняются целиком после каждой отрисовки,
  // поэтому управляются императивно, а не React: см. `usePageRaster`.
  const pageHost = useRef<HTMLDivElement>(null);
  // Слои — отдельные холсты: `Region` — свидетельство распознавалки, черновик масштаба и
  // измерение — намерение человека, и смешивать их нельзя (ADR-0015).
  const overlayCanvas = useRef<HTMLCanvasElement>(null);
  const scaleCanvas = useRef<HTMLCanvasElement>(null);
  const measurementCanvas = useRef<HTMLCanvasElement>(null);

  // Состояние камеры и наведения читается обработчиками кадра, поэтому живёт в ссылках:
  // класть его в состояние React значило бы перерисовывать дерево на каждом кадре.
  const cameraState = useRef<CameraState>(camera.getState());
  const hovered = useRef<string | null>(null);
  // Пространственный индекс измерений (промт 04). Один на холст: отсечение и попадание
  // синхронизируют его со списком сами, в момент обращения, а не при рендере.
  const [measurementIndex] = useState(() => new ShapeIndex<OverlayMeasurement>());

  // Обработчики родителя приходят стрелками и пересоздаются на каждый рендер. Держим их
  // в ссылках, чтобы подписки на камеру не пересоздавались вместе с ними.
  const viewChanged = useRef(onViewChange);
  const failed = useRef(onError);

  useEffect(() => {
    viewChanged.current = onViewChange;
    failed.current = onError;
  }, [onViewChange, onError]);

  // Лист приходит объектом и пересоздаётся вместе с рендером родителя. Всё, что
  // перезапускает отрисовку, зависит от значений, а не от ссылки: иначе холст обрывал
  // собственную задачу на каждый рендер и не дорисовывал страницу никогда.
  const pageIndex = sheet?.pageIndex ?? null;
  const pageWidth = sheet?.width ?? null;
  const pageHeight = sheet?.height ?? null;

  const page = useMemo(
    () =>
      pageIndex !== null && pageWidth !== null && pageHeight !== null
        ? { pageIndex, width: pageWidth, height: pageHeight }
        : null,
    [pageIndex, pageWidth, pageHeight],
  );

  const reportError = useCallback((code: string) => failed.current?.(code), []);

  const { rendering, placeStack, settleRaster } = usePageRaster({
    backend,
    page,
    cameraRef: cameraState,
    hostRef: host,
    stackRef: stack,
    pageHostRef: pageHost,
    onError: reportError,
  });

  const { followCamera, settleLayers, paintRegions } = useViewportLayers(
    {
      hostRef: host,
      regionsRef: overlayCanvas,
      scaleRef: scaleCanvas,
      measurementsRef: measurementCanvas,
    },
    {
      page,
      cameraRef: cameraState,
      hoveredRef: hovered,
      regions,
      hiddenTypes,
      overlayVisible,
      selectedId,
      scaleDraft,
      tools,
      measurements,
      measurementIndex,
      measurementColors,
    },
  );

  /**
   * Двигает стопку страницы и догоняет камеру слоями. Вызывается на каждом кадре камеры.
   *
   * Слои не едут вместе со стопкой, а считаются по той же камере: так они не отстают от листа
   * ни при панораме, ни после перерисовки страницы в новом масштабе.
   */
  const applyCamera = useCallback(
    (state: CameraState) => {
      cameraState.current = state;
      placeStack(state);
      followCamera(state);
      viewChanged.current?.(state);
    },
    [placeStack, followCamera],
  );

  useEffect(() => {
    applyCamera(camera.getState());
    return camera.subscribe(applyCamera);
  }, [camera, applyCamera]);

  // Жест затих — растянутые зумом слои перерисовываются резкими, а лист получает недостающий
  // растр. Одно определение затихания на оба: слои и лист резкость набирают вместе.
  //
  // Подписка зависит только от камеры и стабильных функций: обработчики, пересоздаваемые на
  // каждый рендер, сбрасывали бы отсчёт раньше, чем жест затихнет.
  useEffect(() => {
    const settle = new GestureSettle(SETTLE_DELAY_MS, () => {
      settleLayers();
      settleRaster();
    });
    const unsubscribe = camera.subscribe(() => settle.change());
    return () => {
      settle.dispose();
      unsubscribe();
    };
  }, [camera, settleLayers, settleRaster]);

  // Вписываем лист при его смене и при изменении размера области. Новый размер области
  // меняет и холсты слоёв — их подгонит кадр камеры, который вызовет вписка.
  useEffect(() => {
    const element = host.current;
    if (!element || !page) return;

    const fit = () => {
      camera.fitPage(
        { width: page.width, height: page.height },
        { width: element.clientWidth, height: element.clientHeight },
      );
    };

    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    return () => observer.disconnect();
  }, [page, camera]);

  const { handlers, panning, measuring } = useViewportInput({
    hostRef: host,
    camera,
    cameraStateRef: cameraState,
    hoveredRef: hovered,
    page,
    regions,
    hiddenTypes,
    overlayVisible,
    measurements,
    measurementIndex,
    tools,
    scaleDraft,
    tool,
    onSelect,
    paintRegions,
  });

  return (
    <div
      ref={host}
      {...handlers}
      data-testid="viewport"
      className={cx(
        'relative h-full w-full overflow-hidden bg-canvas-well',
        panning
          ? 'cursor-grab'
          : measuring
            ? 'cursor-crosshair'
            : 'cursor-default data-[hover=region]:cursor-pointer',
      )}
    >
      <div ref={stack} className="absolute top-0 left-0 origin-top-left will-change-transform">
        <div ref={pageHost} />
      </div>
      <canvas
        ref={overlayCanvas}
        data-testid="regions-layer"
        className={cx(LAYER_CLASS, !overlayVisible && 'opacity-0')}
      />
      <canvas
        ref={scaleCanvas}
        data-testid="scale-layer"
        className={cx(LAYER_CLASS, !measuring && 'hidden')}
      />
      <canvas
        ref={measurementCanvas}
        data-testid="measurement-layer"
        className={cx(LAYER_CLASS, !tools && 'hidden')}
      />

      {rendering && (
        <span
          role="status"
          className="absolute top-[var(--s-4)] right-[var(--s-4)] rounded-[var(--radius-sm)] bg-surface px-[var(--s-4)] py-[var(--s-2)] text-micro text-muted"
        >
          отрисовка…
        </span>
      )}
    </div>
  );
};
