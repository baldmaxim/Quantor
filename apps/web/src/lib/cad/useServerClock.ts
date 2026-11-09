'use client';

import { useEffect, useState } from 'react';

import { holdElapsed, type IElapsedPeak } from '@/lib/cad/format';

/**
 * Текущее время браузера, обновляемое раз в секунду, пока `active`.
 * Смещение к часам сервера применяется при вычислении (`attemptElapsedSeconds`).
 */
export const useTicker = (active: boolean): number => {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) {
      return undefined;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  return now;
};

/**
 * Таймер попытки без шагов назад: пока она идёт, показ не меньше ранее показанного для `key`.
 * Состояние «потолка» меняется прямо в рендере по сравнению значений (шаблон «значение с прошлого
 * рендера»), без эффекта и без лишнего кадра.
 */
export const useHeldElapsed = (key: string, raw: number | null, running: boolean): number | null => {
  const [peak, setPeak] = useState<IElapsedPeak | null>(null);
  const held = holdElapsed(peak, key, raw, running);
  if (held.peak?.key !== peak?.key || held.peak?.value !== peak?.value) {
    setPeak(held.peak);
  }
  return held.shown;
};
