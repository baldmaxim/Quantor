import type { CadEomQuantity } from '@quantor/api-client';

import { formatMeters, mepSystemLabel, MEP_SYSTEMS, type MepCandidate } from './mep-candidate';
import { MEP_LAYERS, mepLayerDef } from './mep-layers';

/**
 * Общая спецификация вкладки «Трассы»: механика и ЭОМ/СС одним списком систем, каждая раскрывается
 * в строки «позиция - количество». Чисел здесь не считают: длины механики - из кандидата трасс
 * (`candidate.json`: по слоям, Ø и сечениям), позиции ЭОМ и СС - из ведомости генератора `cad_eom`.
 * До принятия человеком это кандидат, не ВОР и не смета.
 */

export interface ISpecRow {
  readonly key: string;
  readonly item: string;
  /** Количество для показа (запятая - разделитель). */
  readonly qty: string;
  readonly unit: string;
  /** Формула или источник строки генератора; `null` - нет. */
  readonly hint: string | null;
}

export interface ISpecSystem {
  readonly key: string;
  readonly label: string;
  /** Раздел: механика (трассы) или ЭОМ и СС. */
  readonly source: 'mep' | 'eom';
  /** Итог в заголовке системы: «12,30 м» у механики, «5 поз.» у ЭОМ и СС. */
  readonly summary: string;
  readonly rows: readonly ISpecRow[];
}

/** Остаток длины слоя без известного Ø или сечения, ниже которого строка не показывается, м. */
const REMAINDER_M = 0.01;

/** Сечение генератора «AxB» или «ØD» для человека: «400×200 мм», «Ø200 мм». */
export const sizeText = (size: string): string => `${size.replace(/[xхX]/g, '×')} мм`;

/** Количество ведомости ЭОМ и СС: целое - как есть, дробное - до двух знаков. */
export const qtyText = (qty: number): string =>
  qty.toLocaleString('ru-RU', { maximumFractionDigits: Number.isInteger(qty) ? 0 : 2 });

const layerLabel = (layer: string): string => mepLayerDef(layer)?.label ?? layer;

/** Порядок слоёв - как в панели «Слои»; чужие имена - в конце по алфавиту. */
const layerOrder = (a: string, b: string): number => {
  const ia = MEP_LAYERS.findIndex((def) => def.name === a);
  const ib = MEP_LAYERS.findIndex((def) => def.name === b);
  if (ia >= 0 && ib >= 0) return ia - ib;
  if (ia >= 0) return -1;
  if (ib >= 0) return 1;
  return a.localeCompare(b);
};

const meterRow = (key: string, item: string, length: number): ISpecRow => ({
  key,
  item,
  qty: formatMeters(length),
  unit: 'м',
  hint: null,
});

/** Строки слоя: по Ø и сечениям, остаток без известного размера - отдельной строкой. */
const layerRows = (candidate: MepCandidate, layer: string): ISpecRow[] => {
  const label = layerLabel(layer);
  const total = candidate.routes.by_layer[layer]?.length_m ?? 0;
  const dims = candidate.routes.by_layer_dims[layer];
  const rows: ISpecRow[] = [];
  let known = 0;
  for (const [dn, value] of Object.entries(dims?.by_dn_mm ?? {}).sort(([a], [b]) => Number(a) - Number(b))) {
    rows.push(meterRow(`${layer}|dn|${dn}`, `${label}, Ø${dn} мм`, value.length_m));
    known += value.length_m;
  }
  for (const [size, value] of Object.entries(dims?.by_size ?? {})) {
    rows.push(meterRow(`${layer}|size|${size}`, `${label}, ${sizeText(size)}`, value.length_m));
    known += value.length_m;
  }
  if (rows.length === 0) return total > 0 ? [meterRow(layer, label, total)] : [];
  const rest = total - known;
  if (rest > REMAINDER_M) rows.push(meterRow(`${layer}|rest`, `${label}, размер не определён`, rest));
  return rows;
};

/** Система слоя: по генератору (`routes.layers`), у старых файлов - по группе панели «Слои». */
const systemOfLayer = (candidate: MepCandidate, layer: string): string =>
  candidate.routes.layers[layer]?.system ?? mepLayerDef(layer)?.group ?? layer;

/** Системы механики в порядке показа: известные - по `MEP_SYSTEMS`, прочие - за ними. */
export const mepSpecSystems = (candidate: MepCandidate): ISpecSystem[] => {
  const layers = new Map<string, string[]>();
  for (const layer of Object.keys(candidate.routes.by_layer).sort(layerOrder)) {
    const system = systemOfLayer(candidate, layer);
    layers.set(system, [...(layers.get(system) ?? []), layer]);
  }
  for (const system of Object.keys(candidate.routes.by_system)) {
    if (!layers.has(system)) layers.set(system, []);
  }
  const known = MEP_SYSTEMS.map((item) => item.key);
  const order = [
    ...known.filter((key) => layers.has(key)),
    ...[...layers.keys()].filter((key) => !known.includes(key)).sort(),
  ];
  return order.flatMap((system) => {
    const rows = (layers.get(system) ?? []).flatMap((layer) => layerRows(candidate, layer));
    const length =
      candidate.routes.by_system[system]?.length_m ??
      (layers.get(system) ?? []).reduce((sum, layer) => sum + (candidate.routes.by_layer[layer]?.length_m ?? 0), 0);
    if (rows.length === 0 && length <= 0) return [];
    return [
      {
        key: `mep:${system}`,
        label: mepSystemLabel(system),
        source: 'mep' as const,
        summary: `${formatMeters(length)} м`,
        rows,
      },
    ];
  });
};

/** Системы ЭОМ и СС: строки ведомости по полю `system` в порядке генератора. */
export const eomSpecSystems = (quantities: readonly CadEomQuantity[]): ISpecSystem[] => {
  const groups = new Map<string, CadEomQuantity[]>();
  for (const row of quantities) groups.set(row.system, [...(groups.get(row.system) ?? []), row]);
  return [...groups.entries()].map(([system, rows]) => ({
    key: `eom:${system}`,
    label: system,
    source: 'eom' as const,
    summary: `${rows.length} поз.`,
    rows: rows.map((row, index) => ({
      key: `${index}|${row.item}`,
      item: row.item,
      qty: qtyText(row.qty),
      unit: row.unit,
      hint: row.formula ?? row.source ?? null,
    })),
  }));
};

/** Общая спецификация: сначала системы механики, затем ЭОМ и СС. */
export const buildSpec = (
  candidate: MepCandidate | null,
  quantities: readonly CadEomQuantity[],
): ISpecSystem[] => [...(candidate ? mepSpecSystems(candidate) : []), ...eomSpecSystems(quantities)];
