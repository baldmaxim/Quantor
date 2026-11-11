'use client';

import { useEffect, useRef, useState, type FC } from 'react';

import {
  createFloor3dEngine,
  type Floor3dViewKind,
  type IFloor3dEngine,
  type IFloor3dMeasureState,
  type IFloor3dSnapState,
} from '@/lib/cad/floor3d-engine';
import { highlightOf, type IFloor3dPlan } from '@/lib/cad/floor3d-geometry';
import { buildFloor3dScene, readFloor3dColors, type IFloor3dPick } from '@/lib/cad/floor3d-scene';
import { useTheme } from '@/lib/theme';

import { CadFloor3dMeasureLabel } from './CadFloor3dMeasureLabel';
import { CadFloor3dSnapLabel } from './CadFloor3dSnapLabel';

/** Запрос камеры: `seq` меняется при каждом нажатии, чтобы повторная команда не терялась. */
export interface IFloor3dViewRequest {
  readonly kind: Floor3dViewKind | 'fit';
  readonly seq: number;
}

interface ICadFloor3dCanvasProps {
  readonly plan: IFloor3dPlan;
  readonly showSlabCap: boolean;
  readonly viewRequest: IFloor3dViewRequest | null;
  /** Выбранный элемент: подсвечивается оверлеем. */
  readonly selected: IFloor3dPick | null;
  /** Режим измерения: клики ставят точки, элемент не выбирается. */
  readonly measuring: boolean;
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
  selected,
  measuring,
  onPick,
  onMove,
  onError,
}) => {
  const host = useRef<HTMLDivElement>(null);
  const engine = useRef<IFloor3dEngine | null>(null);
  const theme = useTheme();
  const [measure, setMeasure] = useState<IFloor3dMeasureState | null>(null);
  const [snap, setSnap] = useState<IFloor3dSnapState | null>(null);

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
        onMeasure: setMeasure,
        onSnap: setSnap,
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

  // Выделение накладывается после пересборки модели (эффект выше) и при смене выбора.
  useEffect(() => {
    engine.current?.setHighlight(highlightOf(plan, selected));
  }, [plan, showSlabCap, theme, selected]);

  useEffect(() => {
    engine.current?.setMeasuring(measuring);
  }, [measuring]);

  useEffect(() => {
    if (viewRequest === null) return;
    if (viewRequest.kind === 'fit') engine.current?.fit();
    else engine.current?.setView(viewRequest.kind);
  }, [viewRequest]);

  const [first, second] = measure?.points ?? [];
  return (
    <div className="relative h-full w-full">
      <div ref={host} role="img" aria-label="3D-модель этажа" className="h-full w-full" />
      {measuring && first !== undefined && second !== undefined && measure?.mid && (
        <CadFloor3dMeasureLabel a={first} b={second} center={plan.center} at={measure.mid} />
      )}
      {measuring && snap !== null && <CadFloor3dSnapLabel snap={snap} />}
    </div>
  );
};
