import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  readStoredNumber,
  resetStoredNumbers,
  useStoredNumber,
  writeStoredNumber,
} from './useStoredNumber';

const KEY = 'test:number';

beforeEach(() => {
  window.localStorage.clear();
  resetStoredNumbers();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useStoredNumber', () => {
  it('нет значения - по умолчанию', () => {
    const { result } = renderHook(() => useStoredNumber(KEY, 0.4));
    expect(result.current[0]).toBe(0.4);
  });

  it('читает сохранённое и пишет изменения в localStorage', () => {
    window.localStorage.setItem(KEY, '0.7');
    const { result } = renderHook(() => useStoredNumber(KEY, 0.4));
    expect(result.current[0]).toBe(0.7);

    act(() => result.current[1](0.25));
    expect(result.current[0]).toBe(0.25);
    expect(window.localStorage.getItem(KEY)).toBe('0.25');
  });

  it('мусор в хранилище не число - значение по умолчанию', () => {
    window.localStorage.setItem(KEY, 'abc');
    expect(readStoredNumber(KEY, 0.4)).toBe(0.4);
    window.localStorage.setItem(KEY, '');
    expect(readStoredNumber(KEY, 0.4)).toBe(0.4);
  });

  it('два потребителя одного ключа видят одно значение', () => {
    const first = renderHook(() => useStoredNumber(KEY, 0.4));
    const second = renderHook(() => useStoredNumber(KEY, 0.4));
    act(() => first.result.current[1](0.9));
    expect(second.result.current[0]).toBe(0.9);
  });

  it('хранилище недоступно: значение живёт в памяти, ошибок нет', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    expect(readStoredNumber(KEY, 0.4)).toBe(0.4);
    expect(() => writeStoredNumber(KEY, 0.8)).not.toThrow();
    expect(readStoredNumber(KEY, 0.4)).toBe(0.8);
  });
});
