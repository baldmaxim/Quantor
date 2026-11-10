import type { CadJobSummaryRead } from '@quantor/api-client';

/** Задание - трассы механики по одобренному виду (`cad_mep_route`), а не преобразование листа. */
export const isRouteJob = (job: Pick<CadJobSummaryRead, 'job_type'>): boolean =>
  job.job_type === 'cad_mep_route';

/** Подпись route-задания в списке: «Трассы механики · лист 81, вид 1». */
export const routeJobLabel = (
  job: Pick<CadJobSummaryRead, 'page_index' | 'view'>,
): string => {
  const sheet = job.page_index !== null ? `лист ${job.page_index + 1}` : null;
  const view = job.view !== null ? `вид ${job.view}` : null;
  const place = [sheet, view].filter((part): part is string => part !== null).join(', ');
  return place ? `Трассы механики · ${place}` : 'Трассы механики';
};
