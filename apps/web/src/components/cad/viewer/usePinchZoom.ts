'use client';

import { useEffect, type RefObject } from 'react';

import type { Camera } from '@/lib/viewer/camera';

/**
 * Щипок двумя пальцами: зум и сдвиг камеры. Просмотрщик сам понимает один указатель (панорама)
 * и колесо; жеста двумя пальцами у него нет, а на телефоне колеса нет.
 *
 * Слушатели нативные и в фазе перехвата, на контейнере вокруг холста: пока идёт щипок, события
 * обоих пальцев до холста не доходят и не превращаются в панораму одним пальцем. Все указатели
 * щипка гасятся до отпускания последнего, иначе оставшийся палец дёрнул бы лист на пройденное
 * расстояние. Камера двигается мимо состояния React (ADR-0004).
 */

interface IPoint {
  x: number;
  y: number;
}

const distance = (a: IPoint, b: IPoint): number => Math.hypot(a.x - b.x, a.y - b.y);
const center = (a: IPoint, b: IPoint): IPoint => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

/** Меньше этого расстояния между пальцами масштаб считать нельзя: деление на почти ноль. */
const MIN_DISTANCE = 8;

export const usePinchZoom = (hostRef: RefObject<HTMLElement | null>, camera: Camera): void => {
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const pointers = new Map<number, IPoint>();
    // Указатели, которых коснулся щипок: их события холст не получает до отпускания.
    const swallowed = new Set<number>();
    let last: { distance: number; center: IPoint } | null = null;

    const pair = (): [IPoint, IPoint] | null => {
      const [first, second] = [...pointers.values()];
      return first && second ? [first, second] : null;
    };

    const relative = (point: IPoint): IPoint => {
      const bounds = host.getBoundingClientRect();
      return { x: point.x - bounds.left, y: point.y - bounds.top };
    };

    const onDown = (event: PointerEvent) => {
      if (event.pointerType === 'mouse') return;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (pointers.size < 2) return;

      for (const id of pointers.keys()) swallowed.add(id);
      const both = pair();
      if (both && last === null) last = { distance: distance(...both), center: center(...both) };
      event.stopPropagation();
    };

    const onMove = (event: PointerEvent) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      if (!swallowed.has(event.pointerId)) return;
      event.stopPropagation();

      const both = pair();
      if (!both || last === null) return;
      const nextDistance = distance(...both);
      const nextCenter = center(...both);
      if (last.distance >= MIN_DISTANCE && nextDistance >= MIN_DISTANCE) {
        camera.zoomAt(relative(nextCenter), nextDistance / last.distance);
      }
      camera.panBy(nextCenter.x - last.center.x, nextCenter.y - last.center.y);
      last = { distance: nextDistance, center: nextCenter };
    };

    const onEnd = (event: PointerEvent) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.delete(event.pointerId);
      if (swallowed.has(event.pointerId)) event.stopPropagation();
      if (pointers.size < 2) last = null;
      if (pointers.size === 0) swallowed.clear();
    };

    host.addEventListener('pointerdown', onDown, true);
    host.addEventListener('pointermove', onMove, true);
    host.addEventListener('pointerup', onEnd, true);
    host.addEventListener('pointercancel', onEnd, true);
    return () => {
      host.removeEventListener('pointerdown', onDown, true);
      host.removeEventListener('pointermove', onMove, true);
      host.removeEventListener('pointerup', onEnd, true);
      host.removeEventListener('pointercancel', onEnd, true);
    };
  }, [hostRef, camera]);
};
