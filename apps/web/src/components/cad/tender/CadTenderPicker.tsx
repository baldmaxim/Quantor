'use client';

import { useEffect, useRef, type FC } from 'react';

import { HIT_TOLERANCE_PX, isClick } from '@/lib/cad/constructions';
import type { Camera } from '@/lib/viewer/camera';
import { placeViewportPage, toNormalizedPoint } from '@/lib/viewer/coordinates';
import type { IMepInfo } from '@/lib/cad/floor3d-mep-info';
import type { ITenderRef } from '@/lib/tender/info';

import { TenderInfoPopover } from './TenderInfoPopover';

export interface ICadTenderPicker {
  readonly camera: Camera;
  /** Размер листа у отрисовщика (pt при масштабе 1). */
  readonly page: { readonly width: number; readonly height: number };
  /** Объект расчёта под нормализованной точкой листа; допуск - в долях ширины листа. */
  readonly hit: (point: { x: number; y: number }, tolerance: number) => ITenderRef | null;
  /** Щелчок: объект под курсором или `null` (пустое место) и точка клика. */
  readonly onPick: (ref: ITenderRef | null, anchor: { x: number; y: number }) => void;
  /** Карточку закрыть (панорама, зум, щелчок вне, Esc); выделение остаётся. */
  readonly onDismiss: () => void;
  /** Плашка выбранного объекта; `null` - закрыта. */
  readonly popover: { readonly info: IMepInfo; readonly anchor: { x: number; y: number } } | null;
}

interface ICadTenderPickerProps extends ICadTenderPicker {
  /** Выбор приостановлен: идёт калибровка масштаба или другой режим, которому нужен щелчок. */
  readonly disabled?: boolean;
}

/** Холст просмотрщика: щелчки считаются только на нём, а не на плавающих окнах поверх. */
const VIEWPORT = '[data-testid="viewport"]';

interface IDown {
  readonly pointerId: number;
  readonly x: number;
  readonly y: number;
}

/**
 * Выбор объекта расчёта щелчком по плану и его плашка. Устроен как `CadConstructionPicker`: ничего не
 * перехватывает, слушает события указателя, всплывающие от холста; щелчок - сдвиг меньше 4 px, больше -
 * это панорама, и плашка закрывается. Движение указателя и камера не проходят через состояние React
 * (ADR-0004).
 */
export const CadTenderPicker: FC<ICadTenderPickerProps> = ({
  camera,
  page,
  hit,
  onPick,
  onDismiss,
  popover,
  disabled = false,
}) => {
  const marker = useRef<HTMLDivElement>(null);

  const latest = useRef({ page, hit, onPick, onDismiss, disabled });
  useEffect(() => {
    latest.current = { page, hit, onPick, onDismiss, disabled };
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
      current.onPick(current.hit(point, tolerance), { x: event.clientX, y: event.clientY });
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
      latest.current.onDismiss();
    };
  }, [camera]);

  return (
    <>
      <div ref={marker} aria-hidden="true" className="pointer-events-none absolute size-0" />
      {popover !== null && !disabled && (
        <TenderInfoPopover info={popover.info} anchor={popover.anchor} onClose={onDismiss} />
      )}
    </>
  );
};
