import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { layerVisibilityKey, useCadLayerVisibility } from './useCadLayerVisibility';

const NAMES = ['01_КЛАДКА', '02_МОНОЛИТ', '04_ОСИ'] as const;
const KEY = layerVisibilityKey('job-1', 3);

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('видимость слоёв листа', () => {
  it('по умолчанию ничего не скрыто', () => {
    const { result } = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    expect(result.current.hiddenLayers.size).toBe(0);
    expect(result.current.hiddenCategories.size).toBe(0);
  });

  it('слой скрывается по имени, категория - вместе с ним; выбор пишется в хранилище', () => {
    const { result } = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    act(() => result.current.toggleLayer(0));
    expect([...result.current.hiddenLayers]).toEqual([0]);
    expect([...result.current.hiddenCategories]).toEqual(['masonry']);
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? '{}')).toEqual({
      layers: ['01_КЛАДКА'],
      extra: [],
    });
    act(() => result.current.toggleLayer(0));
    expect(result.current.hiddenLayers.size).toBe(0);
  });

  it('«Плита» и «Перемычки» хранятся вместе со слоями', () => {
    const { result } = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    act(() => result.current.setExtraHidden('slab', true));
    act(() => result.current.setLayersHidden([2], true));
    expect([...result.current.hiddenCategories]).toEqual(['slab']);
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? '{}')).toEqual({
      layers: ['04_ОСИ'],
      extra: ['slab'],
    });
  });

  it('восстанавливается из хранилища и не зависит от порядка слоёв вида', () => {
    window.localStorage.setItem(KEY, JSON.stringify({ layers: ['02_МОНОЛИТ'], extra: ['lintel'] }));
    const reordered = ['04_ОСИ', '02_МОНОЛИТ'];
    const { result } = renderHook(() => useCadLayerVisibility(KEY, reordered));
    expect([...result.current.hiddenLayers]).toEqual([1]);
    expect([...result.current.hiddenCategories].sort()).toEqual(['lintel', 'monolith']);
  });

  it('смена листа читает его собственный выбор', () => {
    const other = layerVisibilityKey('job-1', 4);
    window.localStorage.setItem(other, JSON.stringify({ layers: ['01_КЛАДКА'], extra: [] }));
    const { result, rerender } = renderHook(({ key }) => useCadLayerVisibility(key, NAMES), {
      initialProps: { key: KEY },
    });
    expect(result.current.hiddenLayers.size).toBe(0);
    rerender({ key: other });
    expect([...result.current.hiddenLayers]).toEqual([0]);
  });

  it('битый JSON и чужой формат - ничего не скрыто, без падения', () => {
    window.localStorage.setItem(KEY, '{не json');
    const broken = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    expect(broken.result.current.hiddenLayers.size).toBe(0);

    window.localStorage.setItem(KEY, JSON.stringify({ layers: [1, null, '01_КЛАДКА'], extra: ['x', 'slab'] }));
    const partial = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    expect([...partial.result.current.hiddenLayers]).toEqual([0]);
    expect([...partial.result.current.hiddenCategories].sort()).toEqual(['masonry', 'slab']);

    window.localStorage.setItem(KEY, '42');
    const scalar = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    expect(scalar.result.current.hiddenLayers.size).toBe(0);
  });

  it('хранилище недоступно - выбор живёт в состоянии, страница не падает', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    const { result } = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    act(() => result.current.toggleLayer(1));
    expect([...result.current.hiddenLayers]).toEqual([1]);
  });

  it('вида нет (ключ null) - ничего не пишется', () => {
    const { result } = renderHook(() => useCadLayerVisibility(null, NAMES));
    act(() => result.current.toggleLayer(0));
    expect(window.localStorage.length).toBe(0);
  });
});
