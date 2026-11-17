'use client';

import { useEffect, useRef, useState, type FC } from 'react';

import type { IModelElement } from '@/lib/model/model-elements';
import type { IModelPartInput } from '@/lib/model/model-scene';
import { createSpeckleModelViewer, type ISpeckleModelViewer } from '@/lib/model/model-speckle';

interface IModelSpeckleCanvasProps {
  readonly parts: readonly IModelPartInput[];
  /** Свойства элементов частей: без них геометрия рисуется, но фильтры и панель пусты. */
  readonly elements: ReadonlyMap<string, IModelElement> | null;
  /** Дисциплины, спрятанные в панели слоёв. */
  readonly hiddenDisciplines: ReadonlySet<string>;
  readonly selectedId: string | null;
  readonly colorByCategory: boolean;
  /** Показать только этажи с номером не выше этого; `null` - все (режим «весь дом»). */
  readonly maxLevel?: number | null;
  /** Разнос этажей по вертикали, метров на этаж. */
  readonly storeyOffset?: number;
  /** Команда «Вписать»: счётчик, чтобы повторное нажатие не терялось. */
  readonly fitSeq: number;
  readonly onPick: (id: string | null, group: string | null) => void;
  /** Просмотрщик не запустился (нет WebGL) или часть не разобрана. */
  readonly onError: (message: string) => void;
}

/**
 * Холст 3D на просмотрщике Speckle: владеет им и освобождает при размонтировании. Библиотека
 * подгружается при первом показе; части, видимость дисциплин, выбор и раскраска меняются
 * отдельными эффектами, камеру без нужды не сбрасывая.
 */
export const ModelSpeckleCanvas: FC<IModelSpeckleCanvasProps> = ({
  parts,
  elements,
  hiddenDisciplines,
  selectedId,
  colorByCategory,
  maxLevel = null,
  storeyOffset = 0,
  fitSeq,
  onPick,
  onError,
}) => {
  const host = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<ISpeckleModelViewer | null>(null);
  const handlers = useRef({ onPick, onError });
  const state = useRef({ parts, hiddenDisciplines, selectedId, colorByCategory });
  useEffect(() => {
    handlers.current = { onPick, onError };
    state.current = { parts, hiddenDisciplines, selectedId, colorByCategory };
  });
  // Состав содержимого - по ключам частей (sha256), а не по идентичности массива: родитель
  // собирает массив заново на каждый рендер, и без этого любой щелчок перезагружал бы модель.
  const partsKey = parts.map((part) => part.key).join('|');
  const disciplinesKey = [...new Set(parts.map((part) => part.discipline))].sort().join('|');

  useEffect(() => {
    const element = host.current;
    if (element === null) return undefined;
    let cancelled = false;
    let created: ISpeckleModelViewer | null = null;
    createSpeckleModelViewer(element, {
      onPick: (id, group) => handlers.current.onPick(id, group),
      onError: (message) => handlers.current.onError(message),
    })
      .then((viewer) => {
        if (cancelled) {
          viewer.dispose();
          return;
        }
        created = viewer;
        setView(viewer);
      })
      .catch(() => {
        if (!cancelled) {
          handlers.current.onError('Не удалось запустить 3D: в браузере недоступен WebGL.');
        }
      });
    return () => {
      cancelled = true;
      created?.dispose();
      setView(null);
    };
  }, []);

  useEffect(() => {
    if (view === null) return;
    const current = state.current;
    for (const code of new Set(current.parts.map((part) => part.discipline))) {
      view.setDisciplineVisible(code, !current.hiddenDisciplines.has(code));
    }
    view.setColorByCategory(current.colorByCategory);
    void view.setContent(current.parts, elements).then(() => view.select(state.current.selectedId));
  }, [view, partsKey, elements]);

  useEffect(() => {
    if (view === null) return;
    for (const code of disciplinesKey === '' ? [] : disciplinesKey.split('|')) {
      view.setDisciplineVisible(code, !hiddenDisciplines.has(code));
    }
  }, [view, hiddenDisciplines, disciplinesKey]);

  useEffect(() => {
    view?.select(selectedId);
  }, [view, selectedId]);

  useEffect(() => {
    view?.setColorByCategory(colorByCategory);
  }, [view, colorByCategory]);

  useEffect(() => {
    view?.setMaxLevel(maxLevel);
  }, [view, maxLevel, partsKey]);

  useEffect(() => {
    view?.setStoreyOffset(storeyOffset);
  }, [view, storeyOffset, partsKey]);

  useEffect(() => {
    if (fitSeq > 0) view?.fit();
  }, [view, fitSeq]);

  return (
    <div
      ref={host}
      role="img"
      aria-label="Этаж модели в объёме. Вращение — перетаскиванием, масштаб — колесом, панорама — правой кнопкой."
      className="relative h-full min-h-[320px] w-full cursor-grab overflow-hidden active:cursor-grabbing"
    />
  );
};
