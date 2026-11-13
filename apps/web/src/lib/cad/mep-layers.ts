'use client';

import { useCallback } from 'react';

import { useStoredNumber } from './useStoredNumber';

/**
 * Слои трасс механики (ADR-0036 п. 8): по слою на систему (29 слоёв: 20 трасс движка cad_mep.v12, 2 служебных и 7 приборов санузлов и кухонь), как в DXF генератора.
 *
 * Порядок - порядок группы в панели «Слои». Цвета - токены `--cad-mep-*` (packages/ui/src/base.css),
 * свои для каждой темы. Видимость слоёв - личный выбор человека: хранится в браузере битовой маской
 * по этому списку и переживает смену вида и перезагрузку.
 */

export type MepGroupKey =
  | 'water'
  | 'sewer'
  | 'heating'
  | 'vent'
  | 'smoke'
  | 'cooling'
  | 'fire'
  | 'common'
  | 'sanitary'
  | 'electric'
  | 'lowcurrent';

/** Группы слоёв трасс в порядке показа в панели «Слои». */
export const MEP_GROUPS: readonly { readonly key: MepGroupKey; readonly label: string }[] = [
  { key: 'water', label: 'Водоснабжение' },
  { key: 'sewer', label: 'Канализация' },
  { key: 'heating', label: 'Отопление' },
  { key: 'vent', label: 'Вентиляция' },
  { key: 'smoke', label: 'Противодымная вентиляция' },
  { key: 'cooling', label: 'Кондиционирование' },
  { key: 'fire', label: 'Пожаротушение' },
  { key: 'common', label: 'Узлы и стояки' },
  { key: 'sanitary', label: 'Сантехника' },
  { key: 'electric', label: 'Электроснабжение ЭОМ' },
  { key: 'lowcurrent', label: 'Слаботочные системы СС' },
];

export interface IMepLayerDef {
  /** Имя слоя в DXF и в `preview.json` трасс. */
  readonly name: string;
  /** Система (группа панели «Слои»). */
  readonly group: MepGroupKey;
  /** Подпись для человека. */
  readonly label: string;
  /** Токен цвета без `var()`. */
  readonly token: string;
}

export const MEP_LAYERS: readonly IMepLayerDef[] = [
  { name: 'M-VK-V1', group: 'water', label: 'Водопровод В1', token: '--cad-mep-vk-v1' },
  { name: 'M-VK-T3', group: 'water', label: 'ГВС Т3', token: '--cad-mep-vk-t3' },
  { name: 'M-VK-T4', group: 'water', label: 'Циркуляция ГВС Т4', token: '--cad-mep-vk-t4' },
  { name: 'M-VK-K1', group: 'sewer', label: 'Канализация К1', token: '--cad-mep-vk-k1' },
  { name: 'M-VK-K2', group: 'sewer', label: 'Водосток К2', token: '--cad-mep-vk-k2' },
  { name: 'M-VK-K4', group: 'sewer', label: 'Дренаж К4', token: '--cad-mep-vk-k4' },
  { name: 'M-OV-T1', group: 'heating', label: 'Отопление подача Т1', token: '--cad-mep-ov-t1' },
  { name: 'M-OV-T2', group: 'heating', label: 'Отопление обратка Т2', token: '--cad-mep-ov-t2' },
  { name: 'M-OV-VZH', group: 'vent', label: 'Вытяжка квартир Ж', token: '--cad-mep-ov-vzh' },
  { name: 'M-OV-MO', group: 'vent', label: 'Местные отсосы МО', token: '--cad-mep-ov-mo' },
  { name: 'M-OV-VMOP', group: 'vent', label: 'Вытяжка МОП', token: '--cad-mep-ov-vmop' },
  { name: 'M-OV-PMOP', group: 'vent', label: 'Приток МОП', token: '--cad-mep-ov-pmop' },
  { name: 'M-OV-TR', group: 'vent', label: 'Транзитный канал', token: '--cad-mep-ov-tr' },
  { name: 'M-PD-DU', group: 'smoke', label: 'Дымоудаление ДУ', token: '--cad-mep-pd-du' },
  { name: 'M-PD-KDU', group: 'smoke', label: 'Компенсация дымоудаления', token: '--cad-mep-pd-kdu' },
  { name: 'M-PD-DP', group: 'smoke', label: 'Подпор воздуха ДП', token: '--cad-mep-pd-dp' },
  { name: 'M-KV-FR', group: 'cooling', label: 'Фреон кондиционирования', token: '--cad-mep-kv-fr' },
  { name: 'M-KV-DR', group: 'cooling', label: 'Дренаж конденсата', token: '--cad-mep-kv-dr' },
  { name: 'M-PT-VPV', group: 'fire', label: 'Пожарный водопровод ВПВ', token: '--cad-mep-pt-vpv' },
  { name: 'M-PT-AUP', group: 'fire', label: 'Автоматическое пожаротушение АУП', token: '--cad-mep-pt-aup' },
  { name: 'M-NODE', group: 'common', label: 'Узлы и арматура', token: '--cad-mep-node' },
  { name: 'M-RISER', group: 'common', label: 'Стояки', token: '--cad-mep-riser' },
  // Приборы: по замкнутой фигуре на прибор, один цвет на все. Новые слои - только в конец списка (маска).
  { name: 'M-SAN-BATH', group: 'sanitary', label: 'Ванна', token: '--cad-mep-san' },
  { name: 'M-SAN-SHOWER', group: 'sanitary', label: 'Душевой поддон', token: '--cad-mep-san' },
  { name: 'M-SAN-WC', group: 'sanitary', label: 'Унитаз', token: '--cad-mep-san' },
  { name: 'M-SAN-BASIN', group: 'sanitary', label: 'Умывальник', token: '--cad-mep-san' },
  { name: 'M-SAN-KSINK', group: 'sanitary', label: 'Мойка кухонная', token: '--cad-mep-san' },
  { name: 'M-SAN-WASHER', group: 'sanitary', label: 'Стиральная машина', token: '--cad-mep-san' },
  { name: 'M-SAN-MOPSINK', group: 'sanitary', label: 'Раковина ПУИ', token: '--cad-mep-san' },
  // ЭОМ и СС этажа (генератор cad_eom): сети, стояки и приборы.
  { name: 'E-EO-FEED', group: 'electric', label: 'Питающие линии ЩЭ → ЩМк', token: '--cad-eom-feed' },
  { name: 'E-EO-LT', group: 'electric', label: 'Временное освещение квартир', token: '--cad-eom-lt' },
  { name: 'E-EO-MOP', group: 'electric', label: 'Освещение МОП', token: '--cad-eom-mop' },
  { name: 'E-EO-PE', group: 'electric', label: 'Уравнивание потенциалов', token: '--cad-eom-pe' },
  { name: 'E-EO-RISER', group: 'electric', label: 'Стояк ЭО', token: '--cad-eom-riser' },
  { name: 'E-EO-DEV', group: 'electric', label: 'Щиты и приборы ЭОМ', token: '--cad-eom-dev' },
  { name: 'E-SS-TRAY', group: 'lowcurrent', label: 'Лоток СБ', token: '--cad-ss-tray' },
  { name: 'E-SS-OPT', group: 'lowcurrent', label: 'Оптика GPON', token: '--cad-ss-opt' },
  { name: 'E-SS-UTP', group: 'lowcurrent', label: 'Домофон UTP', token: '--cad-ss-utp' },
  { name: 'E-SS-RAD', group: 'lowcurrent', label: 'Радиофикация', token: '--cad-ss-rad' },
  { name: 'E-SS-RISER', group: 'lowcurrent', label: 'Стояк СС', token: '--cad-ss-riser' },
  { name: 'E-SS-DEV', group: 'lowcurrent', label: 'Шкафы и приборы СС', token: '--cad-ss-dev' },
];

/** Ключ браузерного хранилища маски скрытых слоёв. */
export const MEP_HIDDEN_KEY = 'quantor.cad.mep-hidden.v2';

export const mepLayerDef = (name: string): IMepLayerDef | null =>
  MEP_LAYERS.find((def) => def.name === name) ?? null;

/** Подпись пункта списка: «Отопление подача · M-OV-T1». */
export const mepLayerTitle = (def: IMepLayerDef): string => `${def.label} · ${def.name}`;

/** Слои, которые есть в `preview.json` трасс, в порядке списка систем. Чужие имена не перечисляются. */
export const presentMepLayers = (previewLayers: readonly string[]): IMepLayerDef[] =>
  MEP_LAYERS.filter((def) => previewLayers.includes(def.name));

/** Слои превью по системам в порядке групп; группы без слоёв не возвращаются. */
export const groupMepLayers = (
  present: readonly IMepLayerDef[],
): { group: MepGroupKey; label: string; layers: IMepLayerDef[] }[] =>
  MEP_GROUPS.map(({ key, label }) => ({
    group: key,
    label,
    layers: present.filter((def) => def.group === key),
  })).filter((item) => item.layers.length > 0);

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
