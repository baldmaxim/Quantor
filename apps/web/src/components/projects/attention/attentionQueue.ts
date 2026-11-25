import type {
  CadPipelineSheetRead,
  DocCandidateOut,
  DocQuestionOut,
  DocQuestionsOut,
} from '@quantor/api-client';

import { isAutoScaleUnconfirmed } from '@/lib/cad/pipeline';
import { sheetRows } from '@/lib/cad/pipeline-actions';
import { workspaceCadHref } from '@/lib/cad/workspace-url';

/**
 * Очередь прямых вопросов человеку (автопайплайн, S0-B): чистая логика без UI.
 *
 * Приоритет: масштаб CAD не подтвердился -> вопрос к документации с кандидатом (по убыванию
 * оценки) -> вопрос без кандидата. Масштаб здесь не определяется: вопрос только ведёт человека
 * к калибровке.
 */

export const SNOOZE_MS = 24 * 60 * 60 * 1000;
export const AUTO_OPEN_GAP_MS = 2 * 60 * 1000;

export interface IScaleItem {
  readonly kind: 'scale';
  readonly id: string;
  readonly text: string;
  /** Ссылка на калибровку листа в рабочей области. */
  readonly href: string;
}

export interface IDocItem {
  readonly kind: 'doc';
  readonly id: string;
  readonly question: DocQuestionOut;
  /** Лучший живой кандидат; `null` - в документации не найдено. */
  readonly candidate: DocCandidateOut | null;
}

export type AttentionItem = IScaleItem | IDocItem;

export type Snoozed = Readonly<Record<string, number>>;

/** Лучший кандидат: не отклонённый, с наибольшей оценкой. */
export const bestCandidate = (question: DocQuestionOut): DocCandidateOut | null => {
  const alive = question.candidates.filter((candidate) => candidate.status !== 'rejected');
  return alive.reduce<DocCandidateOut | null>(
    (best, candidate) => (best === null || candidate.score > best.score ? candidate : best),
    null,
  );
};

/**
 * «Нет ответа» - у вопроса нет ни одного подтверждённого `DocAnswer` (включая «нет в проекте»).
 * Вопрос без кандидатов задаётся только после завершённого поиска: до него «не найдено» -
 * это ещё не результат.
 */
export const docItems = (data: DocQuestionsOut | undefined): IDocItem[] => {
  if (!data) return [];
  const searched = data.last_search?.status === 'succeeded';
  const items: IDocItem[] = [];
  for (const question of data.questions) {
    if (question.answers.length > 0) continue;
    const candidate = bestCandidate(question);
    if (candidate === null && !searched) continue;
    items.push({ kind: 'doc', id: `doc:${question.code}`, question, candidate });
  }
  return items;
};

export const scaleItem = (
  projectId: string,
  revisionId: string,
  documentName: string,
  sheet: CadPipelineSheetRead,
): IScaleItem | null => {
  if (!isAutoScaleUnconfirmed(sheet)) return null;
  const position = sheet.page_index + 1;
  const link = sheetRows(projectId, revisionId, position, sheet)
    .flatMap((row) => row.actions)
    .find((action) => action.id === 'convert:calibrate');
  const label = sheet.page_label ?? String(position);
  return {
    kind: 'scale',
    id: `scale:${revisionId}:${sheet.page_index}`,
    text: `Лист ${label} (${documentName}): масштаб не подтвердился по размерам - откалибруйте.`,
    href:
      link?.href ??
      workspaceCadHref(projectId, { revision: revisionId, position, job: null, view: null }),
  };
};

export const isSnoozed = (snoozed: Snoozed, id: string, now: number): boolean =>
  (snoozed[id] ?? 0) > now;

export const buildAttentionQueue = (
  scale: readonly IScaleItem[],
  docs: readonly IDocItem[],
  snoozed: Snoozed,
  now: number,
): AttentionItem[] => {
  const score = (item: IDocItem): number => item.candidate?.score ?? 0;
  const withCandidate = docs
    .filter((item) => item.candidate !== null)
    .sort((left, right) => score(right) - score(left));
  const without = docs.filter((item) => item.candidate === null);
  return [...scale, ...withCandidate, ...without].filter(
    (item) => !isSnoozed(snoozed, item.id, now),
  );
};

/* ---------------------------------------------------------------- хранилище */

const snoozeKey = (projectId: string): string => `quantor:attention:snooze:${projectId}`;
const autoOpenKey = (projectId: string): string => `quantor:attention:auto-open:${projectId}`;

const isSnoozedMap = (value: unknown): value is Record<string, number> =>
  typeof value === 'object' &&
  value !== null &&
  !Array.isArray(value) &&
  Object.values(value).every((until) => typeof until === 'number');

/** Отложенные вопросы проекта; истёкшие отбрасываются. Хранилище недоступно - пусто. */
export const readSnoozed = (projectId: string, now: number): Snoozed => {
  try {
    const raw = window.localStorage.getItem(snoozeKey(projectId));
    const parsed: unknown = raw === null ? {} : JSON.parse(raw);
    if (!isSnoozedMap(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter(([, until]) => until > now));
  } catch {
    return {};
  }
};

export const writeSnoozed = (projectId: string, snoozed: Snoozed): void => {
  try {
    window.localStorage.setItem(snoozeKey(projectId), JSON.stringify(snoozed));
  } catch {
    // хранилище недоступно: откладывание живёт до перезагрузки страницы
  }
};

export const readLastAutoOpen = (projectId: string): number => {
  try {
    const value = Number(window.localStorage.getItem(autoOpenKey(projectId)));
    return Number.isFinite(value) ? value : 0;
  } catch {
    return 0;
  }
};

export const writeLastAutoOpen = (projectId: string, at: number): void => {
  try {
    window.localStorage.setItem(autoOpenKey(projectId), String(at));
  } catch {
    // без хранилища ограничение «раз в 2 минуты» держится только пока страница открыта
  }
};
