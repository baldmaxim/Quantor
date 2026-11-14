import type { CheckStatus, FrameCheckOut, FrameNodeOut, NodeStatus } from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';

/**
 * Каркас здания (ADR-0043, С2): подписи, группировка узлов и разбор чисел формы.
 * Порядок узлов задаёт сервер (корпус → секция → уровни снизу вверх); здесь он не меняется.
 */

export const NODE_STATUS_LABELS: Record<NodeStatus, string> = {
  candidate: 'Кандидат',
  confirmed: 'Подтверждён',
  rejected: 'Отклонён',
};

export const NODE_STATUS_TONES: Record<NodeStatus, BadgeTone> = {
  candidate: 'warning',
  confirmed: 'success',
  rejected: 'neutral',
};

export const CHECK_STATUS_LABELS: Record<CheckStatus, string> = {
  match: 'Совпадает',
  mismatch: 'Расхождение',
  not_run: 'Не проверено',
};

export const CHECK_STATUS_TONES: Record<CheckStatus, BadgeTone> = {
  match: 'success',
  mismatch: 'danger',
  not_run: 'neutral',
};

export const buildingLabel = (building: string | null): string =>
  building === null ? 'Корпус не указан' : `Корпус ${building}`;

export const sectionLabel = (section: string | null): string =>
  section === null ? 'Секция не указана' : `Секция ${section}`;

export const placeText = (building: string | null, section: string | null): string =>
  [buildingLabel(building), section === null ? null : sectionLabel(section)]
    .filter((part): part is string => part !== null)
    .join(', ');

/** Отметка со знаком и тремя знаками после запятой, как на чертежах: «+3,300». */
export const elevationText = (value: number | null): string => {
  if (value === null) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '±';
  return `${sign}${Math.abs(value).toFixed(3).replace('.', ',')}`;
};

/** Высота в мм; «—», если не известна. */
export const heightText = (value: number | null): string =>
  value === null ? '—' : `${Math.round(value * 1000)} мм`;

export interface ISectionGroup {
  readonly section: FrameNodeOut | null;
  readonly levels: readonly FrameNodeOut[];
}

export interface IBuildingGroup {
  readonly building: FrameNodeOut;
  readonly sections: readonly ISectionGroup[];
}

/** Узлы в дерево: корпус → секции → уровни; порядок — как пришёл с сервера. */
export const groupFrame = (nodes: readonly FrameNodeOut[]): IBuildingGroup[] => {
  const children = new Map<string, FrameNodeOut[]>();
  for (const node of nodes) {
    if (node.parent_id === null) continue;
    const list = children.get(node.parent_id) ?? [];
    list.push(node);
    children.set(node.parent_id, list);
  }
  return nodes
    .filter((node) => node.kind === 'building')
    .map((building) => ({
      building,
      sections: (children.get(building.id) ?? [])
        .filter((node) => node.kind === 'section')
        .map((section) => ({ section, levels: children.get(section.id) ?? [] })),
    }));
};

export interface ICheckCounts {
  readonly match: number;
  readonly mismatch: number;
  readonly not_run: number;
}

export const countChecks = (checks: readonly FrameCheckOut[]): ICheckCounts => ({
  match: checks.filter((item) => item.status === 'match').length,
  mismatch: checks.filter((item) => item.status === 'mismatch').length,
  not_run: checks.filter((item) => item.status === 'not_run').length,
});

export interface ICheckGroup {
  readonly code: string;
  readonly title: string;
  readonly items: readonly FrameCheckOut[];
}

/** Проверки по коду в порядке каталога; внутри — сначала расхождения. */
export const groupChecks = (
  checks: readonly FrameCheckOut[],
  onlyMismatches: boolean,
): ICheckGroup[] => {
  const order: Record<CheckStatus, number> = { mismatch: 0, not_run: 1, match: 2 };
  const groups = new Map<string, { title: string; items: FrameCheckOut[] }>();
  for (const item of checks) {
    if (onlyMismatches && item.status !== 'mismatch') continue;
    const group = groups.get(item.code) ?? { title: item.title, items: [] };
    group.items.push(item);
    groups.set(item.code, group);
  }
  return [...groups.entries()].map(([code, group]) => ({
    code,
    title: group.title,
    items: [...group.items].sort((a, b) => order[a.status] - order[b.status]),
  }));
};

export const checkPlace = (item: FrameCheckOut): string | null => {
  const parts = [
    item.building === null && item.section === null && item.level === null
      ? null
      : placeText(item.building, item.section),
    item.level,
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(' · ') : null;
};

export type NumberResult =
  { readonly ok: true; readonly value: number | null } | { readonly ok: false };

/** Число из поля формы: пусто — null, запятая — десятичный разделитель. */
export const parseNumber = (text: string): NumberResult => {
  const clean = text.trim().replace(',', '.').replace('−', '-');
  if (clean === '') return { ok: true, value: null };
  const value = Number(clean);
  return Number.isFinite(value) ? { ok: true, value } : { ok: false };
};

/** Целое из поля формы: пусто — null. */
export const parseInteger = (text: string): NumberResult => {
  const clean = text.trim().replace('−', '-');
  if (clean === '') return { ok: true, value: null };
  return /^-?\d{1,3}$/.test(clean) ? { ok: true, value: Number(clean) } : { ok: false };
};

/** Высота из мм формы в метры; пусто — null, не положительное — ошибка. */
export const parseHeightMm = (text: string): NumberResult => {
  const clean = text.trim();
  if (clean === '') return { ok: true, value: null };
  if (!/^\d{3,5}$/.test(clean) || Number(clean) <= 0) return { ok: false };
  return { ok: true, value: Number(clean) / 1000 };
};
