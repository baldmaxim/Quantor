'use client';

import { useCallback, useSyncExternalStore } from 'react';

/**
 * Булев флаг раскладки, который переживает перезагрузку (localStorage).
 *
 * Хранилище может быть недоступно (приватный режим, запрет) - тогда флаг живёт в памяти
 * вкладки, а страница не падает. На сервере и при гидратации значение - `false`: серверная
 * разметка не зависит от браузера, затем React перечитывает хранилище.
 */

const memory = new Map<string, boolean>();
const listeners = new Set<() => void>();

const notify = (): void => {
  for (const listener of listeners) listener();
};

export const readStoredFlag = (key: string): boolean => {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === '1') return true;
    if (raw === '0') return false;
  } catch {
    // хранилище недоступно - берём значение из памяти
  }
  return memory.get(key) ?? false;
};

export const writeStoredFlag = (key: string, value: boolean): void => {
  memory.set(key, value);
  try {
    window.localStorage.setItem(key, value ? '1' : '0');
  } catch {
    // хранилище недоступно - флаг останется в памяти вкладки
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
export const resetStoredFlags = (): void => {
  memory.clear();
  notify();
};

export const useStoredFlag = (key: string): readonly [boolean, (value: boolean) => void] => {
  const value = useSyncExternalStore(
    subscribe,
    () => readStoredFlag(key),
    () => false,
  );
  const set = useCallback((next: boolean) => writeStoredFlag(key, next), [key]);
  return [value, set];
};
