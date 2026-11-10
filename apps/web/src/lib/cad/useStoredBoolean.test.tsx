import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { useStoredBoolean } from './useStoredBoolean';
import { resetStoredNumbers } from './useStoredNumber';

const KEY = 'quantor.test.flag';

describe('useStoredBoolean', () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetStoredNumbers();
  });

  it('без сохранённого значения берёт значение по умолчанию', () => {
    expect(renderHook(() => useStoredBoolean(KEY, false)).result.current[0]).toBe(false);
    expect(renderHook(() => useStoredBoolean(KEY, true)).result.current[0]).toBe(true);
  });

  it('сохраняет значение и отдаёт его другому подписчику', () => {
    const first = renderHook(() => useStoredBoolean(KEY, false));
    const second = renderHook(() => useStoredBoolean(KEY, false));
    act(() => first.result.current[1](true));
    expect(first.result.current[0]).toBe(true);
    expect(second.result.current[0]).toBe(true);
    expect(window.localStorage.getItem(KEY)).toBe('1');
    act(() => first.result.current[1](false));
    expect(second.result.current[0]).toBe(false);
  });
});
