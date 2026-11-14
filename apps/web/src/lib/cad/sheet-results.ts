import type { CadJobSummaryRead, CadPipelineSheetRead } from '@quantor/api-client';

import { READABLE_RESULTS } from './selection';

/**
 * Что известно о листе по заданиям ревизии: берётся самое новое задание, в котором лист есть.
 * Задания трасс механики (`cad_mep_route`) не считаются.
 * `recognized` — итог выпущен (DXF или только диагностика), `running` — в очереди или идёт,
 * `failed` — отказ, ошибка или отмена.
 */
export type SheetResultKind = 'recognized' | 'running' | 'failed';

export interface ISheetResult {
  readonly jobId: string;
  readonly kind: SheetResultKind;
  /** Вид для открытия: сводка задания видов не содержит, поэтому сейчас всегда `null`. */
  readonly view: number | null;
  /** DXF выпущен (итог `completed_requires_review`); иначе только диагностика. */
  readonly dxf: boolean;
}

export type JobForSheets = Pick<
  CadJobSummaryRead,
  'job_id' | 'status' | 'result_status' | 'requested_pages' | 'created_at'
> &
  Partial<Pick<CadJobSummaryRead, 'job_type'>>;

/** Вид итога задания; `null` - задание завершено без понятного итога. */
export const jobResultKind = (job: JobForSheets): SheetResultKind | null => {
  if (job.status === 'queued' || job.status === 'running') {
    return 'running';
  }
  if (job.status === 'failed' || job.status === 'cancelled') {
    return 'failed';
  }
  if (job.result_status === 'failed') {
    return 'failed';
  }
  if (job.result_status !== null && READABLE_RESULTS.has(job.result_status)) {
    return 'recognized';
  }
  return null;
};

const timeOf = (job: JobForSheets): number => {
  const value = Date.parse(job.created_at);
  return Number.isNaN(value) ? 0 : value;
};

/**
 * Карта «индекс страницы → последний результат». Страницы задания — `requested_pages`:
 * задание без перечня («все плановые») лист не привязывает, так как сводка не говорит какие.
 * Задание без понятного итога (завершено без `result_status`) в карту не попадает.
 */
export const latestSheetJobs = (jobs: readonly JobForSheets[]): Map<number, ISheetResult> => {
  const newest = new Map<number, JobForSheets>();
  for (const job of jobs) {
    // Трассы механики - надстройка над видом, а не итог преобразования листа.
    if (job.job_type === 'cad_mep_route') continue;
    for (const page of job.requested_pages ?? []) {
      const current = newest.get(page);
      if (current === undefined || timeOf(job) > timeOf(current)) {
        newest.set(page, job);
      }
    }
  }

  const result = new Map<number, ISheetResult>();
  newest.forEach((job, page) => {
    const kind = jobResultKind(job);
    if (kind !== null) {
      result.set(page, {
        jobId: job.job_id,
        kind,
        view: null,
        dxf: job.result_status === 'completed_requires_review',
      });
    }
  });
  return result;
};

const toSheetResult = (job: JobForSheets, kind: SheetResultKind): ISheetResult => ({
  jobId: job.job_id,
  kind,
  view: null,
  dxf: job.result_status === 'completed_requires_review',
});

/**
 * Задания листа для показа: `shown` - самое новое с итогом `recognized`, а без него - самое новое
 * задание листа; `update` - более новое задание после показываемого (идёт или упало), иначе `null`.
 * Старый готовый CAD листа не пропадает, пока новый прогон в очереди, идёт или упал.
 * Трассы механики не считаются; задание без понятного итога обновлением не бывает.
 */
export const sheetJobsForPage = <T extends JobForSheets>(
  jobs: readonly T[],
  page: number,
): { readonly shown: T | null; readonly update: T | null } => {
  let newest: T | null = null;
  let ready: T | null = null;
  for (const job of jobs) {
    if (job.job_type === 'cad_mep_route' || !(job.requested_pages ?? []).includes(page)) continue;
    if (newest === null || timeOf(job) > timeOf(newest)) newest = job;
    if (jobResultKind(job) === 'recognized' && (ready === null || timeOf(job) > timeOf(ready))) {
      ready = job;
    }
  }
  const shown = ready ?? newest;
  const update =
    newest !== null && newest !== shown && jobResultKind(newest) !== null ? newest : null;
  return { shown, update };
};

/**
 * Карта «индекс страницы → показываемый результат» (см. `sheetJobsForPage`): лист с готовым
 * прогоном и идущим или упавшим обновлением остаётся готовым.
 */
export const shownSheetJobs = (jobs: readonly JobForSheets[]): Map<number, ISheetResult> => {
  const pages = new Set<number>();
  for (const job of jobs) {
    if (job.job_type !== 'cad_mep_route') (job.requested_pages ?? []).forEach((p) => pages.add(p));
  }
  const result = new Map<number, ISheetResult>();
  pages.forEach((page) => {
    const { shown } = sheetJobsForPage(jobs, page);
    const kind = shown ? jobResultKind(shown) : null;
    if (shown && kind !== null) result.set(page, toSheetResult(shown, kind));
  });
  return result;
};

/**
 * Листы с готовым DXF для ярлыка «CAD» в списке листов. Источник - конвейер ревизии: он видит все
 * задания листов, а список заданий ревизии ограничен 20 новейшими, и трассы механики вытесняют из
 * него преобразования. `convert` конвейера - показываемый прогон листа; «только диагностика» не в счёт.
 */
export const readyDxfPages = (
  sheets: readonly Pick<CadPipelineSheetRead, 'page_index' | 'convert'>[],
): ReadonlySet<number> =>
  new Set(
    sheets.flatMap((row) =>
      row.convert?.result_status === 'completed_requires_review' ? [row.page_index] : [],
    ),
  );
