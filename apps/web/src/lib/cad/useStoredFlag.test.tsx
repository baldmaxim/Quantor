import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { readStoredFlag, resetStoredFlags, useStoredFlag, writeStoredFlag } from './useStoredFlag';

const KEY = 'test:flag';

beforeEach(() => {
  window.localStorage.clear();
  resetStoredFlags();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useStoredFlag', () => {
  it('по умолчанию выключен', () => {
    const { result } = renderHook(() => useStoredFlag(KEY));
    expect(result.current[0]).toBe(false);
  });

  it('читает сохранённое значение и пишет изменения в localStorage', () => {
    window.localStorage.setItem(KEY, '1');
    const { result } = renderHook(() => useStoredFlag(KEY));
    expect(result.current[0]).toBe(true);

    act(() => result.current[1](false));
    expect(result.current[0]).toBe(false);
    expect(window.localStorage.getItem(KEY)).toBe('0');
  });

  it('два потребителя одного ключа видят одно значение', () => {
    const first = renderHook(() => useStoredFlag(KEY));
    const second = renderHook(() => useStoredFlag(KEY));
    act(() => first.result.current[1](true));
    expect(second.result.current[0]).toBe(true);
  });

  it('хранилище недоступно: флаг живёт в памяти, ошибок нет', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    expect(readStoredFlag(KEY)).toBe(false);
    expect(() => writeStoredFlag(KEY, true)).not.toThrow();
    expect(readStoredFlag(KEY)).toBe(true);
  });
});
