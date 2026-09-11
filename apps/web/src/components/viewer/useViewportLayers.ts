'use client';

import { useCallback, useEffect, useMemo, useRef, type RefObject } from 'react';

import type { CameraState } from '@/lib/viewer/camera';
import {
  drawMeasurements,
  measurementsTouch,
  type OverlayMeasurement,
} from '@/lib/viewer/measurement-overlay';
import { drawOverlay, overlayTouches, type OverlayRegion } from '@/lib/viewer/overlay';
import type { ScaleDraft } from '@/lib/viewer/scale-draft';
import { drawScaleDraft, scaleDraftTouches } from '@/lib/viewer/scale-overlay';
import type { ShapeIndex } from '@/lib/viewer/shape-index';
import type { ToolController } from '@/lib/viewer/tool-controller';
import { DRAWING_MODES } from '@/lib/viewer/tool-machine';
import { ViewportLayer, type LayerPainter, type LayerView } from '@/lib/viewer/viewport-layer';
import { useTheme } from '@/lib/theme';

/**
 * Слои наложения просмотрщика: области, черновик масштаба, измерения (ADR-0024, ADR-0025).
 *
 * Каждый слой — холст размером с область просмотра, а не с лист, вне стопки страницы. На кадре
 * камеры слой не перерисовывается: его пиксели сдвигаются, и дорисовываются только открывшиеся
 * полосы (`ViewportLayer`). Целиком слой рисуется, когда изменились его данные или затих жест,
 * изменивший масштаб.
 *
 * Слои логически независимы (ADR-0015): у каждого свой холст, свой рисовальщик и своя память о
 * том, как он нарисован. Общий здесь только кадр — догнать камеру.
 */

interface ILayerCanvases {
  readonly hostRef: RefObject<HTMLDivElement | null>;
  readonly regionsRef: RefObject<HTMLCanvasElement | null>;
  readonly scaleRef: RefObject<HTMLCanvasElement | null>;
  readonly measurementsRef: RefObject<HTMLCanvasElement | null>;
}

interface IViewportLayersInput {
  readonly page: { readonly width: number; readonly height: number } | null;
  /** Состояние камеры в ссылке: слои читают его из кадра, а не из состояния React. */
  readonly cameraRef: RefObject<CameraState>;
  readonly hoveredRef: RefObject<string | null>;
  readonly regions: readonly OverlayRegion[];
  readonly hiddenTypes: ReadonlySet<string>;
  readonly overlayVisible: boolean;
  readonly selectedId: string | null;
  readonly scaleDraft: ScaleDraft | null;
  readonly tools: ToolController | null;
  readonly measurements: readonly OverlayMeasurement[];
  /** Пространственный индекс измерений: отсечение спрашивает его, а не весь список (промт 04). */
  readonly measurementIndex: ShapeIndex<OverlayMeasurement>;
  readonly measurementColors: Readonly<Record<string, string>>;
}

type LayerKey = 'regions' | 'scale' | 'measurements';

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

export const useViewportLayers = (canvases: ILayerCanvases, input: IViewportLayersInput) => {
  const { hostRef, regionsRef, scaleRef, measurementsRef } = canvases;
  const {
    page,
    cameraRef,
    hoveredRef,
    regions,
    hiddenTypes,
    overlayVisible,
    selectedId,
    scaleDraft,
    tools,
    measurements,
    measurementIndex,
    measurementColors,
  } = input;

  // Цвета читаются из токенов один раз на тему, а не на каждой полосе панорамы: чтение
  // вычисленного стиля заставляет браузер пересчитать стили документа.
  const theme = useTheme();
  const regionColors = useMemo(() => {
    void theme;
    return readRegionColors();
  }, [theme]);
  const sheetInk = useMemo(() => {
    void theme;
    return readSheetInk();
  }, [theme]);

  const regionsPainter = useMemo<LayerPainter>(() => {
    // Состояние наведения читается в момент рисования: оно меняется мимо React.
    const state = () => ({
      regions: overlayVisible ? regions : [],
      hiddenTypes,
      selectedId,
      hoveredId: hoveredRef.current,
    });
    return {
      paint: (context, placement, ratio, area) => {
        drawOverlay(
          context,
          placement,
          state(),
          { colors: regionColors, fallbackColor: 'currentColor' },
          ratio,
          area,
        );
      },
      touches: (placement, ratio, area) => overlayTouches(placement, state(), ratio, area),
    };
  }, [hoveredRef, regions, hiddenTypes, overlayVisible, selectedId, regionColors]);

  const scalePainter = useMemo<LayerPainter | null>(() => {
    if (!scaleDraft) return null;
    // Черновик калибровки рисуется по той же бумаге — и теми же чернилами.
    const color = sheetInk.accent || 'currentColor';
    return {
      paint: (context, placement, ratio, area) => {
        drawScaleDraft(context, placement, scaleDraft.getState(), { color }, ratio, area);
      },
      touches: () => scaleDraftTouches(scaleDraft.getState()),
    };
  }, [scaleDraft, sheetInk]);

  const measurementsPainter = useMemo<LayerPainter | null>(() => {
    if (!tools) return null;
    // Палитра строк обмера ложится поверх умолчаний: сама строка вправе назвать свой цвет,
    // но по умолчанию берутся чернила, читаемые на бумаге.
    const palette = { ...sheetInk, ...measurementColors };
    const fallback = palette.accent || 'currentColor';

    // Состояние инструментов читается в момент рисования: черновик меняется на каждом движении.
    const state = () => {
      const toolState = tools.getState();
      return {
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
        index: measurementIndex,
      };
    };

    return {
      paint: (context, placement, ratio, area) => {
        drawMeasurements(
          context,
          placement,
          state(),
          { colors: palette, fallbackColor: fallback },
          ratio,
          area,
        );
      },
      touches: (placement, ratio, area) => measurementsTouch(placement, state(), ratio, area),
    };
  }, [tools, measurements, measurementIndex, measurementColors, sheetInk]);

  // Слой создаётся на свой холст один раз и помнит, как нарисован. Холст не пересоздаётся
  // React, пока жив компонент.
  const layers = useRef<Partial<Record<LayerKey, ViewportLayer>>>({});
  const layerOf = useCallback(
    (key: LayerKey): ViewportLayer | null => {
      const refs = { regions: regionsRef, scale: scaleRef, measurements: measurementsRef };
      const canvas = refs[key].current;
      if (!canvas) return null;
      const existing = layers.current[key];
      if (existing) return existing;
      const created = new ViewportLayer(canvas);
      layers.current[key] = created;
      return created;
    },
    [regionsRef, scaleRef, measurementsRef],
  );

  const viewOf = useCallback(
    (camera: CameraState): LayerView | null => {
      const host = hostRef.current;
      if (!host || !page) return null;
      return {
        camera,
        page,
        width: host.clientWidth,
        height: host.clientHeight,
        ratio: window.devicePixelRatio || 1,
      };
    },
    [hostRef, page],
  );

  // Кадр камеры зовёт свежих рисовальщиков через ссылку: подписка на камеру живёт всё время
  // жизни холста и не пересоздаётся вместе с данными слоёв.
  const painters = useRef<Record<LayerKey, LayerPainter | null>>({
    regions: regionsPainter,
    scale: scalePainter,
    measurements: measurementsPainter,
  });
  const view = useRef(viewOf);
  useEffect(() => {
    painters.current = {
      regions: regionsPainter,
      scale: scalePainter,
      measurements: measurementsPainter,
    };
    view.current = viewOf;
  }, [regionsPainter, scalePainter, measurementsPainter, viewOf]);

  const repaint = useCallback(
    (key: LayerKey) => {
      const painter = painters.current[key];
      const current = view.current(cameraRef.current);
      const layer = layerOf(key);
      if (painter && current && layer) layer.repaint(current, painter);
    },
    [cameraRef, layerOf],
  );

  /** Догоняет камеру на кадре: сдвиг пикселей, растяжение или перерисовка — что дешевле. */
  const followCamera = useCallback(
    (camera: CameraState) => {
      const current = view.current(camera);
      if (!current) return;
      for (const key of ['regions', 'scale', 'measurements'] as const) {
        const painter = painters.current[key];
        const layer = layerOf(key);
        if (painter && layer) layer.follow(current, painter);
      }
    },
    [layerOf],
  );

  /** Жест затих: растянутые слои перерисовываются в масштабе камеры. */
  const settleLayers = useCallback(() => {
    const current = view.current(cameraRef.current);
    if (!current) return;
    for (const key of ['regions', 'scale', 'measurements'] as const) {
      const painter = painters.current[key];
      const layer = layerOf(key);
      if (painter && layer) layer.settle(current, painter);
    }
  }, [cameraRef, layerOf]);

  /** Подсветка области под курсором: данные слоя областей изменились. */
  const paintRegions = useCallback(() => repaint('regions'), [repaint]);

  // Данные слоя изменились — слой рисуется целиком. Эффект зависит от рисовальщика, а тот
  // пересоздаётся ровно тогда, когда меняется то, что он рисует.
  useEffect(() => {
    repaint('regions');
  }, [regionsPainter, viewOf, repaint]);

  // Черновик и инструменты меняются на каждом движении мыши. Слой перерисовывается по их
  // подписке, а не через состояние React, — иначе дерево коммитилось бы на каждом кадре.
  useEffect(() => {
    if (!scaleDraft || !scalePainter) return;
    repaint('scale');
    return scaleDraft.subscribe(() => repaint('scale'));
  }, [scaleDraft, scalePainter, viewOf, repaint]);

  useEffect(() => {
    if (!tools || !measurementsPainter) return;
    repaint('measurements');
    return tools.subscribe(() => repaint('measurements'));
  }, [tools, measurementsPainter, viewOf, repaint]);

  return { followCamera, settleLayers, paintRegions };
};
