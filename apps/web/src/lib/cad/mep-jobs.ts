import type { CadJobSummaryRead } from '@quantor/api-client';

/** Задание - трассы механики по одобренному виду (`cad_mep_route`), а не преобразование листа. */
export const isRouteJob = (job: Pick<CadJobSummaryRead, 'job_type'>): boolean =>
  job.job_type === 'cad_mep_route';

/**
 * Список заданий без дублей трасс: одно route-задание на вид (новое сверху, его попытки - внутри
 * задания). Преобразования листов не трогаются.
 */
export const dedupeRouteJobs = <T extends Pick<CadJobSummaryRead, 'job_type' | 'parent_job_id' | 'page_index' | 'view'>>(
  jobs: readonly T[],
): T[] => {
  const seen = new Set<string>();
  return jobs.filter((job) => {
    if (!isRouteJob(job)) return true;
    const key = `${job.parent_job_id ?? ''}:${job.page_index ?? ''}:${job.view ?? ''}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
};

/** Подпись route-задания в списке: «Трассы механики · лист 81, вид 1». */
export const routeJobLabel = (
  job: Pick<CadJobSummaryRead, 'page_index' | 'view'>,
): string => {
  const sheet = job.page_index !== null ? `лист ${job.page_index + 1}` : null;
  const view = job.view !== null ? `вид ${job.view}` : null;
  const place = [sheet, view].filter((part): part is string => part !== null).join(', ');
  return place ? `Трассы механики · ${place}` : 'Трассы механики';
};
