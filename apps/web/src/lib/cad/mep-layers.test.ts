import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  groupMepLayers,
  isMepLayerHidden,
  mepColorVar,
  MEP_GROUPS,
  MEP_LAYERS,
  mepLayerDef,
  mepLayerTitle,
  presentMepLayers,
  readMepColors,
  withMepLayersHidden,
} from './mep-layers';

describe('слои трасс механики', () => {
  it('22 слоя в порядке группы: 20 трасс движка и 2 служебных, у каждого подпись и свой токен', () => {
    expect(MEP_LAYERS.map((def) => def.name)).toEqual([
      'M-VK-V1',
      'M-VK-T3',
      'M-VK-T4',
      'M-VK-K1',
      'M-VK-K2',
      'M-VK-K4',
      'M-OV-T1',
      'M-OV-T2',
      'M-OV-VZH',
      'M-OV-MO',
      'M-OV-VMOP',
      'M-OV-PMOP',
      'M-OV-TR',
      'M-PD-DU',
      'M-PD-KDU',
      'M-PD-DP',
      'M-KV-FR',
      'M-KV-DR',
      'M-PT-VPV',
      'M-PT-AUP',
      'M-NODE',
      'M-RISER',
    ]);
    expect(new Set(MEP_LAYERS.map((def) => def.name)).size).toBe(22);
    expect(new Set(MEP_LAYERS.map((def) => def.token)).size).toBe(22);
    expect(new Set(MEP_LAYERS.map((def) => def.label)).size).toBe(22);
    expect(MEP_LAYERS.every((def) => def.label.trim() !== '')).toBe(true);
    expect(MEP_LAYERS.every((def) => def.token.startsWith('--cad-mep-'))).toBe(true);
  });

  it('подписи по-русски: «подпись · код»', () => {
    expect(mepLayerTitle(mepLayerDef('M-VK-K1')!)).toBe('Канализация К1 · M-VK-K1');
    expect(mepLayerDef('M-VK-V1')?.label).toBe('Водопровод В1');
    expect(mepLayerDef('M-PD-DP')?.label).toBe('Подпор воздуха ДП');
    expect(mepLayerDef('A-WALL')).toBeNull();
  });

  it('у каждого слоя есть токен в обеих темах base.css', () => {
    const css = readFileSync(resolve(__dirname, '../../../../../packages/ui/src/base.css'), 'utf8');
    for (const def of MEP_LAYERS) {
      const count = css.split(`${def.token}:`).length - 1;
      expect(count, def.token).toBe(3);
    }
  });

  it('маска держит все 22 бита, в том числе старший', () => {
    const all = MEP_LAYERS.map((def) => def.name);
    const full = withMepLayersHidden(0, all, true);
    expect(full).toBe(2 ** 22 - 1);
    expect(all.every((name) => isMepLayerHidden(full, name))).toBe(true);
    const last = withMepLayersHidden(0, ['M-RISER'], true);
    expect(last).toBe(2 ** 21);
    expect(isMepLayerHidden(last, 'M-RISER')).toBe(true);
    expect(isMepLayerHidden(last, 'M-NODE')).toBe(false);
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

  it('группы слоёв: порядок, подписи, каждая из 22 записей в своей группе', () => {
    expect(MEP_GROUPS.map((group) => `${group.key}:${group.label}`)).toEqual([
      'water:Водоснабжение',
      'sewer:Канализация',
      'heating:Отопление',
      'vent:Вентиляция',
      'smoke:Противодымная вентиляция',
      'cooling:Кондиционирование',
      'fire:Пожаротушение',
      'common:Узлы и стояки',
    ]);
    const all = groupMepLayers(MEP_LAYERS);
    expect(all.map((item) => [item.group, item.layers.map((def) => def.name)])).toEqual([
      ['water', ['M-VK-V1', 'M-VK-T3', 'M-VK-T4']],
      ['sewer', ['M-VK-K1', 'M-VK-K2', 'M-VK-K4']],
      ['heating', ['M-OV-T1', 'M-OV-T2']],
      ['vent', ['M-OV-VZH', 'M-OV-MO', 'M-OV-VMOP', 'M-OV-PMOP', 'M-OV-TR']],
      ['smoke', ['M-PD-DU', 'M-PD-KDU', 'M-PD-DP']],
      ['cooling', ['M-KV-FR', 'M-KV-DR']],
      ['fire', ['M-PT-VPV', 'M-PT-AUP']],
      ['common', ['M-NODE', 'M-RISER']],
    ]);
    expect(all.flatMap((item) => item.layers)).toHaveLength(22);
    expect(MEP_LAYERS.every((def) => MEP_GROUPS.some((group) => group.key === def.group))).toBe(true);
  });

  it('пустые группы не возвращаются', () => {
    const grouped = groupMepLayers(presentMepLayers(['M-OV-T2', 'M-NODE', 'M-OV-T1']));
    expect(grouped.map((item) => item.label)).toEqual(['Отопление', 'Узлы и стояки']);
    expect(groupMepLayers([])).toEqual([]);
  });

  it('цвет образца - токен темы, для холста значения читаются из токенов', () => {
    expect(mepColorVar('M-OV-T1')).toBe('var(--cad-mep-ov-t1)');
    expect(mepColorVar('X')).toBe('var(--muted)');
    const colors = readMepColors((token) => `v:${token}`);
    expect(colors['M-VK-T3']).toBe('v:--cad-mep-vk-t3');
    expect(Object.keys(colors)).toHaveLength(22);
  });
});
