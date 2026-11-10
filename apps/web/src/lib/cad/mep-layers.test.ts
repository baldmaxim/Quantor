import { describe, expect, it } from 'vitest';

import {
  isMepLayerHidden,
  mepColorVar,
  MEP_LAYERS,
  presentMepLayers,
  readMepColors,
  withMepLayersHidden,
} from './mep-layers';

describe('слои трасс механики', () => {
  it('десять систем в порядке группы, у каждой свой токен цвета', () => {
    expect(MEP_LAYERS.map((def) => def.name)).toEqual([
      'M-OV-T1',
      'M-OV-T2',
      'M-PT-VPV',
      'M-PT-AUP',
      'M-VK-V1',
      'M-VK-T3',
      'M-VK-T4',
      'M-VK-K1',
      'M-NODE',
      'M-RISER',
    ]);
    expect(new Set(MEP_LAYERS.map((def) => def.token)).size).toBe(10);
    expect(MEP_LAYERS.every((def) => def.token.startsWith('--cad-mep-'))).toBe(true);
  });

  it('в группе только слои, которые есть в превью трасс', () => {
    const present = presentMepLayers(['M-OV-T2', 'M-NODE', 'A-WALL', 'M-OV-T1']);
    expect(present.map((def) => def.name)).toEqual(['M-OV-T1', 'M-OV-T2', 'M-NODE']);
    expect(presentMepLayers([])).toEqual([]);
  });

  it('скрытие и показ слоёв маской: по одному и группой', () => {
    let mask = 0;
    expect(isMepLayerHidden(mask, 'M-OV-T1')).toBe(false);

    mask = withMepLayersHidden(mask, ['M-OV-T1', 'M-RISER'], true);
    expect(isMepLayerHidden(mask, 'M-OV-T1')).toBe(true);
    expect(isMepLayerHidden(mask, 'M-RISER')).toBe(true);
    expect(isMepLayerHidden(mask, 'M-OV-T2')).toBe(false);

    // Повтор ничего не меняет, показ возвращает слой.
    expect(withMepLayersHidden(mask, ['M-OV-T1'], true)).toBe(mask);
    mask = withMepLayersHidden(mask, ['M-OV-T1'], false);
    expect(isMepLayerHidden(mask, 'M-OV-T1')).toBe(false);
    expect(isMepLayerHidden(mask, 'M-RISER')).toBe(true);

    mask = withMepLayersHidden(mask, MEP_LAYERS.map((def) => def.name), false);
    expect(mask).toBe(0);
  });

  it('чужое имя слоя скрыть нельзя, мусорная маска не ломает', () => {
    expect(withMepLayersHidden(0, ['A-WALL'], true)).toBe(0);
    expect(isMepLayerHidden(1023, 'A-WALL')).toBe(false);
    expect(withMepLayersHidden(Number.NaN, ['M-NODE'], true)).toBeGreaterThan(0);
  });

  it('цвет образца - токен темы, для холста значения читаются из токенов', () => {
    expect(mepColorVar('M-OV-T1')).toBe('var(--cad-mep-ov-t1)');
    expect(mepColorVar('X')).toBe('var(--muted)');
    const colors = readMepColors((token) => `v:${token}`);
    expect(colors['M-VK-T3']).toBe('v:--cad-mep-vk-t3');
    expect(Object.keys(colors)).toHaveLength(10);
  });
});
