import type { CadJobSummaryRead } from '@quantor/api-client';

import { isRouteJob } from './mep-jobs';

/**
 * Автовыбор route-задания (трассы механики) для открытого листа: слои «Трассы механики» должны
 * появляться сами, как только трассы построены, без захода во вкладку «Трассы».
 */

type RouteCandidate = Pick<
  CadJobSummaryRead,
  'job_id' | 'job_type' | 'parent_job_id' | 'page_index' | 'view' | 'status' | 'created_at'
>;

export interface IAutoRouteScope {
  /** Показанное задание-родитель (вид, под которым рисуются трассы). */
  readonly parentJobId: string | null;
  readonly pageIndex: number | null;
  readonly view: number | null;
}

const timeOf = (job: Pick<CadJobSummaryRead, 'created_at'>): number => {
  const value = Date.parse(job.created_at);
  return Number.isNaN(value) ? 0 : value;
};

const newest = <T extends RouteCandidate>(jobs: readonly T[]): T | null =>
  jobs.reduce<T | null>((best, job) => (best === null || timeOf(job) > timeOf(best) ? job : best), null);

/**
 * Самое новое успешное route-задание показанного вида листа; если успешных нет - самое новое
 * вообще (виден ход построения). Другой лист, родитель или вид не подходят: трассы лягут
 * на чужой DXF. Явный выбор человека (задание в адресе) решает вызывающий и автовыбор не зовёт.
 */
export const pickAutoRoute = <T extends RouteCandidate>(
  jobs: readonly T[],
  { parentJobId, pageIndex, view }: IAutoRouteScope,
): T | null => {
  if (parentJobId === null || pageIndex === null || view === null) return null;
  const own = jobs.filter(
    (job) =>
      isRouteJob(job) &&
      job.parent_job_id === parentJobId &&
      job.page_index === pageIndex &&
      job.view === view,
  );
  return newest(own.filter((job) => job.status === 'succeeded')) ?? newest(own);
};
