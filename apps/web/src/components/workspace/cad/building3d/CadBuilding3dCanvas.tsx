'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { useEffect, useMemo, useRef, type FC } from 'react';

import { buildBuildingPlan } from '@/lib/cad/building3d-geometry';
import { createBuilding3dView, readBuilding3dColors, type IBuilding3dView } from '@/lib/cad/building3d-scene';
import { useTheme } from '@/lib/theme';

interface ICadBuilding3dCanvasProps {
  readonly floors: readonly CadBuilding3dFloorRead[];
  readonly currentKey: string | null;
  readonly hoverKey: string | null;
  readonly onHover: (key: string | null, anchor: { x: number; y: number } | null) => void;
  readonly onSelect: (key: string) => void;
  /** Холст создать не удалось (нет WebGL). */
  readonly onError: (message: string) => void;
}

/**
 * Холст three.js колонки «Здание»: владеет renderer'ом и освобождает его при размонтировании.
 * Модель пересобирается при смене набора этажей и темы; подсветка - отдельным эффектом.
 */
export const CadBuilding3dCanvas: FC<ICadBuilding3dCanvasProps> = ({
  floors,
  currentKey,
  hoverKey,
  onHover,
  onSelect,
  onError,
}) => {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<IBuilding3dView | null>(null);
  const theme = useTheme();
  const plan = useMemo(() => buildBuildingPlan(floors), [floors]);

  // Колбэки читаются в момент события: смена пропсов движок не пересоздаёт.
  const handlers = useRef({ onHover, onSelect, onError });
  const highlight = useRef({ currentKey, hoverKey });
  useEffect(() => {
    handlers.current = { onHover, onSelect, onError };
    highlight.current = { currentKey, hoverKey };
  });

  useEffect(() => {
    const element = host.current;
    if (element === null) return undefined;
    try {
      view.current = createBuilding3dView(element, {
        onHover: (key, anchor) => handlers.current.onHover(key, anchor),
        onSelect: (key) => handlers.current.onSelect(key),
      });
    } catch {
      handlers.current.onError('Не удалось запустить 3D: в браузере недоступен WebGL.');
      return undefined;
    }
    return () => {
      view.current?.dispose();
      view.current = null;
    };
  }, []);

  useEffect(() => {
    view.current?.setPlan(plan, readBuilding3dColors());
    view.current?.setHighlight(highlight.current.currentKey, highlight.current.hoverKey);
  }, [plan, theme]);

  useEffect(() => {
    view.current?.setHighlight(currentKey, hoverKey);
  }, [currentKey, hoverKey]);

  return (
    <div
      ref={host}
      role="img"
      aria-label="Здание в аксонометрии: этажи"
      className="h-full w-full cursor-grab active:cursor-grabbing"
    />
  );
};
