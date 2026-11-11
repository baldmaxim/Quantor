import type {
  CadConstructionRead,
  CadVorCoverageGroupRead,
  CadVorCoverageRead,
  CadVorItemRead,
  CadVorSuggestionRead,
} from '@quantor/api-client';

import { materialLabel, KIND_LABELS } from './construction-labels';
import { formatNumber, NO_VALUE } from './view-format';

/**
 * ВОР Заказчика во вкладке CAD (ADR-0038 п. 5): чистые функции без сети и React.
 * ВОР - только объект сверки: количества строк показываются справочно и с количествами CAD
 * не сравниваются.
 */

export const CAD_VOR_NOT_IN_VOR_VISIBLE_KEY = 'quantor.cad.vor-not-in-vor-visible';

/** Группа свода: подпись «Кладка, 100 мм, газобетон». */
export const vorGroupLabel = (
  group: Pick<CadVorCoverageGroupRead, 'kind' | 'thickness_mm' | 'material'>,
): string => {
  const parts = [KIND_LABELS[group.kind], `${formatNumber(group.thickness_mm, 1)} мм`];
  if (group.material !== null) parts.push(materialLabel(group.material));
  return parts.join(', ');
};

/** Строка ВОР для показа: «код — наименование». Количество и единица - отдельно, справочно. */
export const vorItemTitle = (item: Pick<CadVorItemRead, 'code' | 'name'>): string =>
  item.code ? `${item.code} — ${item.name}` : item.name;

export const vorItemQuantity = (item: Pick<CadVorItemRead, 'quantity' | 'unit'>): string =>
  item.quantity === null
    ? NO_VALUE
    : item.unit
      ? `${formatNumber(item.quantity, 3)} ${item.unit}`
      : formatNumber(item.quantity, 3);

export const SUGGEST_REASON_LABELS: Readonly<Record<CadVorSuggestionRead['reasons'][number], string>> = {
  thickness: 'совпала толщина',
  kind: 'совпал вид',
  material: 'совпал материал',
};

export const suggestReasonsText = (reasons: CadVorSuggestionRead['reasons']): string =>
  reasons.map((reason) => SUGGEST_REASON_LABELS[reason]).join(', ');

/** Толщины из ключей групп `вид|толщина|материал`: по возрастанию, без повторов. */
export const thicknessesOfKeys = (keys: readonly string[]): number[] => {
  const values = keys
    .map((key) => Number(key.split('|')[1]))
    .filter((value) => Number.isFinite(value));
  return [...new Set(values)].sort((a, b) => a - b);
};

/** Подпись списка толщин: «80, 150 мм». */
export const thicknessListText = (values: readonly number[]): string =>
  `${values.map((value) => formatNumber(value, 1)).join(', ')} мм`;

/**
 * Конструкции, которые подсвечиваются как «не в ВОР». ВОР не загружен или подсветка выключена -
 * `undefined`: рисовать нечего, даже если сервер прислал ключи.
 */
export const notInVorIds = (
  coverage: CadVorCoverageRead | null | undefined,
  enabled: boolean,
): ReadonlySet<string> | undefined =>
  enabled && coverage?.has_vor === true ? new Set(coverage.not_in_vor_keys) : undefined;

export type ConstructionVorStatus =
  | { readonly state: 'no-vor' }
  /** Конструкция не в итогах (нет толщины или высоты): со строками ВОР не сверяется. */
  | { readonly state: 'not-counted' }
  | { readonly state: 'not-in-vor'; readonly groupKey: string }
  | { readonly state: 'in-vor'; readonly groupKey: string; readonly items: readonly CadVorItemRead[] };

const sameThickness = (a: number, b: number): boolean => Math.abs(a - b) < 0.0005;

/** Группа сверки, к которой относится строка свода или конструкция. */
export const coverageGroupFor = (
  coverage: CadVorCoverageRead,
  group: Pick<CadVorCoverageGroupRead, 'kind' | 'thickness_mm' | 'material'>,
): CadVorCoverageGroupRead | null =>
  coverage.groups.find(
    (item) =>
      item.kind === group.kind &&
      sameThickness(item.thickness_mm, group.thickness_mm) &&
      (item.material ?? null) === (group.material ?? null),
  ) ?? null;

/** Статус конструкции в ВОР: по группе (вид, толщина, материал), как её строит сервер. */
export const constructionVorStatus = (
  coverage: CadVorCoverageRead | null | undefined,
  construction: CadConstructionRead | null | undefined,
): ConstructionVorStatus | null => {
  if (!coverage || !construction) return null;
  if (!coverage.has_vor) return { state: 'no-vor' };
  const thickness = construction.computed.thickness_mm;
  if (construction.computed.status !== 'ok' || thickness === null) return { state: 'not-counted' };
  const group = coverageGroupFor(coverage, {
    kind: construction.kind,
    thickness_mm: thickness,
    material: construction.material.value ?? null,
  });
  if (group === null) return { state: 'not-counted' };
  return group.status === 'linked'
    ? { state: 'in-vor', groupKey: group.group_key, items: group.items }
    : { state: 'not-in-vor', groupKey: group.group_key };
};
