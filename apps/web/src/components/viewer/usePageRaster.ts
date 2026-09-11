'use client';

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';

import { DocumentLoadError, RenderCancelledError, type RenderBackend } from '@/lib/viewer/backend';
import type { CameraState } from '@/lib/viewer/camera';
import {
  pieceStyle,
  planRaster,
  planStillValid,
  samePlan,
  stackTransform,
  type RasterPiece,
  type RasterPlan,
} from '@/lib/viewer/surface';

/**
 * Растр страницы в стопке: весь лист или подложка с резкой частью (ADR-0025).
 *
 * Стопка двигается CSS-преобразованием на каждом кадре камеры, растры в ней не перерисовываются.
 * pdf.js зовётся только когда жест затих, и только за тем, чего виду не хватает: листом в новом
 * масштабе, резкой частью за краем прежней или подложкой. Чистая панорама внутри резкой части
 * не рисует ничего.
 *
 * Растр рисуется в отсоединённый холст и встаёт на место прежнего одним шагом: отрисовщик
 * меняет размер холста в начале работы, а смена размера стирает холст, и рисуй он в видимый,
 * страница пропадала бы на всё время отрисовки.
 */

interface IPageRasterInput {
  readonly backend: RenderBackend | null;
  readonly page: {
    readonly pageIndex: number;
    readonly width: number;
    readonly height: number;
  } | null;
  readonly cameraRef: RefObject<CameraState>;
  readonly hostRef: RefObject<HTMLDivElement | null>;
  readonly stackRef: RefObject<HTMLDivElement | null>;
  readonly pageHostRef: RefObject<HTMLDivElement | null>;
  readonly onError: (code: string) => void;
}

/** Задержка перед показом значка отрисовки: быстрые листы не должны им мигать. */
const BADGE_DELAY_MS = 120;

const BASE_CLASS = 'absolute block bg-canvas shadow-[var(--shadow-sheet)]';
const DETAIL_CLASS = 'absolute block';

/** Освобождает память растра сразу, не дожидаясь сборщика: у A1 на 266 % это сотни мегабайт. */
const release = (canvas: HTMLCanvasElement | undefined): void => {
  if (!canvas) return;
  canvas.width = 0;
  canvas.height = 0;
};

interface Piece extends RasterPiece {
  readonly canvas: HTMLCanvasElement;
}

interface Running {
  readonly plan: RasterPlan;
  readonly controller: AbortController;
}

export const usePageRaster = ({
  backend,
  page,
  cameraRef,
  hostRef,
  stackRef,
  pageHostRef,
  onError,
}: IPageRasterInput) => {
  const [rendering, setRendering] = useState(false);

  const base = useRef<Piece | null>(null);
  const detail = useRef<Piece | null>(null);
  // Чей лист лежит в стопке. При смене листа или документа прежние растры убираются сразу:
  // показывать чужой лист в раскладке нового хуже, чем пустое место до отрисовки.
  const rendered = useRef<{
    readonly backend: RenderBackend;
    readonly pageIndex: number;
  } | null>(null);
  // Масштаб, в котором разложена стопка: её CSS-пиксели — лист × этот масштаб.
  const layoutScale = useRef(1);
  // Одна активная отрисовка: pdf.js 6 падает, когда две задачи идут по одному холсту, а две
  // параллельные ещё и спорят, чей растр встанет последним.
  const running = useRef<Running | null>(null);
  // Последний поставленный растр. Страховка от шторма отрисовок: если план снова требует ровно
  // его же, значит, план и покрытие разошлись в арифметике, и повторять pdf.js бессмысленно.
  const installed = useRef<RasterPlan | null>(null);

  const failed = useRef(onError);
  useEffect(() => {
    failed.current = onError;
  }, [onError]);

  /** Двигает стопку по камере. Вызывается на каждом её кадре — дёшево, без отрисовки. */
  const placeStack = useCallback(
    (state: CameraState) => {
      const element = stackRef.current;
      if (element) element.style.transform = stackTransform(layoutScale.current, state);
    },
    [stackRef],
  );

  /** Раскладывает растры в стопке по масштабу самого резкого из них. */
  const layout = useCallback(() => {
    const scale = detail.current?.region.scale ?? base.current?.region.scale;
    if (scale !== undefined) layoutScale.current = scale;

    for (const piece of [base.current, detail.current]) {
      if (!piece) continue;
      Object.assign(piece.canvas.style, pieceStyle(piece.region, layoutScale.current));
    }
    placeStack(cameraRef.current);
  }, [cameraRef, placeStack]);

  const releaseAll = useCallback(() => {
    running.current?.controller.abort();
    running.current = null;
    installed.current = null;
    release(base.current?.canvas);
    release(detail.current?.canvas);
    base.current = null;
    detail.current = null;
    pageHostRef.current?.replaceChildren();
  }, [pageHostRef]);

  /** Ставит готовый растр на место и убирает то, что он заменил. */
  const install = useCallback(
    (plan: RasterPlan, canvas: HTMLCanvasElement) => {
      const container = pageHostRef.current;
      if (!container) {
        release(canvas);
        return;
      }

      installed.current = plan;
      const piece: Piece = { region: plan.region, ratio: plan.ratio, canvas };
      if (plan.kind === 'detail') {
        canvas.className = DETAIL_CLASS;
        release(detail.current?.canvas);
        detail.current = piece;
      } else {
        canvas.className = BASE_CLASS;
        release(base.current?.canvas);
        base.current = piece;
        // Лист в масштабе камеры резок сам: резкая часть от прежнего масштаба только мешает.
        if (plan.kind === 'page') {
          release(detail.current?.canvas);
          detail.current = null;
        }
      }

      const children = [base.current?.canvas, detail.current?.canvas].filter(
        (item): item is HTMLCanvasElement => item !== undefined,
      );
      container.replaceChildren(...children);
      layout();
    },
    [pageHostRef, layout],
  );

  // Функции планирования ссылаются друг на друга через ссылку: отрисовка, закончившись,
  // сразу проверяет, не нужна ли следующая (подложка после резкой части).
  const scheduleRef = useRef<() => void>(() => undefined);

  const schedule = useCallback(() => {
    const host = hostRef.current;
    if (!backend || !page || !host) return;

    const state = cameraRef.current;
    const viewport = { width: host.clientWidth, height: host.clientHeight };
    const ratio = window.devicePixelRatio || 1;
    const plan = planRaster(
      { base: base.current, detail: detail.current },
      page,
      state,
      viewport,
      ratio,
    );

    const current = running.current;
    if (current && plan && planStillValid(current.plan, plan, page, state, viewport)) return;
    current?.controller.abort();
    running.current = null;
    if (!plan || (installed.current && samePlan(installed.current, plan))) {
      setRendering(false);
      return;
    }

    const controller = new AbortController();
    running.current = { plan, controller };
    const canvas = document.createElement('canvas');

    // Значок — только пока листа не видно вовсе. Резкая часть или подложка поверх уже
    // видимого листа значка не заслуживают: картинка на экране есть.
    let finished = false;
    const badge =
      base.current === null
        ? window.setTimeout(() => {
            if (!finished && !controller.signal.aborted) setRendering(true);
          }, BADGE_DELAY_MS)
        : undefined;

    const done = () => {
      finished = true;
      if (badge !== undefined) window.clearTimeout(badge);
      if (running.current?.controller === controller) running.current = null;
      setRendering(false);
    };

    backend
      .render({
        pageIndex: page.pageIndex,
        scale: plan.region.scale,
        canvas,
        signal: controller.signal,
        pixelRatio: plan.ratio,
        ...(plan.kind === 'detail' ? { region: plan.region } : {}),
      })
      .then(() => {
        if (controller.signal.aborted) {
          release(canvas);
          return;
        }
        done();
        install(plan, canvas);
        scheduleRef.current();
      })
      .catch((error: unknown) => {
        release(canvas);
        if (controller.signal.aborted || error instanceof RenderCancelledError) return;
        done();
        failed.current(error instanceof DocumentLoadError ? error.code : 'PDF_RENDER_FAILED');
      });
  }, [backend, page, hostRef, cameraRef, install]);

  useEffect(() => {
    scheduleRef.current = schedule;
  }, [schedule]);

  // Первая отрисовка листа. При смене листа прежние растры убираются, а незавершённая задача
  // обрывается: иначе при быстром перелистывании поверх актуальной страницы дорисуется прежняя.
  useEffect(() => {
    if (!backend || !page) return;
    const previous = rendered.current;
    if (previous?.backend !== backend || previous.pageIndex !== page.pageIndex) {
      releaseAll();
      rendered.current = { backend, pageIndex: page.pageIndex };
    }
    schedule();
    return () => {
      running.current?.controller.abort();
      running.current = null;
    };
  }, [backend, page, schedule, releaseAll]);

  useEffect(() => releaseAll, [releaseAll]);

  /**
   * Жест затих: нарисовать то, чего виду не хватает. Проверка — в момент затихания, а не в
   * начале жеста: масштаб и положение могли измениться по ходу. Функция стабильна: подписка на
   * затихание не пересоздаётся вместе с листом.
   */
  const settleRaster = useCallback(() => scheduleRef.current(), []);

  return { rendering, placeStack, settleRaster };
};
