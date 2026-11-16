import type {
  TenderCalcRead,
  TenderCalcVersionSummaryRead,
  TenderQuantityDiffRead,
} from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';
import { workspaceCadHref } from '@/lib/cad/workspace-url';

import { DISCIPLINE_ORDER, type TenderDiscipline } from './systems';

/** Представление данных обмена с TENDER: группировка, числа, статусы, ссылки на лист. */

export interface ICalcGroup {
  readonly discipline: TenderDiscipline;
  readonly calcs: readonly TenderCalcRead[];
}

/** Репозитории по разделам в порядке формата; внутри раздела — по системе и названию. */
export const groupCalcs = (calcs: readonly TenderCalcRead[]): readonly ICalcGroup[] =>
  DISCIPLINE_ORDER.map((discipline) => ({
    discipline,
    calcs: calcs
      .filter((calc) => calc.discipline === discipline)
      .sort(
        (a, b) => a.system.localeCompare(b.system, 'ru') || a.title.localeCompare(b.title, 'ru'),
      ),
  })).filter((group) => group.calcs.length > 0);

const QTY = new Intl.NumberFormat('ru', { maximumFractionDigits: 3 });

/** Количество по-русски: «1 234,5». */
export const formatQty = (value: number | null): string =>
  value === null ? '—' : QTY.format(value);

/** Разница со знаком: «+12,5», «−3»; ноль — «0». */
export const formatDelta = (value: number): string => {
  if (value === 0) return '0';
  const text = QTY.format(Math.abs(value));
  return value > 0 ? `+${text}` : `−${text}`;
};

/** Первые 8 знаков sha256: по ним версию сверяют с файлом. */
export const shortSha = (sha: string): string => sha.slice(0, 8);

export type VersionStatus = TenderCalcVersionSummaryRead['status'];

export const VERSION_STATUS_LABELS: Readonly<Record<VersionStatus, string>> = {
  active: 'Действует',
  superseded: 'Заменена',
  withdrawn: 'Отозвана',
};

export const VERSION_STATUS_TONES: Readonly<Record<VersionStatus, BadgeTone>> = {
  active: 'success',
  superseded: 'neutral',
  withdrawn: 'danger',
};

export type DiffStatus = TenderQuantityDiffRead['status'];

export const DIFF_STATUS_LABELS: Readonly<Record<DiffStatus, string>> = {
  added: 'Добавлено',
  removed: 'Удалено',
  changed: 'Изменено',
  same: 'Без изменений',
};

/** Подсветка строки по статусу разницы: токены темы, не цвета. */
export const DIFF_ROW_CLASSES: Readonly<Record<DiffStatus, string>> = {
  added: 'bg-success-soft',
  removed: 'bg-danger-soft',
  changed: 'bg-warning-soft',
  same: '',
};

export const BASIS_LABELS: Readonly<Record<string, string>> = {
  geometry: 'по трассам',
  schedule: 'по спецификации',
  rule: 'по норме',
  assumption: 'допущение',
};

export interface ITenderSheetTarget {
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly view: number;
  /** Позиция листа в рабочей области (с 1); нет — берётся индекс страницы + 1. */
  readonly position?: number;
}

/**
 * Ссылка на вид в рабочей области CAD со слоем «Расчёты» этой версии: тот же адрес, что у остальных
 * ссылок на вид (`workspaceCadHref`), плюс `tender=<calc_id>`. `mode=3d` открывает вид сразу как «3D этажа».
 */
export const tenderSheetHref = (
  projectId: string,
  calcId: string,
  target: ITenderSheetTarget,
  mode: 'plan' | '3d' = 'plan',
): string => {
  const base = workspaceCadHref(projectId, {
    revision: target.revisionId,
    position: target.position ?? target.pageIndex + 1,
    job: null,
    view: null,
  });
  const extra = new URLSearchParams({ view: String(target.view), tender: calcId });
  if (mode === '3d') extra.set('mode', '3d');
  return `${base}&${extra.toString()}`;
};
