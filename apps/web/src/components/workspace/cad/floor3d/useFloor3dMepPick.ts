'use client';

import { useCallback, useState, type RefObject } from 'react';

import { mepInfoOf, type IMepInfo } from '@/lib/cad/floor3d-mep-info';
import { sameMepPick, type IMepPick } from '@/lib/cad/floor3d-mep-pick';

import type { ICadFloor3dRoutes } from './CadFloor3dCanvas';

/**
 * Выбор трассы или элемента ВИС в 3D-виде этажа: свой вид выбора, не конструкция. Выбор привязан к
 * прочитанным трассам: после их перечитывания индексы устарели, и выбор считается снятым. Плашка
 * у курсора уходит при движении камеры, выбор (подсветка) остаётся. Данные - те же, что рисует сцена
 * (механика и ЭОМ/СС одним списком): индекс выбора указывает в них.
 */

interface IMepPopup {
  readonly anchor: { readonly x: number; readonly y: number };
  readonly bounds: { readonly width: number; readonly height: number };
}

interface IMepState {
  readonly pick: IMepPick;
  readonly data: ICadFloor3dRoutes;
  readonly popup: IMepPopup | null;
}

export interface IFloor3dMepPick {
  /** Выбранная трасса или элемент; `null` - выбора нет. */
  readonly pick: IMepPick | null;
  /** Содержимое плашки; `null` - плашки нет (закрыта движением камеры или выбор снят). */
  readonly info: IMepInfo | null;
  readonly popup: IMepPopup | null;
  /** Этот объект уже выбран: повторный клик по нему снимает выбор. */
  readonly isSelected: (pick: IMepPick) => boolean;
  readonly select: (pick: IMepPick, anchor: { x: number; y: number }) => void;
  readonly clear: () => void;
  /** Камера пошла: плашка закрывается, выделение остаётся. */
  readonly hidePopup: () => void;
}

export const useFloor3dMepPick = (
  routesData: ICadFloor3dRoutes | null,
  stage: RefObject<HTMLElement | null>,
): IFloor3dMepPick => {
  const [state, setState] = useState<IMepState | null>(null);
  const live = state !== null && state.data === routesData ? state : null;
  const clear = useCallback(() => setState(null), []);
  const hidePopup = useCallback(
    () => setState((current) => (current === null || current.popup === null ? current : { ...current, popup: null })),
    [],
  );
  return {
    pick: live?.pick ?? null,
    info: live?.popup && routesData !== null ? mepInfoOf(live.pick, routesData) : null,
    popup: live?.popup ?? null,
    isSelected: (pick) => sameMepPick(live?.pick ?? null, pick),
    select: (pick, anchor) => {
      if (routesData === null) return;
      const rect = stage.current?.getBoundingClientRect();
      setState({
        pick,
        data: routesData,
        popup: rect ? { anchor, bounds: { width: rect.width, height: rect.height } } : null,
      });
    },
    clear,
    hidePopup,
  };
};
