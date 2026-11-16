import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { layer } from '@/lib/tender/fixtures';
import { Camera } from '@/lib/viewer/camera';

const state = vi.hoisted(() => ({ layers: [] as unknown[] }));

vi.mock('@/lib/tender/layers', () => ({
  useTenderViewLayers: () => ({ data: { layers: state.layers } }),
}));

import { tenderLayerKey } from '@/lib/tender/view-key';

import { useWorkspaceCadTender } from './useWorkspaceCadTender';

const camera = new Camera();
const FRAME = { originX: 100, originY: 700, mmPerPt: 10 };

const visibilityOf = (hidden: string[]) => {
  const setNamesHidden = vi.fn();
  return { visibility: { hiddenLayerNames: new Set(hidden), setNamesHidden }, setNamesHidden };
};

const mount = (hidden: string[], patch: { tenderParam?: string | null; shown?: boolean } = {}) => {
  const { visibility, setNamesHidden } = visibilityOf(hidden);
  const hook = renderHook(() =>
    useWorkspaceCadTender({
      projectId: 'p1',
      revisionId: 'r1',
      pageIndex: 3,
      view: 0,
      frame: FRAME,
      pageSize: { width: 1000, height: 800 },
      camera,
      visibility,
      shown: patch.shown ?? true,
      tenderParam: patch.tenderParam ?? null,
    }),
  );
  return { ...hook, setNamesHidden };
};

beforeEach(() => {
  state.layers = [layer(), layer({ calc_id: 'c2', version_id: 'v2', title: 'Вентиляция', system: 'ventilation' })];
});

describe('слой «Расчёты» на плане', () => {
  it('строка на версию; по умолчанию все включены, слой рисуется', () => {
    const { result } = mount([]);
    expect(result.current.layers?.items.map((item) => [item.calcId, item.visible])).toEqual([
      ['c1', true],
      ['c2', true],
    ]);
    expect(result.current.painter(true)).not.toBeNull();
    expect(result.current.picker).not.toBeNull();
  });

  it('переключатель пишет ключи tender:<calc_id> в общее хранилище видимости', () => {
    const { result, setNamesHidden } = mount([]);
    act(() => result.current.layers?.onSetVisible(['c1'], false));
    expect(setNamesHidden).toHaveBeenCalledWith([tenderLayerKey('c1')], true);
  });

  it('все расчёты скрыты - рисовать нечего, выбора нет', () => {
    const { result } = mount([tenderLayerKey('c1'), tenderLayerKey('c2')]);
    expect(result.current.painter(true)).toBeNull();
    expect(result.current.picker).toBeNull();
    expect(result.current.layers?.items.every((item) => !item.visible)).toBe(true);
  });

  it('tender=<calc_id> из адреса включает скрытый слой', () => {
    const { setNamesHidden } = mount([tenderLayerKey('c2')], { tenderParam: 'c2' });
    expect(setNamesHidden).toHaveBeenCalledWith([tenderLayerKey('c2')], false);
  });

  it('tender= для включённого слоя ничего не меняет', () => {
    const { setNamesHidden } = mount([], { tenderParam: 'c1' });
    expect(setNamesHidden).not.toHaveBeenCalled();
  });

  it('режим «PDF» (DXF не показан) слой не рисует, панель остаётся', () => {
    const { result } = mount([], { shown: false });
    expect(result.current.painter(true)).toBeNull();
    expect(result.current.layers).not.toBeNull();
  });

  it('на виде нет расчётов - группы нет', () => {
    state.layers = [];
    const { result } = mount([]);
    expect(result.current.layers).toBeNull();
    expect(result.current.painter(true)).toBeNull();
  });
});
