'use client';

import { useEffect, useRef, type FC } from 'react';

import { createFloor3dEngine, type Floor3dViewKind, type IFloor3dEngine } from '@/lib/cad/floor3d-engine';
import type { IFloor3dPlan } from '@/lib/cad/floor3d-geometry';
import { buildFloor3dScene, readFloor3dColors, type IFloor3dPick } from '@/lib/cad/floor3d-scene';
import { useTheme } from '@/lib/theme';

/** Запрос камеры: `seq` меняется при каждом нажатии, чтобы повторная команда не терялась. */
export interface IFloor3dViewRequest {
  readonly kind: Floor3dViewKind | 'fit';
  readonly seq: number;
}

interface ICadFloor3dCanvasProps {
  readonly plan: IFloor3dPlan;
  readonly showSlabCap: boolean;
  readonly viewRequest: IFloor3dViewRequest | null;
  readonly onPick: (pick: IFloor3dPick | null, anchor: { x: number; y: number }) => void;
  readonly onMove: () => void;
  /** Холст создать не удалось (нет WebGL). */
  readonly onError: (message: string) => void;
}

/**
 * Холст three.js: владеет renderer'ом и освобождает его при размонтировании. Модель пересобирается
 * при смене плана, темы и галки «Плита сверху»; камера при этом не сбрасывается.
 */
export const CadFloor3dCanvas: FC<ICadFloor3dCanvasProps> = ({
  plan,
  showSlabCap,
  viewRequest,
  onPick,
  onMove,
  onError,
}) => {
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<IFloor3dEngine | null>(null);
  const theme = useTheme();

  // Колбэки читаются в момент события: смена пропсов движок не пересоздаёт.
  const handlers = useRef({ onPick, onMove, onError });
  useEffect(() => {
    handlers.current = { onPick, onMove, onError };
  });

  useEffect(() => {
    const element = host.current;
    if (element === null) return undefined;
    try {
      engine.current = createFloor3dEngine(element, {
        reducedMotion: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
        onPick: (pick, anchor) => handlers.current.onPick(pick, anchor),
        onMove: () => handlers.current.onMove(),
      });
    } catch {
      handlers.current.onError('Не удалось запустить 3D: в браузере недоступен WebGL.');
      return undefined;
    }
    return () => {
      engine.current?.dispose();
      engine.current = null;
    };
  }, []);

  useEffect(() => {
    engine.current?.setModel(
      plan.prisms.length === 0 ? null : buildFloor3dScene(plan, readFloor3dColors(), { showSlabCap }),
    );
  }, [plan, showSlabCap, theme]);

  useEffect(() => {
    if (viewRequest === null) return;
    if (viewRequest.kind === 'fit') engine.current?.fit();
    else engine.current?.setView(viewRequest.kind);
  }, [viewRequest]);

  return <div ref={host} role="img" aria-label="3D-модель этажа" className="h-full w-full" />;
};
