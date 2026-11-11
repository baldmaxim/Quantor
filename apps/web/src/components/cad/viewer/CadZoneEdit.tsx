'use client';

import { useMemo, useRef, useState, type FC } from 'react';

import type { CadZoneRead } from '@quantor/api-client';

import { Button } from '@/components/ui';
import {
  edgeHandle,
  hitMidpoint,
  hitVertex,
  insertMidpoint,
  moveVertex,
  removeVertex,
  type EditRing,
} from '@/lib/cad/zone-edit';
import {
  buildSnapIndex,
  snapPoint,
  zonesToSnapShapes,
  type ISnapIndex,
  type ISnapResult,
} from '@/lib/cad/zone-snap';
import { drawSnapMarker } from '@/lib/cad/zone-snap-marker';
import { readZoneColors, zoneColor } from '@/lib/cad/zones-painter';
import type { Camera } from '@/lib/viewer/camera';
import {
  clamp,
  placeViewportPage,
  toNormalizedPoint,
  toScreenPoint,
  type ScreenPoint,
} from '@/lib/viewer/coordinates';

import { CadZoneModeBar } from './CadZoneModeBar';
import { useZoneOverlay, type IOverlayModifiers } from './useZoneOverlay';

export interface ICadZoneEditProps {
  camera: Camera;
  /** Размер страницы у отрисовщика (pt при масштабе 1) - единицы листа в камере. */
  page: { readonly width: number; readonly height: number };
  /** Зоны листа: вершины и рёбра остальных - цели привязки. */
  zones: readonly CadZoneRead[];
  /** Правимая зона-помещение. */
  zoneId: string;
  /** Углы и грани стен листа; нет - привязка только к зонам. */
  walls?: ISnapIndex | null;
  /** Запись идёт. */
  saving: boolean;
  /** Отказ сервера (самопересечение и т.п.): режим остаётся открытым. */
  error: string | null;
  /** Enter или «Сохранить»: новый контур в долях листа от левого верхнего угла. */
  onSave: (points: [number, number][]) => void;
  /** Esc или «Отмена»: без изменений. */
  onCancel: () => void;
}

const HANDLE_RADIUS = 5;
const HANDLE_RADIUS_ACTIVE = 7;
const MID_RADIUS = 3.5;
const FILL_ALPHA = 0.15;

const HINT =
  'Тяните вершины; точка в середине ребра добавляет вершину. Delete - убрать выбранную вершину (не меньше 3), Enter - сохранить, Esc - отмена. Shift - орто, Alt - без привязки.';

/**
 * Правка контура зоны-помещения: ручки на вершинах и в серединах рёбер.
 *
 * Контур, выбранная вершина и привязка ведутся в refs, не в React: перетаскивание только
 * перерисовывает холст (ADR-0004). Привязка при перетаскивании та же, что при рисовании: вершины и
 * рёбра остальных зон, углы и грани стен, Shift - орто от предыдущей вершины, Alt - выкл.
 */
export const CadZoneEdit: FC<ICadZoneEditProps> = ({
  camera,
  page,
  zones,
  zoneId,
  walls = null,
  saving,
  error,
  onSave,
  onCancel,
}) => {
  const zone = zones.find((item) => item.id === zoneId) ?? null;
  const [initial] = useState<EditRing>(() => zone?.points ?? []);
  const ring = useRef<EditRing>(initial);
  const selected = useRef<number | null>(null);
  const hover = useRef<number | null>(null);
  const drag = useRef<number | null>(null);
  const snap = useRef<ISnapResult | null>(null);

  const layerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colors = useMemo(() => readZoneColors(), []);
  const color = zoneColor(colors, zone?.kind ?? 'room_mop');
  // Цели привязки - остальные зоны листа; свой контур правится, к себе не липнет.
  const snapIndex = useMemo(
    () => buildSnapIndex(zonesToSnapShapes(zones.filter((item) => item.id !== zoneId))),
    [zones, zoneId],
  );

  const placement = () => placeViewportPage(page, camera.getState());
  const screenRing = () => ring.current.map(([x, y]) => toScreenPoint({ x, y }, placement()));

  // Привязка перетаскиваемой вершины: опора ortho - предыдущая вершина, соседние вершины не цели.
  const snapDrag = (screen: ScreenPoint, modifiers: IOverlayModifiers, index: number) => {
    const sheet = placement();
    const current = ring.current;
    const count = current.length;
    const before = (index - 1 + count) % count;
    const after = (index + 1) % count;
    const prev = current[before] as readonly [number, number];
    const others = current
      .filter((_, at) => at !== index && at !== before && at !== after)
      .map(([x, y]) => ({ x, y }));
    return snapPoint(toNormalizedPoint(screen, sheet), {
      index: snapIndex,
      walls,
      scale: { x: sheet.width, y: sheet.height },
      placed: [...others, { x: prev[0], y: prev[1] }],
      shift: modifiers.shift,
      alt: modifiers.alt,
    });
  };

  const overlay = useZoneOverlay(camera, page, layerRef, canvasRef, {
    draw: (context, sheet, extent) => {
      const vertices = ring.current.map(([x, y]) => toScreenPoint({ x, y }, sheet));
      if (vertices.length === 0) return;
      context.lineJoin = 'round';
      context.beginPath();
      vertices.forEach((point, at) => {
        if (at === 0) context.moveTo(point.x, point.y);
        else context.lineTo(point.x, point.y);
      });
      context.closePath();
      context.fillStyle = color;
      context.globalAlpha = FILL_ALPHA;
      context.fill();
      context.globalAlpha = 1;
      context.strokeStyle = color;
      context.lineWidth = 2;
      context.stroke();

      // Середины рёбер: ромб, тянуть - добавить вершину.
      context.fillStyle = colors.paper;
      for (let edge = 0; edge < vertices.length; edge += 1) {
        const handle = edgeHandle(vertices, edge);
        if (!handle) continue;
        context.beginPath();
        context.moveTo(handle.x, handle.y - MID_RADIUS);
        context.lineTo(handle.x + MID_RADIUS, handle.y);
        context.lineTo(handle.x, handle.y + MID_RADIUS);
        context.lineTo(handle.x - MID_RADIUS, handle.y);
        context.closePath();
        context.fill();
        context.stroke();
      }
      vertices.forEach((point, at) => {
        const active = at === selected.current;
        const raised = active || at === hover.current;
        context.beginPath();
        context.arc(
          point.x,
          point.y,
          raised ? HANDLE_RADIUS_ACTIVE : HANDLE_RADIUS,
          0,
          Math.PI * 2,
        );
        context.fillStyle = active ? color : colors.paper;
        context.fill();
        context.stroke();
      });

      const dragged = drag.current;
      if (dragged !== null && snap.current) {
        const count = vertices.length;
        const anchor = vertices[(dragged - 1 + count) % count] ?? null;
        drawSnapMarker(
          context,
          colors,
          snap.current,
          toScreenPoint(snap.current.point, sheet),
          anchor,
          extent,
        );
      }
    },
    onHover: (screen) => {
      const next = screen ? hitVertex(screenRing(), screen) : -1;
      const value = next >= 0 ? next : null;
      if (value === hover.current) return;
      hover.current = value;
      overlay.redraw();
    },
    onPress: (screen) => {
      const vertices = screenRing();
      const vertex = hitVertex(vertices, screen);
      if (vertex >= 0) {
        selected.current = vertex;
        drag.current = vertex;
        overlay.redraw();
        return true;
      }
      const edge = hitMidpoint(vertices, screen);
      const inserted = edge >= 0 ? insertMidpoint(ring.current, edge) : null;
      if (inserted) {
        ring.current = inserted.ring;
        selected.current = inserted.index;
        drag.current = inserted.index;
        overlay.redraw();
        return true;
      }
      return false;
    },
    onDrag: (screen, modifiers) => {
      const index = drag.current;
      if (index === null) return;
      const result = snapDrag(screen, modifiers, index);
      snap.current = result;
      ring.current = moveVertex(ring.current, index, {
        x: clamp(result.point.x, 0, 1),
        y: clamp(result.point.y, 0, 1),
      });
      overlay.redraw();
    },
    onRelease: () => {
      drag.current = null;
      snap.current = null;
      overlay.redraw();
    },
    onTap: () => {
      // Щелчок мимо ручек снимает выбор вершины.
      if (selected.current === null) return;
      selected.current = null;
      overlay.redraw();
    },
    onKey: (event) => {
      if (event.key === 'Enter') {
        save();
        event.preventDefault();
      } else if (event.key === 'Escape') {
        onCancel();
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        const index = selected.current;
        if (index === null) return;
        event.preventDefault();
        const next = removeVertex(ring.current, index);
        if (!next) return;
        ring.current = next;
        selected.current = null;
        hover.current = null;
        overlay.redraw();
      }
    },
  });

  const save = () => {
    if (saving) return;
    onSave(ring.current.map(([x, y]) => [x, y]));
  };

  return (
    <div className="pointer-events-none absolute inset-0 z-10" data-testid="zone-edit-root">
      <div
        ref={layerRef}
        data-testid="zone-edit"
        role="application"
        aria-label="Правка контура зоны: тяните вершины"
        {...overlay.bind}
        className="pointer-events-auto absolute inset-0 cursor-crosshair touch-none"
      >
        <canvas ref={canvasRef} className="pointer-events-none absolute top-0 left-0" />
      </div>
      <CadZoneModeBar hint={HINT} problem={error}>
        <Button
          variant="primary"
          compact
          disabled={saving}
          className="max-md:h-[44px]"
          onClick={save}
        >
          Сохранить
        </Button>
        <Button compact className="max-md:h-[44px]" onClick={onCancel}>
          Отмена
        </Button>
      </CadZoneModeBar>
    </div>
  );
};
