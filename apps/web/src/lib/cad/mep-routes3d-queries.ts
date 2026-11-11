'use client';

import { readCadMepRoutes3D, type CadMepRoutes3dOut } from '@quantor/api-client';
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { isRouteJob } from './mep-jobs';
import { useCadJobs } from './queries';

/**
 * Трассы механики для 3D-вида этажа (ADR-0036): вершины в мм DXF вида, Z от отметки этажа.
 * Отказы 404 «трасс нет» и «задание старее v7» - не ошибки вида, а состояния `none` и `stale`.
 */

export const ROUTES_NOT_FOUND = 'CAD_ROUTES_NOT_FOUND';
export const ROUTES3D_MISSING = 'CAD_ROUTES3D_MISSING';

export type CadRoutes3dState =
  | { readonly status: 'loading' }
  | { readonly status: 'error' }
  | { readonly status: 'none' }
  | { readonly status: 'stale' }
  | { readonly status: 'ready'; readonly data: CadMepRoutes3dOut };

type Fetched =
  | { readonly status: 'none' }
  | { readonly status: 'stale' }
  | { readonly status: 'ready'; readonly data: CadMepRoutes3dOut };

export interface ICadRoutes3dInput {
  readonly projectId: string;
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly view: number;
  readonly enabled: boolean;
}

export const routes3dKey = (input: Omit<ICadRoutes3dInput, 'enabled'>, latest: string) =>
  [
    'cad-mep',
    'routes3d',
    input.projectId,
    input.revisionId,
    input.pageIndex,
    input.view,
    latest,
  ] as const;

/**
 * Отметка новейшего успешного route-задания листа и вида: job_id, попытка и время завершения.
 * Новая попытка или новое задание меняют отметку, и ключ кэша читает трассы заново.
 */
export const latestRouteMark = (
  jobs: readonly {
    job_id: string;
    job_type: 'cad_pdf_convert' | 'cad_mep_route';
    status: string;
    page_index: number | null;
    view: number | null;
    attempt: number;
    created_at: string;
    finished_at: string | null;
  }[],
  pageIndex: number,
  view: number,
): string => {
  const own = jobs.filter(
    (job) =>
      isRouteJob(job) && job.status === 'succeeded' && job.page_index === pageIndex && job.view === view,
  );
  const timeOf = (job: { created_at: string }): number => {
    const value = Date.parse(job.created_at);
    return Number.isNaN(value) ? 0 : value;
  };
  const best = own.reduce<(typeof own)[number] | null>(
    (acc, job) => (acc === null || timeOf(job) > timeOf(acc) ? job : acc),
    null,
  );
  return best === null ? 'none' : `${best.job_id}:${best.attempt}:${best.finished_at ?? ''}`;
};

export const useCadMepRoutes3d = ({
  projectId,
  revisionId,
  pageIndex,
  view,
  enabled,
}: ICadRoutes3dInput): CadRoutes3dState => {
  // Список заданий общий с рабочей областью (тот же ключ кэша); пока трассы строятся, он опрашивается.
  const jobs = useCadJobs(projectId, enabled ? revisionId : null);
  const latest = useMemo(
    () => latestRouteMark(jobs.data?.items ?? [], pageIndex, view),
    [jobs.data, pageIndex, view],
  );
  const query = useQuery<Fetched>({
    queryKey: routes3dKey({ projectId, revisionId, pageIndex, view }, latest),
    enabled,
    queryFn: async () => {
      try {
        const data = unwrap(
          await readCadMepRoutes3D({
            throwOnError: true,
            path: { project_id: projectId },
            query: { revision_id: revisionId, page_index: pageIndex, view },
          }),
        );
        return { status: 'ready', data };
      } catch (error) {
        const code = extractCode(error);
        if (code === ROUTES_NOT_FOUND) return { status: 'none' };
        if (code === ROUTES3D_MISSING) return { status: 'stale' };
        throw error;
      }
    },
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });

  if (query.data !== undefined) return query.data;
  return query.isError ? { status: 'error' } : { status: 'loading' };
};
