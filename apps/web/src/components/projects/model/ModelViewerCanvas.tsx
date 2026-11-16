'use client';

import { useEffect, useRef, type FC } from 'react';

import {
  createModelViewer,
  type IModelPartInput,
  type IModelViewer,
  type IModelViewerColors,
} from '@/lib/model/model-scene';
import { useTheme } from '@/lib/theme';

interface IModelViewerCanvasProps {
  readonly parts: readonly IModelPartInput[];
  /** Дисциплины, спрятанные в панели слоёв. */
  readonly hiddenDisciplines: ReadonlySet<string>;
  readonly selectedId: string | null;
  /** Команда «Вписать»: счётчик, чтобы повторное нажатие не терялось. */
  readonly fitSeq: number;
  readonly onPick: (id: string | null) => void;
  /** Холст создать не удалось (нет WebGL) или часть не разобрана. */
  readonly onError: (message: string) => void;
}

const FALLBACK_COLOR = 'gray';

const readColors = (): IModelViewerColors => {
  if (typeof document === 'undefined') {
    return { accent: FALLBACK_COLOR, background: FALLBACK_COLOR };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return { accent: token('--accent'), background: token('--bg') };
};

const reducedMotion = (): boolean =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * Холст 3D этажа модели: владеет renderer'ом и освобождает его при размонтировании. Части GLB,
 * видимость дисциплин, выбор и цвета темы меняются отдельными эффектами, камеру не сбрасывая.
 */
export const ModelViewerCanvas: FC<IModelViewerCanvasProps> = ({
  parts,
  hiddenDisciplines,
  selectedId,
  fitSeq,
  onPick,
  onError,
}) => {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<IModelViewer | null>(null);
  const theme = useTheme();
  const handlers = useRef({ onPick, onError });
  const state = useRef({ hiddenDisciplines, selectedId });
  useEffect(() => {
    handlers.current = { onPick, onError };
    state.current = { hiddenDisciplines, selectedId };
  });

  useEffect(() => {
    const element = host.current;
    if (element === null) return undefined;
    try {
      view.current = createModelViewer(element, {
        reducedMotion: reducedMotion(),
        colors: readColors(),
        onPick: (id) => handlers.current.onPick(id),
        onPartError: () => handlers.current.onError('Часть модели не удалось разобрать.'),
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
    const current = view.current;
    if (current === null) return;
    for (const part of parts) {
      current.setDisciplineVisible(
        part.discipline,
        !state.current.hiddenDisciplines.has(part.discipline),
      );
    }
    current.setParts(parts);
    current.select(state.current.selectedId);
  }, [parts]);

  useEffect(() => {
    const current = view.current;
    if (current === null) return;
    for (const part of parts) {
      current.setDisciplineVisible(part.discipline, !hiddenDisciplines.has(part.discipline));
    }
  }, [hiddenDisciplines, parts]);

  useEffect(() => {
    view.current?.select(selectedId);
  }, [selectedId]);

  useEffect(() => {
    view.current?.setColors(readColors());
  }, [theme]);

  useEffect(() => {
    if (fitSeq > 0) view.current?.fit();
  }, [fitSeq]);

  return (
    <div
      ref={host}
      role="img"
      aria-label="Этаж модели в объёме. Вращение — перетаскиванием, масштаб — колесом, панорама — правой кнопкой."
      className="relative h-full min-h-[320px] w-full cursor-grab overflow-hidden active:cursor-grabbing"
    />
  );
};
