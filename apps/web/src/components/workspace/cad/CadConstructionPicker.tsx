'use client';

import { useEffect, useRef, type FC } from 'react';

import { HIT_TOLERANCE_PX, isClick } from '@/lib/cad/constructions';
import { placeViewportPage, toNormalizedPoint } from '@/lib/viewer/coordinates';

import { ConstructionPopover } from './ConstructionPopover';
import type { IWorkspaceCadConstructionPicker } from './types';

interface ICadConstructionPickerProps extends IWorkspaceCadConstructionPicker {
  /** Выбор приостановлен: идёт калибровка масштаба или другой режим, которому нужен щелчок. */
  disabled?: boolean;
}

/** Холст просмотрщика: щелчки считаются только на нём, а не на плавающих окнах поверх. */
const VIEWPORT = '[data-testid="viewport"]';

interface IDown {
  readonly pointerId: number;
  readonly x: number;
  readonly y: number;
}

/**
 * Выбор конструкции щелчком по холсту и её карточка (ADR-0038).
 *
 * Компонент ничего не перехватывает: он лежит рядом с холстом в одном контейнере и слушает
 * события указателя, которые всплывают от холста (`pointer-events-none`). Щелчок - смещение
 * между нажатием и отпусканием меньше 4 px; больше - это панорама, и карточка закрывается. Колесо и
 * любое движение камеры закрывают карточку тоже. Попадание - через пространственный индекс; ни
 * движение указателя, ни камера не проходят через состояние React (ADR-0004).
 */
export const CadConstructionPicker: FC<ICadConstructionPickerProps> = ({
  camera,
  page,
  index,
  onPick,
  onDismiss,
  popover,
  disabled = false,
}) => {
  const marker = useRef<HTMLDivElement>(null);

  // Свежие значения без переподписки на каждый рендер.
  const latest = useRef({ page, index, onPick, onDismiss, disabled });
  useEffect(() => {
    latest.current = { page, index, onPick, onDismiss, disabled };
  });

  useEffect(() => {
    const host = marker.current?.parentElement;
    if (!host) return undefined;
    let down: IDown | null = null;

    const viewportOf = (event: Event): Element | null =>
      event.target instanceof Element ? event.target.closest(VIEWPORT) : null;

    const onPointerDown = (event: PointerEvent) => {
      if (event.button !== 0 || viewportOf(event) === null) return;
      down = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    };

    const onPointerUp = (event: PointerEvent) => {
      const start = down;
      down = null;
      const view = viewportOf(event);
      if (start === null || start.pointerId !== event.pointerId || view === null) return;
      const current = latest.current;
      if (current.disabled) return;
      if (!isClick(start, { x: event.clientX, y: event.clientY })) {
        current.onDismiss();
        return;
      }
      const bounds = view.getBoundingClientRect();
      const placement = placeViewportPage(current.page, camera.getState());
      const point = toNormalizedPoint(
        { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
        placement,
      );
      const tolerance = placement.width > 0 ? HIT_TOLERANCE_PX / placement.width : 0;
      current.onPick(current.index.hit(point, tolerance), { x: event.clientX, y: event.clientY });
    };

    const onPointerCancel = () => {
      down = null;
    };
    const dismiss = () => latest.current.onDismiss();

    host.addEventListener('pointerdown', onPointerDown);
    host.addEventListener('pointerup', onPointerUp);
    host.addEventListener('pointercancel', onPointerCancel);
    host.addEventListener('wheel', dismiss, { passive: true });
    const unsubscribe = camera.subscribe(dismiss);
    return () => {
      host.removeEventListener('pointerdown', onPointerDown);
      host.removeEventListener('pointerup', onPointerUp);
      host.removeEventListener('pointercancel', onPointerCancel);
      host.removeEventListener('wheel', dismiss);
      unsubscribe();
      // Выбор выключили (слой скрыт, другая вкладка): карточка не должна вернуться позже.
      latest.current.onDismiss();
    };
  }, [camera]);

  return (
    <>
      <div ref={marker} aria-hidden="true" className="pointer-events-none absolute size-0" />
      {popover !== null && !disabled && <ConstructionPopover {...popover} />}
    </>
  );
};
