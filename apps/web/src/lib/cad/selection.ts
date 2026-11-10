/**
 * Адрес прежней страницы CAD: `?revision=<uuid>&job=<uuid>&page=<индекс>&view=<n>`. Страницы больше
 * нет, адрес только переводится в рабочую область (`workspace-url.ts`). `page` — индекс страницы
 * PDF с 0, как в API.
 */

import type { CadAttemptRead, CadJobRead } from '@quantor/api-client';

export interface ICadSelection {
  readonly revision: string | null;
  readonly job: string | null;
  readonly page: number | null;
  readonly view: number | null;
}

export const EMPTY_SELECTION: ICadSelection = { revision: null, job: null, page: null, view: null };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const asUuid = (value: string | null): string | null => (value && UUID.test(value) ? value : null);

export const asIndex = (value: string | null): number | null => {
  if (value === null || !/^\d{1,6}$/.test(value)) {
    return null;
  }
  return Number(value);
};

interface IParamsReader {
  get: (name: string) => string | null;
}

/** Разбирает адрес. Невалидные значения отбрасываются, а не угадываются. */
export const parseSelection = (params: IParamsReader): ICadSelection => {
  const revision = asUuid(params.get('revision'));
  if (!revision) {
    return EMPTY_SELECTION;
  }
  const job = asUuid(params.get('job'));
  const page = job ? asIndex(params.get('page')) : null;
  const view = page !== null ? asIndex(params.get('view')) : null;
  // Страница без вида допустима: лист открыт из списка, вид выберет человек в ходе задания.
  return { revision, job, page, view };
};

/** Итоги, при которых у вида есть диагностика (`GET .../views/...` отвечает 200). */
export const READABLE_RESULTS: ReadonlySet<string> = new Set([
  'completed_requires_review',
  'no_cad_review_required',
]);

/** Вид для показа: выбранный, а если выбран только лист — первый вид этого листа в задании. */
export const effectiveView = (
  job: Pick<CadJobRead, 'pages'>,
  page: number | null,
  view: number | null,
): number | null => {
  if (page === null || view !== null) return view;
  const views = job.pages.find((item) => item.index === page)?.views ?? [];
  return views.length > 0 ? Math.min(...views.map((entry) => entry.view)) : null;
};

export type ViewSelectionKind =
  /** Вид не выбран. */
  | 'none'
  /** Диагностика вида выпущена: открывается панель просмотра. */
  | 'panel'
  /** Попытка завершилась отказом: запроса диагностики нет, этапы вида - в ходе попытки. */
  | 'failed'
  /** Просмотр недоступен: другая попытка, вид не найден или результат ещё не выпущен. */
  | 'unavailable';

/**
 * Что показать для выбранного вида. Панель просмотра монтируется только у попытки-результата
 * и только при выпущенном итоге: у попытки с отказом сервер отвечает 409 `CAD_RESULT_NOT_READY`,
 * и запрос туда не уходит вовсе.
 */
export const viewSelectionKind = (
  job: Pick<CadJobRead, 'result_attempt' | 'result_status' | 'pages'>,
  attempt: Pick<CadAttemptRead, 'attempt' | 'outcome'> | null,
  page: number | null,
  view: number | null,
): ViewSelectionKind => {
  if (page === null || view === null) {
    return 'none';
  }
  if (attempt === null) {
    return 'unavailable';
  }
  const failed =
    attempt.outcome === 'failed' ||
    (job.result_attempt === attempt.attempt && job.result_status === 'failed');
  if (failed) {
    return 'failed';
  }
  const exists = job.pages.some(
    (item) => item.index === page && item.views.some((entry) => entry.view === view),
  );
  const readable =
    job.result_attempt === attempt.attempt &&
    job.result_status !== null &&
    READABLE_RESULTS.has(job.result_status);
  return exists && readable ? 'panel' : 'unavailable';
};
