import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { CadPreviewRead } from '@quantor/api-client';

import type { ICadFrame, IPageSize } from '@/lib/cad/frame';

import { useWallSnapIndex } from './useWallSnapIndex';

const FRAME: ICadFrame = { originX: 0, originY: 100, mmPerPt: 1 };
const PAGE: IPageSize = { width: 100, height: 100 };
const PREVIEW = {
  layers: ['01_КОНТУРЫ_СТЕН'],
  paths: [{ closed: true, fill: false, layer: 0, points: [0, 0, 10, 0, 10, 10, 0, 10] }],
} as unknown as CadPreviewRead;

describe('useWallSnapIndex', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('индекс появляется после задачи, а не в рендере; выключен - null', () => {
    const { result, rerender } = renderHook(
      ({ enabled }) => useWallSnapIndex(PREVIEW, FRAME, PAGE, enabled),
      { initialProps: { enabled: false } },
    );
    act(() => void vi.runAllTimers());
    expect(result.current).toBeNull();

    rerender({ enabled: true });
    expect(result.current).toBeNull();
    act(() => void vi.runAllTimers());
    expect(result.current?.vertices).toHaveLength(4);

    // Повторное включение - тот же индекс без пересборки.
    const first = result.current;
    rerender({ enabled: false });
    rerender({ enabled: true });
    expect(result.current).toBe(first);
  });

  it('нет предпросмотра или кадра - null', () => {
    const { result } = renderHook(() => useWallSnapIndex(null, FRAME, PAGE, true));
    act(() => void vi.runAllTimers());
    expect(result.current).toBeNull();
    const noFrame = renderHook(() => useWallSnapIndex(PREVIEW, null, PAGE, true));
    act(() => void vi.runAllTimers());
    expect(noFrame.result.current).toBeNull();
  });
});
