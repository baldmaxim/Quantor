'use client';

import { useCallback } from 'react';

import { useStoredNumber } from './useStoredNumber';

/**
 * Флаг, который переживает перезагрузку: тот же механизм, что и у `useStoredNumber`
 * (localStorage с запасом в памяти вкладки), значение хранится как 1 или 0.
 */
export const useStoredBoolean = (
  key: string,
  fallback: boolean,
): readonly [boolean, (value: boolean) => void] => {
  const [raw, setRaw] = useStoredNumber(key, fallback ? 1 : 0);
  const set = useCallback((next: boolean) => setRaw(next ? 1 : 0), [setRaw]);
  return [raw !== 0, set];
};
