'use client';

import type { CadBuilding3dFloorRead, CadBuilding3dGroupRead } from '@quantor/api-client';
import { useEffect, useMemo, useRef, useState, type FC } from 'react';

import { describeFloor, floorKey } from '@/lib/cad/building3d-geometry';
import { buildViewerPlan } from '@/lib/cad/building-viewer-geometry';
import { readBuildingViewerColors } from '@/lib/cad/building-viewer-colors';
import { buildAllGroupsPlan } from '@/lib/cad/building-viewer-layout';
import { createBuildingViewer, type IBuildingViewer } from '@/lib/cad/building-viewer-scene';
import { useTheme } from '@/lib/theme';

interface IBuildingViewerCanvasProps {
  readonly floors: readonly CadBuilding3dFloorRead[];
  /** Режим «Весь объект»: группы, расставленные в один ряд; `null` - одно здание. */
  readonly allGroups: readonly CadBuilding3dGroupRead[] | null;
  readonly selectedKey: string | null;
  /** Наведённый этаж (мышь или список): подсвечивается. */
  readonly hoverKey: string | null;
  /** Выбранная конструкция выбранного этажа (`id` из walls.json). */
  readonly constructionId: string | null;
  readonly exploded: boolean;
  /** Команда «Вписать»: счётчик, чтобы повторное нажатие не терялось. */
  readonly fitSeq: number;
  readonly onHover: (key: string | null) => void;
  readonly onSelect: (key: string) => void;
  /** Конструкция выбрана щелчком по стене; `null` - выбор снят щелчком в пустоту. */
  readonly onSelectConstruction: (id: string | null) => void;
  readonly onOpenDetail: (key: string) => void;
  /** Холст создать не удалось (нет WebGL). */
  readonly onError: (message: string) => void;
}

const reducedMotion = (): boolean =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * Холст просмотрщика объекта: владеет renderer'ом и освобождает его при размонтировании. Модель
 * пересобирается при смене набора этажей, цвета темы меняются без пересборки, подсветка и
 * разнесение - отдельными эффектами. Подсказка у курсора показывается здесь же.
 */
export const BuildingViewerCanvas: FC<IBuildingViewerCanvasProps> = ({
  floors,
  allGroups,
  selectedKey,
  hoverKey,
  constructionId,
  exploded,
  fitSeq,
  onHover,
  onSelect,
  onSelectConstruction,
  onOpenDetail,
  onError,
}) => {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<IBuildingViewer | null>(null);
  const theme = useTheme();
  const plan = useMemo(
    () => (allGroups === null ? buildViewerPlan(floors) : buildAllGroupsPlan(floors, allGroups)),
    [floors, allGroups],
  );
  const byKey = useMemo(() => new Map(floors.map((floor) => [floorKey(floor), floor])), [floors]);
  const [tip, setTip] = useState<{ key: string; x: number; y: number } | null>(null);

  // Колбэки читаются в момент события: смена пропсов движок не пересоздаёт.
  const handlers = useRef({ onHover, onSelect, onSelectConstruction, onOpenDetail, onError });
  const state = useRef({ selectedKey, hoverKey, constructionId, exploded });
  useEffect(() => {
    handlers.current = { onHover, onSelect, onSelectConstruction, onOpenDetail, onError };
    state.current = { selectedKey, hoverKey, constructionId, exploded };
  });

  useEffect(() => {
    const element = host.current;
    if (element === null) return undefined;
    try {
      view.current = createBuildingViewer(element, {
        reducedMotion: reducedMotion(),
        onHover: (key, anchor) => {
          handlers.current.onHover(key);
          setTip(key !== null && anchor !== null ? { key, ...anchor } : null);
        },
        onSelect: (key) => handlers.current.onSelect(key),
        onSelectConstruction: (id) => handlers.current.onSelectConstruction(id),
        onOpenDetail: (key) => handlers.current.onOpenDetail(key),
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

  // Модель: только при смене данных; тема красит заново, не сбрасывая камеру.
  useEffect(() => {
    const current = view.current;
    if (current === null) return;
    current.setPlan(plan, readBuildingViewerColors());
    current.setStyle(state.current.selectedKey, state.current.hoverKey, state.current.constructionId);
    current.setExploded(state.current.exploded);
  }, [plan]);

  useEffect(() => {
    view.current?.setColors(readBuildingViewerColors());
  }, [theme]);

  useEffect(() => {
    view.current?.setStyle(selectedKey, hoverKey, constructionId);
  }, [selectedKey, hoverKey, constructionId]);

  useEffect(() => {
    view.current?.setExploded(exploded);
  }, [exploded]);

  useEffect(() => {
    if (fitSeq > 0) view.current?.fit();
  }, [fitSeq]);

  const tipFloor = tip ? (byKey.get(tip.key) ?? null) : null;

  return (
    <>
      <div
        ref={host}
        role="img"
        aria-label="Здание: этажи в объёме. Вращение - перетаскиванием, масштаб - колесом или щипком. Щелчок по этажу выбирает его, по стене выбранного этажа - конструкцию"
        className="relative h-full w-full cursor-grab overflow-hidden active:cursor-grabbing"
      />
      {tipFloor && tip && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 max-w-[220px] rounded-[var(--radius-sm)] border border-border bg-surface px-[var(--s-3)] py-[var(--s-2)] text-xs text-text"
          style={{ left: Math.max(0, tip.x + 12), top: Math.max(0, tip.y + 12) }}
        >
          {describeFloor(tipFloor)}
        </div>
      )}
    </>
  );
};
