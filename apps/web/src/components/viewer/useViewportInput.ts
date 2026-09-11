'use client';

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';

import type { Camera, CameraState } from '@/lib/viewer/camera';
import { placeViewportPage, toNormalizedPoint } from '@/lib/viewer/coordinates';
import {
  hitTestMeasurements,
  hitTestVertex,
  type OverlayMeasurement,
} from '@/lib/viewer/measurement-overlay';
import type { OverlayRegion } from '@/lib/viewer/overlay';
import type { ShapeIndex } from '@/lib/viewer/shape-index';
import type { ScaleDraft } from '@/lib/viewer/scale-draft';
import type { ToolController } from '@/lib/viewer/tool-controller';
import { DRAWING_MODES } from '@/lib/viewer/tool-machine';

/**
 * Ввод просмотрщика: указатель, колесо и клавиши.
 *
 * Главное правило — ни одного коммита React и ни одного запроса на движении мыши (ADR-0004).
 * Жест идёт в камеру, черновик масштаба или контроллер инструментов, подсветка области —
 * атрибутом и кадром слоя. Координата под указателем считается той же формулой камеры, что
 * рисует слои (ADR-0024), и не зависит от размера растра страницы.
 */

/** Шаг зума на щелчок колеса. Множитель, а не слагаемое: на мелком масштабе шаг иначе огромен. */
const ZOOM_WHEEL_STEP = 1.12;

interface IViewportInput {
  readonly hostRef: RefObject<HTMLDivElement | null>;
  readonly camera: Camera;
  readonly cameraStateRef: RefObject<CameraState>;
  readonly hoveredRef: RefObject<string | null>;
  readonly page: { readonly width: number; readonly height: number } | null;
  readonly regions: readonly OverlayRegion[];
  readonly hiddenTypes: ReadonlySet<string>;
  readonly overlayVisible: boolean;
  readonly measurements: readonly OverlayMeasurement[];
  /** Пространственный индекс измерений: попадание проверяет только его кандидатов (промт 04). */
  readonly measurementIndex: ShapeIndex<OverlayMeasurement> | null;
  readonly tools: ToolController | null;
  readonly scaleDraft: ScaleDraft | null;
  readonly tool: 'pointer' | 'pan' | 'scale';
  readonly onSelect: (id: string | null) => void;
  readonly paintRegions: () => void;
}

export const useViewportInput = ({
  hostRef,
  camera,
  cameraStateRef,
  hoveredRef,
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
}: IViewportInput) => {
  const dragging = useRef<{ pointerId: number; x: number; y: number } | null>(null);
  const [spacePressed, setSpacePressed] = useState(false);

  /** Указатель → нормализованная точка листа: та же формула камеры, что рисует слои. */
  const pointFromEvent = useCallback(
    (clientX: number, clientY: number) => {
      const element = hostRef.current;
      if (!element || !page) return null;

      const bounds = element.getBoundingClientRect();
      return toNormalizedPoint(
        { x: clientX - bounds.left, y: clientY - bounds.top },
        placeViewportPage(page, cameraStateRef.current),
      );
    },
    [hostRef, cameraStateRef, page],
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

  /** Меняет подсвеченную область без коммита React: курсор — атрибутом, подсветка — кадром. */
  const setHovered = useCallback(
    (id: string | null) => {
      if (id === hoveredRef.current) return;
      hoveredRef.current = id;
      const element = hostRef.current;
      if (element) {
        if (id) element.dataset.hover = 'region';
        else delete element.dataset.hover;
      }
      paintRegions();
    },
    [hostRef, hoveredRef, paintRegions],
  );

  const drawing = tools !== null && DRAWING_MODES.includes(tools.getState().mode);
  const measuring = tool === 'scale' && scaleDraft !== null;
  const panning = tool === 'pan' || spacePressed;

  // Панорама и калибровка подсветку областей не показывают: курсор у них свой.
  useEffect(() => {
    if (panning || measuring) setHovered(null);
  }, [panning, measuring, setHovered]);

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
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

      if (point && page) {
        const placed = placeViewportPage(page, cameraStateRef.current);

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
          // Пустой черновик: щелчок по уже сохранённой фигуре выбирает её, а не начинает
          // новую. Иначе в режиме «Линия» нельзя ни выделить, ни удалить нарисованное.
          if (state.points.length === 0) {
            const found = hitTestMeasurements(
              measurements,
              point,
              placed,
              undefined,
              measurementIndex,
            );
            if (found) {
              tools.send({ type: 'selectMeasurement', measurementId: found.id });
              return;
            }
          }
          tools.send({ type: 'pointerDown', point });
          return;
        }

        const found = hitTestMeasurements(measurements, point, placed, undefined, measurementIndex);
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

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
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

    setHovered(findRegion(event.clientX, event.clientY)?.id ?? null);
  };

  const onPointerEnd = (event: React.PointerEvent<HTMLDivElement>) => {
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

  const onWheel = (event: React.WheelEvent<HTMLDivElement>) => {
    const element = hostRef.current;
    if (!element) return;

    // С модификатором колесо двигает лист, без него — меняет масштаб. Разложение по
    // модификаторам, а не смена режима: после зума лист нужно подвинуть сразу.
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

  return {
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: onPointerEnd,
      onPointerCancel: onPointerEnd,
      onWheel,
    },
    panning,
    measuring,
  };
};
