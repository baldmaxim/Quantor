'use client';

import { useCallback } from 'react';

import { useStoredNumber } from './useStoredNumber';

/**
 * Слои трасс механики (ADR-0036 п. 8): по слою на систему, как в DXF генератора.
 *
 * Порядок - порядок группы в панели «Слои». Цвета - токены `--cad-mep-*` (packages/ui/src/base.css),
 * свои для каждой темы. Видимость слоёв - личный выбор человека: хранится в браузере битовой маской
 * по этому списку и переживает смену вида и перезагрузку.
 */

export interface IMepLayerDef {
  /** Имя слоя в DXF и в `preview.json` трасс. */
  readonly name: string;
  /** Подпись для человека. */
  readonly label: string;
  /** Токен цвета без `var()`. */
  readonly token: string;
}

export const MEP_LAYERS: readonly IMepLayerDef[] = [
  { name: 'M-OV-T1', label: 'Отопление подача', token: '--cad-mep-ov-t1' },
  { name: 'M-OV-T2', label: 'Отопление обратка', token: '--cad-mep-ov-t2' },
  { name: 'M-PT-VPV', label: 'ВПВ', token: '--cad-mep-pt-vpv' },
  { name: 'M-PT-AUP', label: 'АУП', token: '--cad-mep-pt-aup' },
  { name: 'M-VK-V1', label: 'В1', token: '--cad-mep-vk-v1' },
  { name: 'M-VK-T3', label: 'Т3', token: '--cad-mep-vk-t3' },
  { name: 'M-VK-T4', label: 'Т4', token: '--cad-mep-vk-t4' },
  { name: 'M-VK-K1', label: 'К1 стояки', token: '--cad-mep-vk-k1' },
  { name: 'M-NODE', label: 'Узлы', token: '--cad-mep-node' },
  { name: 'M-RISER', label: 'Стояки', token: '--cad-mep-riser' },
];

/** Ключ браузерного хранилища маски скрытых слоёв. */
export const MEP_HIDDEN_KEY = 'quantor.cad.mep-hidden.v1';

export const mepLayerDef = (name: string): IMepLayerDef | null =>
  MEP_LAYERS.find((def) => def.name === name) ?? null;

/** Подпись пункта списка: «Отопление подача · M-OV-T1». */
export const mepLayerTitle = (def: IMepLayerDef): string => `${def.label} · ${def.name}`;

/** Слои, которые есть в `preview.json` трасс, в порядке списка систем. Чужие имена не перечисляются. */
export const presentMepLayers = (previewLayers: readonly string[]): IMepLayerDef[] =>
  MEP_LAYERS.filter((def) => previewLayers.includes(def.name));

const bitOf = (name: string): number => {
  const at = MEP_LAYERS.findIndex((def) => def.name === name);
  return at < 0 ? 0 : 2 ** at;
};

/** Слой скрыт человеком. Незнакомое имя скрыть нельзя: оно всегда видно. */
export const isMepLayerHidden = (mask: number, name: string): boolean => {
  const bit = bitOf(name);
  return bit !== 0 && Math.floor(mask / bit) % 2 === 1;
};

/** Маска после скрытия или показа слоёв; чужие имена игнорируются. */
export const withMepLayersHidden = (
  mask: number,
  names: readonly string[],
  hidden: boolean,
): number => {
  let next = Number.isFinite(mask) && mask > 0 ? Math.trunc(mask) : 0;
  for (const name of names) {
    const bit = bitOf(name);
    if (bit === 0) continue;
    const isHidden = Math.floor(next / bit) % 2 === 1;
    if (hidden && !isHidden) next += bit;
    else if (!hidden && isHidden) next -= bit;
  }
  return next;
};

/** Значение для `style`: образец цвета следует за темой. */
export const mepColorVar = (name: string): string => {
  const def = mepLayerDef(name);
  return def ? `var(${def.token})` : 'var(--muted)';
};

/** Цвета слоёв трасс для холста по токенам темы; ключ - имя слоя. */
export const readMepColors = (read: (token: string) => string): Record<string, string> =>
  Object.fromEntries(MEP_LAYERS.map((def) => [def.name, read(def.token)]));

/** Видимость слоёв трасс: маска в браузере и действия над ней. */
export const useMepLayerVisibility = (): {
  readonly mask: number;
  readonly setHidden: (names: readonly string[], hidden: boolean) => void;
} => {
  const [mask, setMask] = useStoredNumber(MEP_HIDDEN_KEY, 0);
  const setHidden = useCallback(
    (names: readonly string[], hidden: boolean) => setMask(withMepLayersHidden(mask, names, hidden)),
    [mask, setMask],
  );
  return { mask, setHidden };
};
