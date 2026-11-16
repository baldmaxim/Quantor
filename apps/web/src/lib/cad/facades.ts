import type { FacadeIssueRead, FacadeViewRead } from '@quantor/api-client';

import { formatMark, matchesReviewFilter } from './sections';
import type { ISectionCounts, ReviewFilter } from './sections';

/**
 * Чистые правила вкладки «Фасады» (режим CAD): подписи видов, привязки по отметкам, группировка по
 * страницам. Всё приходит от генератора; клиент ничего не считает - показывает и отправляет решение.
 */

export type FacadeScaleStatus = FacadeViewRead['scale_status'];
export type FacadeViewStatus = FacadeViewRead['status'];

/** Пустое значение не показывается как 0. */
export const EMPTY = '—';

export const facadeScaleText = (view: Pick<FacadeViewRead, 'scale_status' | 'marks'>): string => {
  const used = view.marks.filter((mark) => mark.used === true).length;
  switch (view.scale_status) {
    case 'fitted':
      return used > 0 ? `привязан по ${used} отметкам` : 'привязан по отметкам';
    case 'weak':
      return 'привязан по двум отметкам';
    case 'text_only':
      return 'отметки без знаков: уровни только числами';
    case 'none':
      return 'не привязан';
  }
};

export const facadeBodyText = (body: FacadeViewRead['body']): string =>
  body === 'vector' ? 'векторный' : 'растровый (только отметки)';

const STATUS_LABELS: Readonly<Record<FacadeViewStatus, string>> = {
  candidate: 'Кандидат',
  accepted: 'Принят',
  rejected: 'Отклонён',
};

export const facadeStatusLabel = (status: FacadeViewStatus): string => STATUS_LABELS[status];

/** Вид привязан по отметкам (fitted/weak): только такой можно принять. */
export const isFacadeScaled = (view: Pick<FacadeViewRead, 'scale_status'>): boolean =>
  view.scale_status === 'fitted' || view.scale_status === 'weak';

export const canAcceptFacade = (view: Pick<FacadeViewRead, 'scale_status' | 'status'>): boolean =>
  view.status !== 'accepted' && isFacadeScaled(view);

/** Кандидаты с привязкой по отметкам: что принимает «Принять все». */
export const acceptableFacadeCandidateIds = (views: readonly FacadeViewRead[]): string[] =>
  views.filter((view) => view.status === 'candidate' && isFacadeScaled(view)).map((view) => view.id);

/** Сводка видов по статусам решения. */
export const countFacades = (views: readonly FacadeViewRead[]): ISectionCounts => {
  const count = (status: FacadeViewStatus) => views.filter((view) => view.status === status).length;
  return {
    total: views.length,
    accepted: count('accepted'),
    candidate: count('candidate'),
    rejected: count('rejected'),
  };
};

export const FACADE_ACCEPT_BLOCKED = 'Вид не привязан по отметкам: принять нельзя';

/** Число (мм) или «—». */
export const mmOrEmpty = (value: number | null | undefined): string =>
  value === null || value === undefined ? EMPTY : String(Math.round(value));

/** Отметка со знаком или «—». */
export const markOrEmpty = (value: number | null | undefined): string =>
  value === null || value === undefined ? EMPTY : formatMark(value);

/** Оси вида: «оси 1–8», одна ось - её марка, нет - «—». */
export const facadeAxesText = (view: Pick<FacadeViewRead, 'axis_from' | 'axis_to'>): string => {
  const { axis_from: from, axis_to: to } = view;
  if (from && to) return `оси ${from}–${to}`;
  if (from || to) return `ось ${from ?? to}`;
  return EMPTY;
};

export const facadePlaceText = (view: Pick<FacadeViewRead, 'corps' | 'section'>): string | null => {
  const parts = [
    view.corps ? `корпус ${view.corps}` : null,
    view.section ? `секция ${view.section}` : null,
  ].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(', ') : null;
};

export interface IFacadePageGroup {
  readonly pageIndex: number;
  readonly views: readonly FacadeViewRead[];
}

/** Виды по страницам (по номеру страницы), внутри - по `seq`. */
export const groupFacadesByPage = (views: readonly FacadeViewRead[]): IFacadePageGroup[] => {
  const byPage = new Map<number, FacadeViewRead[]>();
  for (const view of views) {
    byPage.set(view.page_index, [...(byPage.get(view.page_index) ?? []), view]);
  }
  return [...byPage.entries()]
    .sort(([a], [b]) => a - b)
    .map(([pageIndex, items]) => ({
      pageIndex,
      views: [...items].sort((a, b) => a.seq - b.seq),
    }));
};

export interface IFacadeReviewGroup extends IFacadePageGroup {
  /** Группа открытого листа: идёт первой, заголовок «На этом листе». */
  readonly current: boolean;
}

/**
 * Группы видов для списка приёмки: первой - страница открытого листа, затем остальные по номеру
 * страницы; внутри - по `seq`. Фильтр убирает только не подходящие виды и опустевшие группы.
 */
export const facadeReviewGroups = (
  views: readonly FacadeViewRead[],
  currentPageIndex: number | null,
  filter: ReviewFilter = 'all',
): IFacadeReviewGroup[] => {
  const groups = groupFacadesByPage(views)
    .map((group) => ({
      pageIndex: group.pageIndex,
      views: group.views.filter((view) => matchesReviewFilter(view.status, filter)),
      current: group.pageIndex === currentPageIndex,
    }))
    .filter((group) => group.views.length > 0);
  return [...groups.filter((group) => group.current), ...groups.filter((group) => !group.current)];
};

export const facadeIssuesOfPage = (
  issues: readonly FacadeIssueRead[],
  pageIndex: number,
): FacadeIssueRead[] => issues.filter((issue) => issue.page_index === pageIndex);

/** Задание идёт: опрашивать результат. */
export const isFacadesJobActive = (status: string | undefined): boolean =>
  status === 'queued' || status === 'running';
