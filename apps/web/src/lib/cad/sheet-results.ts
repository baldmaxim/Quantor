import type { CadJobSummaryRead } from '@quantor/api-client';

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
