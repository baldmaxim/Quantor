'use client';

import { useMemo, useRef, useState, type FC } from 'react';

import type { CadZoneRead } from '@quantor/api-client';

import { Button } from '@/components/ui';
import { buildSnapIndex, snapPoint, type ISnapResult } from '@/lib/cad/zone-snap';
import { drawSnapMarker } from '@/lib/cad/zone-snap-marker';
import {
  locateOnRing,
  ringArea,
  splitRing,
  type ISplitPoint,
  type ZoneRing,
} from '@/lib/cad/zone-split';
import { readZoneColors, zoneColor } from '@/lib/cad/zones-painter';
import type { Camera } from '@/lib/viewer/camera';
import {
  placeViewportPage,
  toNormalizedPoint,
  toScreenPoint,
  type ScreenPoint,
} from '@/lib/viewer/coordinates';

import { CadZoneModeBar } from './CadZoneModeBar';
import { useZoneOverlay } from './useZoneOverlay';

/** Две части разреза: большая остаётся исходной зоне, меньшая становится новой зоной. */
export interface ISplitParts {
  readonly keep: [number, number][];
  readonly created: [number, number][];
}

export interface ICadZoneSplitProps {
  camera: Camera;
  /** Размер страницы у отрисовщика (pt при масштабе 1) - единицы листа в камере. */
  page: { readonly width: number; readonly height: number };
  /** Зоны листа: из них берётся разрезаемая. */
  zones: readonly CadZoneRead[];
  zoneId: string;
  /** Запись идёт. */
  saving: boolean;
  /** Отказ сервера при записи частей. */
  error: string | null;
  /** Линия принята: части в долях листа от левого верхнего угла. */
  onApply: (parts: ISplitParts) => void;
  /** Esc без поставленной точки или «Отмена». */
  onCancel: () => void;
}

const DRAFT_DASH = [6, 4];
const EMPTY_RING: ZoneRing = [];

const HINT_FIRST = 'Поставьте первую точку на границе помещения. Esc - отмена.';
const HINT_SECOND =
  'Поставьте вторую точку на границе: помещение делится по линии. Esc - сбросить первую точку.';

const pairs = (ring: ZoneRing): [number, number][] => ring.map(([x, y]) => [x, y]);

/**
 * Разрез зоны-помещения: две точки на границе выбранной зоны, между ними - предпросмотр отрезка.
 *
 * Точки липнут только к вершинам и рёбрам разрезаемой зоны; вне границы щелчок не принимается.
 * Большая часть остаётся исходной зоне, меньшая уходит в новую (запись - у вызывающего).
 * Положение курсора и первая точка ведутся в refs: движение только перерисовывает холст (ADR-0004).
 */
export const CadZoneSplit: FC<ICadZoneSplitProps> = ({
  camera,
  page,
  zones,
  zoneId,
  saving,
  error,
  onApply,
  onCancel,
}) => {
  const zone = zones.find((item) => item.id === zoneId) ?? null;
  const [initial] = useState<ZoneRing>(() => zone?.points ?? EMPTY_RING);
  const first = useRef<ISplitPoint | null>(null);
  const hover = useRef<ISnapResult | null>(null);
  const [started, setStarted] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);

  const layerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colors = useMemo(() => readZoneColors(), []);
  const color = zoneColor(colors, zone?.kind ?? 'room_mop');
  // Цель привязки одна - граница разрезаемой зоны; стены и другие зоны не участвуют.
  const index = useMemo(() => buildSnapIndex([{ points: initial, closed: true }]), [initial]);

  const snapAt = (screen: ScreenPoint): ISnapResult => {
    const sheet = placeViewportPage(page, camera.getState());
    return snapPoint(toNormalizedPoint(screen, sheet), {
      index,
      walls: null,
      scale: { x: sheet.width, y: sheet.height },
      placed: [],
      shift: false,
      alt: false,
    });
  };

  const overlay = useZoneOverlay(camera, page, layerRef, canvasRef, {
    draw: (context, sheet, extent) => {
      const vertices = initial.map(([x, y]) => toScreenPoint({ x, y }, sheet));
      context.lineJoin = 'round';
      context.strokeStyle = color;
      context.lineWidth = 2;
      context.beginPath();
      vertices.forEach((point, at) => {
        if (at === 0) context.moveTo(point.x, point.y);
        else context.lineTo(point.x, point.y);
      });
      context.closePath();
      context.stroke();

      const cursor = hover.current ? toScreenPoint(hover.current.point, sheet) : null;
      const start = first.current ? toScreenPoint(first.current.point, sheet) : null;
      if (start) {
        if (cursor) {
          context.setLineDash(DRAFT_DASH);
          context.beginPath();
          context.moveTo(start.x, start.y);
          context.lineTo(cursor.x, cursor.y);
          context.stroke();
          context.setLineDash([]);
        }
        context.fillStyle = color;
        context.beginPath();
        context.arc(start.x, start.y, 5, 0, Math.PI * 2);
        context.fill();
      }
      if (cursor) drawSnapMarker(context, colors, hover.current, cursor, null, extent);
    },
    onHover: (screen) => {
      hover.current = screen ? snapAt(screen) : null;
      overlay.redraw();
    },
    onTap: (screen) => {
      if (saving) return;
      const snapped = snapAt(screen);
      const located =
        snapped.kind === 'vertex' || snapped.kind === 'edge'
          ? locateOnRing(initial, snapped.point)
          : null;
      if (located === null) {
        setRefusal('Точка должна лежать на границе помещения.');
        return;
      }
      const start = first.current;
      if (start === null) {
        first.current = located;
        setStarted(true);
        setRefusal(null);
        overlay.redraw();
        return;
      }
      const result = splitRing(initial, start, located);
      if (!result.ok) {
        setRefusal(result.reason);
        return;
      }
      setRefusal(null);
      const [one, two] = result.rings;
      const oneLarger = ringArea(one) >= ringArea(two);
      onApply({ keep: pairs(oneLarger ? one : two), created: pairs(oneLarger ? two : one) });
    },
    onKey: (event) => {
      if (event.key !== 'Escape') return;
      if (first.current !== null) {
        first.current = null;
        setStarted(false);
        setRefusal(null);
        overlay.redraw();
      } else {
        onCancel();
      }
    },
  });

  return (
    <div className="pointer-events-none absolute inset-0 z-10" data-testid="zone-split-root">
      <div
        ref={layerRef}
        data-testid="zone-split"
        role="application"
        aria-label="Разрез зоны: поставьте две точки на границе"
        {...overlay.bind}
        className="pointer-events-auto absolute inset-0 cursor-crosshair touch-none"
      >
        <canvas ref={canvasRef} className="pointer-events-none absolute top-0 left-0" />
      </div>
      <CadZoneModeBar hint={started ? HINT_SECOND : HINT_FIRST} problem={refusal ?? error}>
        <Button compact className="max-md:h-[44px]" onClick={onCancel}>
          Отмена
        </Button>
      </CadZoneModeBar>
    </div>
  );
};
