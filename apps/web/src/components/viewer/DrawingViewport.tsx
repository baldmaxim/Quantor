'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { cx } from '@/components/ui';
import type { Camera, CameraState } from '@/lib/viewer/camera';
import { placeRenderedPage, toNormalizedPoint } from '@/lib/viewer/coordinates';
import { drawOverlay, resizeOverlay, type OverlayRegion } from '@/lib/viewer/overlay';
import { DocumentLoadError, RenderCancelledError, type RenderBackend } from '@/lib/viewer/backend';
import type { ScaleDraft } from '@/lib/viewer/scale-draft';
import { drawScaleDraft } from '@/lib/viewer/scale-overlay';
import {
  drawMeasurements,
  hitTestMeasurements,
  hitTestVertex,
  type OverlayMeasurement,
} from '@/lib/viewer/measurement-overlay';
import type { ToolController } from '@/lib/viewer/tool-controller';
import { DRAWING_MODES } from '@/lib/viewer/tool-machine';

/** Инструменты, которые понимает холст. Остальные живут выше и сюда не доходят. */
export type ViewportTool = 'pointer' | 'pan' | 'scale';

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

/** Пауза после последнего изменения вида, после которой страница рисуется заново. */
const RERENDER_DELAY_MS = 180;

/** Шаг зума на щелчок колеса. Множитель, а не слагаемое: на мелком масштабе шаг иначе огромен. */
const ZOOM_WHEEL_STEP = 1.12;

/** Задержка перед показом значка отрисовки: быстрые листы не должны им мигать. */
const BADGE_DELAY_MS = 120;

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

/**
 * Чернила обмера.
 *
 * Отдельные токены, а не `--accent`: тот в тёмной теме светлеет, а бумага листа остаётся
 * светлой в обеих. Светлый штрих по светлой бумаге не виден — на этом уже спотыкались.
 */
const readSheetInk = (): Record<string, string> => {
  if (typeof window === 'undefined') return {};
  const style = getComputedStyle(document.documentElement);

  return {
    accent: style.getPropertyValue('--sheet-ink').trim(),
    danger: style.getPropertyValue('--sheet-ink-danger').trim(),
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
  scaleDraft = null,
  measurements = [],
  tools = null,
  measurementColors = {},
  onViewChange,
  onError,
}: IDrawingViewportProps) => {
  const host = useRef<HTMLDivElement>(null);
  const stack = useRef<HTMLDivElement>(null);
  const pageCanvas = useRef<HTMLCanvasElement>(null);
  const overlayCanvas = useRef<HTMLCanvasElement>(null);
  // Третий холст: черновик калибровки не смешивается со слоем распознанных областей.
  // `Region` — свидетельство, черновик — намерение (ADR-0015).
  const scaleCanvas = useRef<HTMLCanvasElement>(null);
  // Четвёртый холст: измерения не смешиваются ни со слоем областей, ни с черновиком
  // масштаба. Каждый слой — своя ответственность (ADR-0015).
  const measurementCanvas = useRef<HTMLCanvasElement>(null);

  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  // Состояние камеры и наведения читается обработчиками кадра, поэтому живёт в ссылках:
  // класть его в состояние React значило бы перерисовывать дерево на каждом кадре.
  const cameraState = useRef<CameraState>(camera.getState());
  const hovered = useRef<string | null>(null);
  const dragging = useRef<{ pointerId: number; x: number; y: number } | null>(null);
  const [spacePressed, setSpacePressed] = useState(false);

  // Масштаб, в котором сейчас лежат пиксели холста страницы.
  //
  // Пока идёт жест, стопка растягивается стилями от этого значения — зум мгновенный,
  // без единой перерисовки PDF. Когда жест затих, страница перерисовывается в новом
  // масштабе, и коэффициент растяжения снова становится единичным.
  const renderedScale = useRef(1);

  // Одна активная отрисовка: первая вписка листа и перерисовка после зума иначе
  // бегут параллельно с разными AbortController и оба зовут pdf.js render() на одном
  // canvas — в pdf.js 6 это падает в PDF_RENDER_FAILED.
  const renderController = useRef<AbortController | null>(null);

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

  const paintOverlay = useCallback(() => {
    const canvas = overlayCanvas.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context || !page) return;

    const ratio = window.devicePixelRatio || 1;
    // Слой рисуется в том же масштабе, что и страница: у них общий родитель, и одно
    // преобразование двигает обоих — разъехаться они не могут по построению.
    const placed = placeRenderedPage(page, renderedScale.current, ratio);

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
  }, [page, regions, hiddenTypes, overlayVisible, selectedId]);

  /** Двигает и масштабирует стопку холстов. Вызывается на каждом кадре камеры. */
  const applyCamera = useCallback((state: CameraState) => {
    cameraState.current = state;

    const element = stack.current;
    if (element) {
      const zoom = state.scale / renderedScale.current;
      element.style.transform = `translate(${state.offsetX}px, ${state.offsetY}px) scale(${zoom})`;
    }

    viewChanged.current?.(state);
  }, []);

  useEffect(() => {
    applyCamera(camera.getState());
    return camera.subscribe(applyCamera);
  }, [camera, applyCamera]);

  const reportFailure = useCallback((error: unknown) => {
    if (error instanceof RenderCancelledError) return;
    failed.current?.(error instanceof DocumentLoadError ? error.code : 'PDF_RENDER_FAILED');
  }, []);

  /** Рисует страницу в текущем масштабе камеры и снимает растяжение стопки. */
  const renderPage = useCallback(
    async (signal: AbortSignal) => {
      const canvas = pageCanvas.current;
      if (!backend || !page || !canvas) return;

      const scale = cameraState.current.scale;
      await backend.render({ pageIndex: page.pageIndex, scale, canvas, signal });
      if (signal.aborted) return;

      renderedScale.current = scale;
      applyCamera(cameraState.current);
      paintOverlay();
    },
    [backend, page, applyCamera, paintOverlay],
  );

  const render = useRef(renderPage);
  useEffect(() => {
    render.current = renderPage;
  }, [renderPage]);

  /** Запускает отрисовку, отменяя прежнюю незавершённую на этом холсте. */
  const startRender = useCallback(
    (options?: { readonly showBadge?: boolean }) => {
      renderController.current?.abort();
      const controller = new AbortController();
      renderController.current = controller;

      let finished = false;
      const badge =
        options?.showBadge === false
          ? undefined
          : window.setTimeout(() => {
              if (!finished && !controller.signal.aborted) setRendering(true);
            }, BADGE_DELAY_MS);

      void render
        .current(controller.signal)
        .catch(reportFailure)
        .finally(() => {
          finished = true;
          if (badge !== undefined) window.clearTimeout(badge);
          if (!controller.signal.aborted && renderController.current === controller) {
            setRendering(false);
          }
        });

      return () => {
        if (badge !== undefined) window.clearTimeout(badge);
        if (renderController.current === controller) {
          controller.abort();
          renderController.current = null;
        }
      };
    },
    [reportFailure],
  );

  // Первая отрисовка листа. Старая задача отменяется при смене листа: иначе при быстром
  // перелистывании поверх актуальной страницы дорисуется прежняя.
  useEffect(() => {
    if (!backend || !page) return;
    return startRender();
    // Масштаб намеренно не в зависимостях: перерисовка по зуму идёт отдельно, с
    // задержкой, иначе каждый щелчок колеса ставил бы новую задачу отрисовки.
  }, [backend, page, startRender]);

  // Перерисовка страницы после того, как жест затих.
  //
  // Подписка зависит только от камеры. Раньше в зависимостях стояли обработчики,
  // пересоздаваемые на каждый рендер, а рендер случался на каждый щелчок колеса —
  // очистка эффекта снимала таймер раньше, чем он срабатывал, и страница не
  // перерисовывалась вообще. Зум при этом «не работал»: менялся только слой областей.
  useEffect(() => {
    let timer: number | undefined;

    const unsubscribe = camera.subscribe(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        startRender({ showBadge: false });
      }, RERENDER_DELAY_MS);
    });

    return () => {
      window.clearTimeout(timer);
      unsubscribe();
    };
  }, [camera, startRender]);

  useEffect(() => {
    paintOverlay();
  }, [paintOverlay]);

  // Вписываем лист при его смене и при изменении размера области.
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

  const pointFromEvent = useCallback(
    (clientX: number, clientY: number) => {
      const element = stack.current;
      if (!element || !page) return null;

      const bounds = element.getBoundingClientRect();
      const placed = placeRenderedPage(
        page,
        cameraState.current.scale,
        window.devicePixelRatio || 1,
      );

      return toNormalizedPoint({ x: clientX - bounds.left, y: clientY - bounds.top }, placed);
    },
    [page],
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

  const paintScale = useCallback(() => {
    const canvas = scaleCanvas.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context || !page || !scaleDraft) return;

    const ratio = window.devicePixelRatio || 1;
    const placed = placeRenderedPage(page, renderedScale.current, ratio);
    resizeOverlay(canvas, placed.width, placed.height, ratio);

    // Черновик калибровки рисуется по той же бумаге — и теми же чернилами.
    const color = readSheetInk().accent;
    drawScaleDraft(
      context,
      placed,
      scaleDraft.getState(),
      { color: color || 'currentColor' },
      ratio,
    );
  }, [page, scaleDraft]);

  // Слой перерисовывается по подписке на черновик, а не через состояние React: точка под
  // курсором меняется на каждом движении мыши, и перерисовывать ей дерево компонентов
  // значило бы ронять частоту кадров вместе со всеми панелями.
  useEffect(() => {
    if (!scaleDraft) return;
    paintScale();
    return scaleDraft.subscribe(paintScale);
  }, [scaleDraft, paintScale]);

  const paintMeasurements = useCallback(() => {
    const canvas = measurementCanvas.current;
    const context = canvas?.getContext('2d');
    if (!canvas || !context || !page || !tools) return;

    const ratio = window.devicePixelRatio || 1;
    const placed = placeRenderedPage(page, renderedScale.current, ratio);
    resizeOverlay(canvas, placed.width, placed.height, ratio);

    const toolState = tools.getState();
    // Палитра строк обмера ложится поверх умолчаний: сама строка вправе назвать свой цвет,
    // но по умолчанию берутся чернила, читаемые на бумаге.
    const palette = { ...readSheetInk(), ...measurementColors };
    const fallback = palette.accent || 'currentColor';

    drawMeasurements(
      context,
      placed,
      {
        measurements,
        selectedId: toolState.selectedId,
        hoveredId: null,
        draft: toolState.points,
        draftType: DRAWING_MODES.includes(toolState.mode)
          ? (toolState.mode as OverlayMeasurement['geometryType'])
          : null,
        draftHover: toolState.hover,
        dragOverride: toolState.drag
          ? { id: toolState.drag.measurementId, points: toolState.drag.points }
          : null,
      },
      { colors: palette, fallbackColor: fallback },
      ratio,
    );
  }, [page, tools, measurements, measurementColors]);

  // Слой перерисовывается по подписке на контроллер, а не через состояние React: черновик
  // меняется на каждом движении мыши, и перерисовывать им дерево значило бы ронять кадры.
  useEffect(() => {
    if (!tools) return;
    paintMeasurements();
    return tools.subscribe(paintMeasurements);
  }, [tools, paintMeasurements]);

  // Список измерений приходит из запроса и меняется редко, но перерисовать слой нужно.
  useEffect(() => {
    paintMeasurements();
  }, [paintMeasurements]);

  const drawing = tools !== null && DRAWING_MODES.includes(tools.getState().mode);
  const measuring = tool === 'scale' && scaleDraft !== null;
  const panning = tool === 'pan' || spacePressed;

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    // Средняя кнопка панорамирует всегда, каким бы инструментом ни работали: в AutoCAD
    // и Revit это тот же жест, и переучивать инженера незачем.
    const wheelDrag = event.button === 1;
    if (event.button !== 0 && !wheelDrag) return;
    if (wheelDrag) event.preventDefault();

    if (panning || wheelDrag) {
      dragging.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }

    if (tools) {
      const point = pointFromEvent(event.clientX, event.clientY);
      const state = tools.getState();

      if (point) {
        const placed = placeRenderedPage(
          page ?? { width: 1, height: 1 },
          cameraState.current.scale,
          window.devicePixelRatio || 1,
        );

        // Сначала вершина выбранного измерения: попасть в неё труднее, чем в саму фигуру,
        // и приоритет должен быть у более точного намерения.
        if (state.selectedId) {
          const selected = measurements.find((item) => item.id === state.selectedId);
          const vertex = selected ? hitTestVertex(selected.points, point, placed) : null;
          if (selected && vertex !== null) {
            tools.send({
              type: 'startVertexDrag',
              measurementId: selected.id,
              vertexIndex: vertex,
              points: selected.points,
            });
            event.currentTarget.setPointerCapture(event.pointerId);
            return;
          }
        }

        if (drawing) {
          tools.send({ type: 'pointerDown', point });
          return;
        }

        const found = hitTestMeasurements(measurements, point, placed);
        if (found) {
          tools.send({ type: 'selectMeasurement', measurementId: found.id });
          return;
        }
        if (state.selectedId) {
          tools.send({ type: 'selectMeasurement', measurementId: null });
        }
      }
    }

    if (measuring) {
      const point = pointFromEvent(event.clientX, event.clientY);
      // Точка за пределами листа — промах мимо чертежа, а не намерение: ставить её
      // значило бы получить калибровку по краю поля.
      if (point && point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1) {
        scaleDraft?.pick(point);
      }
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

    if (tools) {
      const state = tools.getState();
      if (state.drag !== null) {
        const point = pointFromEvent(event.clientX, event.clientY);
        // Ни одного запроса: геометрия уйдёт на сервер один раз, по отпусканию.
        if (point) tools.send({ type: 'moveVertex', point });
        return;
      }
      if (drawing) {
        tools.send({ type: 'pointerMove', point: pointFromEvent(event.clientX, event.clientY) });
        return;
      }
    }

    if (measuring) {
      // Ни одного обращения к серверу: черновик живёт в памяти до подтверждения.
      scaleDraft?.hover(pointFromEvent(event.clientX, event.clientY));
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
    if (tools?.getState().drag !== null && tools) {
      tools.send({ type: 'finishVertexDrag' });
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    }
    if (dragging.current?.pointerId === event.pointerId) {
      dragging.current = null;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handleWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    const element = host.current;
    if (!element) return;

    // С модификатором колесо двигает лист, без него — меняет масштаб. Разложение по
    // модификаторам, а не смена режима: после зума лист нужно подвинуть сразу, не
    // переключая инструмент и не отпуская колесо.
    if (event.shiftKey || event.altKey) {
      const step = event.deltaY + event.deltaX;
      // Shift — по горизонтали, Alt — по вертикали: так же ведут себя редакторы чертежей.
      camera.panBy(event.shiftKey ? -step : 0, event.shiftKey ? 0 : -step);
      return;
    }

    const bounds = element.getBoundingClientRect();
    camera.zoomAt(
      { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
      event.deltaY < 0 ? ZOOM_WHEEL_STEP : 1 / ZOOM_WHEEL_STEP,
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
        panning
          ? 'cursor-grab'
          : measuring
            ? 'cursor-crosshair'
            : hoveredId
              ? 'cursor-pointer'
              : 'cursor-default',
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
        <canvas
          ref={scaleCanvas}
          data-testid="scale-layer"
          className={cx('pointer-events-none absolute top-0 left-0', !measuring && 'hidden')}
        />
        <canvas
          ref={measurementCanvas}
          data-testid="measurement-layer"
          className={cx('pointer-events-none absolute top-0 left-0', !tools && 'hidden')}
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
