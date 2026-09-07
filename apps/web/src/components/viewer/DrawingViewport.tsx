'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { cx } from '@/components/ui';
import type { Camera, CameraState } from '@/lib/viewer/camera';
import { placeRenderedPage, toNormalizedPoint } from '@/lib/viewer/coordinates';
import { drawOverlay, resizeOverlay, type OverlayRegion } from '@/lib/viewer/overlay';
import { DocumentLoadError, RenderCancelledError, type RenderBackend } from '@/lib/viewer/backend';

/**
 * Холст рабочей области: страница документа и слой распознанных областей.
 *
 * Два холста, а не один: страница перерисовывается только при смене листа или масштаба,
 * а слой областей — при наведении и выборе. Совмещать их значило бы перерисовывать
 * пятидесятимегабайтную страницу ради подсветки прямоугольника.
 *
 * Панорамирование и зум идут мимо состояния React: камера хранит трансформацию, а этот
 * компонент подписан на неё и двигает холсты стилями. Через состояние React каждое
 * движение мыши перерисовывало бы обе панели и список областей (ADR-0004).
 */

/**
 * Страница, готовая к отрисовке.
 *
 * Размер — в единицах документа при масштабе 1, то есть ровно то, что вернул отрисовщик.
 * Поворота здесь нет намеренно: pdf.js применяет `/Rotate` сам, и координаты областей
 * записаны в той же конечной системе (см. `placeRenderedPage`).
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
  tool: 'pointer' | 'pan';
  onViewChange?: (state: CameraState) => void;
  onError?: (code: string) => void;
}

/** Цвета областей берутся из токенов темы — хардкод здесь означал бы разъехавшуюся тему. */
const readRegionColors = (): Record<string, string> => {
  if (typeof window === 'undefined') return {};
  const style = getComputedStyle(document.documentElement);

  return {
    text: style.getPropertyValue('--region-text').trim(),
    image: style.getPropertyValue('--region-image').trim(),
    stamp: style.getPropertyValue('--region-stamp').trim(),
  };
};

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
  onViewChange,
  onError,
}: IDrawingViewportProps) => {
  const host = useRef<HTMLDivElement>(null);
  const stack = useRef<HTMLDivElement>(null);
  const pageCanvas = useRef<HTMLCanvasElement>(null);
  const overlayCanvas = useRef<HTMLCanvasElement>(null);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  // Состояние камеры и наведения читается обработчиками кадра, поэтому живёт в ссылках:
  // класть его в состояние React значило бы перерисовывать дерево на каждом кадре.
  const cameraState = useRef<CameraState>(camera.getState());
  const hovered = useRef<string | null>(null);
  const dragging = useRef<{ pointerId: number; x: number; y: number } | null>(null);
  const [spacePressed, setSpacePressed] = useState(false);

  const paintOverlay = useCallback(() => {
    const canvas = overlayCanvas.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context || !sheet) return;

    const ratio = window.devicePixelRatio || 1;
    const { scale } = cameraState.current;
    const placed = placeRenderedPage(sheet, scale, ratio);

    resizeOverlay(canvas, placed.width, placed.height, ratio);
    drawOverlay(
      context,
      placed,
      {
        regions: overlayVisible ? regions : [],
        hiddenTypes,
        selectedId,
        hoveredId: hovered.current,
      },
      { colors: readRegionColors(), fallbackColor: 'currentColor' },
      ratio,
    );
  }, [sheet, regions, hiddenTypes, overlayVisible, selectedId]);

  /** Двигает и масштабирует стопку холстов. Вызывается на каждом кадре камеры. */
  const applyCamera = useCallback(
    (state: CameraState) => {
      cameraState.current = state;
      const element = stack.current;
      if (element) {
        element.style.transform = `translate(${state.offsetX}px, ${state.offsetY}px)`;
      }
      paintOverlay();
      onViewChange?.(state);
    },
    [paintOverlay, onViewChange],
  );

  useEffect(() => {
    applyCamera(camera.getState());
    return camera.subscribe(applyCamera);
  }, [camera, applyCamera]);

  // Отрисовка страницы. Старая задача отменяется при любой смене листа или масштаба:
  // иначе при быстром перелистывании поверх актуальной страницы дорисуется прежняя.
  useEffect(() => {
    if (!backend || !sheet) return;

    const canvas = pageCanvas.current;
    if (!canvas) return;

    const controller = new AbortController();
    setRendering(true);

    void (async () => {
      try {
        await backend.render({
          pageIndex: sheet.pageIndex,
          scale: cameraState.current.scale,
          canvas,
          signal: controller.signal,
        });
        paintOverlay();
      } catch (error) {
        if (error instanceof RenderCancelledError) return;
        if (error instanceof DocumentLoadError) onError?.(error.code);
        else onError?.('PDF_RENDER_FAILED');
      } finally {
        if (!controller.signal.aborted) setRendering(false);
      }
    })();

    return () => controller.abort();
    // Масштаб намеренно не в зависимостях: перерисовка по зуму запускается отдельно,
    // с задержкой, иначе каждый щелчок колеса ставил бы новую задачу отрисовки.
  }, [backend, sheet, paintOverlay, onError]);

  // Перерисовка страницы после того, как зум остановился.
  useEffect(() => {
    if (!backend || !sheet) return;

    let timer: number | undefined;
    let controller: AbortController | null = null;

    const unsubscribe = camera.subscribe(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const canvas = pageCanvas.current;
        if (!canvas) return;

        controller?.abort();
        controller = new AbortController();

        void backend
          .render({
            pageIndex: sheet.pageIndex,
            scale: cameraState.current.scale,
            canvas,
            signal: controller.signal,
          })
          .then(paintOverlay)
          .catch((error: unknown) => {
            if (error instanceof RenderCancelledError) return;
            onError?.(error instanceof DocumentLoadError ? error.code : 'PDF_RENDER_FAILED');
          });
      }, 180);
    });

    return () => {
      window.clearTimeout(timer);
      controller?.abort();
      unsubscribe();
    };
  }, [backend, sheet, camera, paintOverlay, onError]);

  useEffect(() => {
    paintOverlay();
  }, [paintOverlay]);

  // Вписываем лист при его смене и при изменении размера области.
  useEffect(() => {
    const element = host.current;
    if (!element || !sheet) return;

    const fit = () => {
      camera.fitPage(
        { width: sheet.width, height: sheet.height },
        { width: element.clientWidth, height: element.clientHeight },
      );
    };

    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(element);
    return () => observer.disconnect();
  }, [sheet, camera]);

  const pointFromEvent = useCallback(
    (clientX: number, clientY: number) => {
      const element = stack.current;
      if (!element || !sheet) return null;

      const bounds = element.getBoundingClientRect();
      const placed = placeRenderedPage(
        sheet,
        cameraState.current.scale,
        window.devicePixelRatio || 1,
      );

      return toNormalizedPoint({ x: clientX - bounds.left, y: clientY - bounds.top }, placed);
    },
    [sheet],
  );

  const findRegion = useCallback(
    (clientX: number, clientY: number): OverlayRegion | null => {
      if (!overlayVisible) return null;
      const point = pointFromEvent(clientX, clientY);
      if (!point) return null;

      let best: OverlayRegion | null = null;
      let bestArea = Number.POSITIVE_INFINITY;

      for (const region of regions) {
        if (hiddenTypes.has(region.blockType)) continue;

        const [x0, y0, x1, y1] = region.coords;
        if (point.x < Math.min(x0, x1) || point.x > Math.max(x0, x1)) continue;
        if (point.y < Math.min(y0, y1) || point.y > Math.max(y0, y1)) continue;

        // Из перекрывающихся выбираем наименьшую: крупный блок обычно окружает мелкие.
        const area = Math.abs(x1 - x0) * Math.abs(y1 - y0);
        if (area < bestArea) {
          best = region;
          bestArea = area;
        }
      }

      return best;
    },
    [regions, hiddenTypes, overlayVisible, pointFromEvent],
  );

  const panning = tool === 'pan' || spacePressed;

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;

    if (panning) {
      dragging.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }

    onSelect(findRegion(event.clientX, event.clientY)?.id ?? null);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragging.current;
    if (drag && drag.pointerId === event.pointerId) {
      camera.panBy(event.clientX - drag.x, event.clientY - drag.y);
      dragging.current = { ...drag, x: event.clientX, y: event.clientY };
      return;
    }

    if (panning) return;

    const found = findRegion(event.clientX, event.clientY)?.id ?? null;
    if (found !== hovered.current) {
      hovered.current = found;
      setHoveredId(found);
      paintOverlay();
    }
  };

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (dragging.current?.pointerId === event.pointerId) {
      dragging.current = null;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    const element = host.current;
    if (!element) return;

    const bounds = element.getBoundingClientRect();
    camera.zoomAt(
      { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
      event.deltaY < 0 ? 1.12 : 1 / 1.12,
    );
  };

  // Пробел с перетаскиванием — панорама; Esc снимает выбор. Обработчики на документе,
  // потому что фокус может быть на панели, а жест ожидается всё равно.
  useEffect(() => {
    const isTyping = (target: EventTarget | null) =>
      target instanceof HTMLElement &&
      (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable);

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTyping(event.target)) return;

      if (event.code === 'Space') {
        setSpacePressed(true);
        event.preventDefault();
      }
      if (event.key === 'Escape') onSelect(null);
    };
    const onKeyUp = (event: KeyboardEvent) => {
      if (event.code === 'Space') setSpacePressed(false);
    };

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('keyup', onKeyUp);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('keyup', onKeyUp);
    };
  }, [onSelect]);

  return (
    <div
      ref={host}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onWheel={handleWheel}
      data-testid="viewport"
      className={cx(
        'relative h-full w-full overflow-hidden bg-canvas-well',
        panning ? 'cursor-grab' : hoveredId ? 'cursor-pointer' : 'cursor-default',
      )}
    >
      <div ref={stack} className="absolute top-0 left-0 origin-top-left will-change-transform">
        <canvas ref={pageCanvas} className="block bg-canvas shadow-[var(--shadow-sheet)]" />
        <canvas
          ref={overlayCanvas}
          className={cx(
            'pointer-events-none absolute top-0 left-0',
            !overlayVisible && 'opacity-0',
          )}
        />
      </div>

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
