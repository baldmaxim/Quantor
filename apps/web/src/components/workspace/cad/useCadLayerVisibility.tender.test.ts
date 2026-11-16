import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { hiddenCalcIds, tenderLayerKey } from '@/lib/tender/view-key';

import { layerVisibilityKey, useCadLayerVisibility } from './useCadLayerVisibility';

const NAMES = ['01_КЛАДКА', '04_ОСИ'] as const;
const KEY = layerVisibilityKey('rev-1', 3);

beforeEach(() => {
  window.localStorage.clear();
});

describe('видимость расчётов TENDER в слоях листа', () => {
  it('по умолчанию расчёты включены: скрытых нет', () => {
    const { result } = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    expect(hiddenCalcIds(result.current.hiddenLayerNames).size).toBe(0);
  });

  it('расчёт скрывается по ключу tender:<calc_id> и пишется в то же хранилище', () => {
    const { result } = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    act(() => result.current.setNamesHidden([tenderLayerKey('c1')], true));
    expect([...hiddenCalcIds(result.current.hiddenLayerNames)]).toEqual(['c1']);
    expect(JSON.parse(window.localStorage.getItem(KEY) ?? '{}')).toEqual({
      layers: ['tender:c1'],
      extra: [],
    });
    act(() => result.current.setNamesHidden([tenderLayerKey('c1')], false));
    expect(hiddenCalcIds(result.current.hiddenLayerNames).size).toBe(0);
  });

  it('слои DXF и расчёты не мешают друг другу; выбор переживает перезагрузку (общий для 2D и 3D)', () => {
    const first = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    act(() => first.result.current.toggleLayer(1));
    act(() => first.result.current.setNamesHidden([tenderLayerKey('c2')], true));
    // 3D и план читают один ключ: новый хук видит оба выбора.
    const second = renderHook(() => useCadLayerVisibility(KEY, NAMES));
    expect([...second.result.current.hiddenLayers]).toEqual([1]);
    expect([...hiddenCalcIds(second.result.current.hiddenLayerNames)]).toEqual(['c2']);
    act(() => second.result.current.toggleLayer(1));
    expect([...hiddenCalcIds(second.result.current.hiddenLayerNames)]).toEqual(['c2']);
  });
});
