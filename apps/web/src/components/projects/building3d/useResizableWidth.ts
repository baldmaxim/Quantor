'use client';

import { useState } from 'react';

export interface IResizableWidthOptions {
  readonly min: number;
  readonly max: number;
  readonly initial: number;
}

/** Ширина в границах `[min, max]`; не число - `fallback`. */
export const clampWidth = (value: number, min: number, max: number, fallback: number): number =>
  Number.isFinite(value) ? Math.min(Math.max(Math.round(value), min), max) : fallback;

const readStored = (key: string, options: IResizableWidthOptions): number => {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? options.initial : clampWidth(Number(raw), options.min, options.max, options.initial);
  } catch {
    // Хранилище закрыто (приватный режим, запрет): ширина по умолчанию.
    return options.initial;
  }
};

/**
 * Ширина панели, которую пользователь меняет разделителем: хранится в `localStorage` под `storageKey`,
 * читается один раз при создании (просмотрщик грузится только в браузере). Сбой хранилища ширину не ломает.
 */
export const useResizableWidth = (
  storageKey: string,
  options: IResizableWidthOptions,
): readonly [number, (next: number) => void] => {
  const [width, setWidth] = useState(() => readStored(storageKey, options));

  const update = (next: number): void => {
    const value = clampWidth(next, options.min, options.max, options.initial);
    setWidth(value);
    try {
      window.localStorage.setItem(storageKey, String(value));
    } catch {
      // Не сохранилось - ширина действует до перезагрузки.
    }
  };

  return [width, update];
};
