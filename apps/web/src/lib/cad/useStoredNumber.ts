'use client';

import { useCallback, useSyncExternalStore } from 'react';

/**
 * Число, которое переживает перезагрузку (localStorage): непрозрачность подложки и т. п.
 *
 * Хранилище может быть недоступно (приватный режим, запрет) - тогда значение живёт в памяти
 * вкладки, а страница не падает. На сервере и при гидратации берётся значение по умолчанию.
 */

const memory = new Map<string, number>();
const listeners = new Set<() => void>();

const notify = (): void => {
  for (const listener of listeners) listener();
};

export const readStoredNumber = (key: string, fallback: number): number => {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw !== null) {
      const value = Number(raw);
      if (raw.trim() !== '' && Number.isFinite(value)) return value;
    }
  } catch {
    // хранилище недоступно - берём значение из памяти
  }
  return memory.get(key) ?? fallback;
};

export const writeStoredNumber = (key: string, value: number): void => {
  memory.set(key, value);
  try {
    window.localStorage.setItem(key, String(value));
  } catch {
    // хранилище недоступно - значение останется в памяти вкладки
  }
  notify();
};

const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  // Изменение в соседней вкладке.
  window.addEventListener('storage', listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', listener);
  };
};

/** Сбросить память (для тестов). */
export const resetStoredNumbers = (): void => {
  memory.clear();
  notify();
};

export const useStoredNumber = (
  key: string,
  fallback: number,
): readonly [number, (value: number) => void] => {
  const value = useSyncExternalStore(
    subscribe,
    () => readStoredNumber(key, fallback),
    () => fallback,
  );
  const set = useCallback((next: number) => writeStoredNumber(key, next), [key]);
  return [value, set];
};
