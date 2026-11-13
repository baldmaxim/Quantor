import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { clampWidth, useResizableWidth } from './useResizableWidth';

const OPTIONS = { min: 240, max: 640, initial: 320 } as const;

beforeEach(() => window.localStorage.clear());

describe('ширина панели', () => {
  it('границы и мусор', () => {
    expect(clampWidth(100, 240, 640, 320)).toBe(240);
    expect(clampWidth(900, 240, 640, 320)).toBe(640);
    expect(clampWidth(400.4, 240, 640, 320)).toBe(400);
    expect(clampWidth(Number.NaN, 240, 640, 320)).toBe(320);
  });

  it('по умолчанию 320; сохранённая ширина читается и ограничивается', () => {
    expect(renderHook(() => useResizableWidth('k', OPTIONS)).result.current[0]).toBe(320);
    window.localStorage.setItem('k', '500');
    expect(renderHook(() => useResizableWidth('k', OPTIONS)).result.current[0]).toBe(500);
    window.localStorage.setItem('k', '9999');
    expect(renderHook(() => useResizableWidth('k', OPTIONS)).result.current[0]).toBe(640);
    window.localStorage.setItem('k', 'abc');
    expect(renderHook(() => useResizableWidth('k', OPTIONS)).result.current[0]).toBe(320);
  });

  it('новая ширина ограничивается и сохраняется', () => {
    const { result } = renderHook(() => useResizableWidth('k', OPTIONS));
    act(() => result.current[1](700));
    expect(result.current[0]).toBe(640);
    expect(window.localStorage.getItem('k')).toBe('640');
  });
});
