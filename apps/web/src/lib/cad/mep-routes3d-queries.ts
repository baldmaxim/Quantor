'use client';

import {
  readCadMepRoutes3D,
  type CadJobSummaryRead,
  type CadMepRoutes3dOut,
} from '@quantor/api-client';
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { useCadJobs } from './queries';
import { pickAutoRoute } from './route-autoselect';

/**
 * Трассы механики для 3D-вида этажа (ADR-0036): вершины в мм DXF вида, Z от отметки этажа.
 * Отказы 404 «трасс нет» и «задание старее v7» - не ошибки вида, а состояния `none` и `stale`.
 *
 * Один источник: 3D читает то же route-задание, что рисует план и считает итоги (`job_id` в
 * запросе). План и 3D - только отображение одного расчёта, своего выбора трасс у 3D нет.
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
  /** Задание листа (CAD-родитель трасс): по нему автовыбор, когда `routeJobId` не задан. */
  readonly parentJobId: string;
  /**
   * Route-задание, которое показывает план (выбор человека или автовыбор плана): 3D читает его же.
   * `null` - на плане трасс нет, и в 3D их нет. Не задано (страница объекта, плана рядом нет) -
   * тот же автовыбор, что у плана: новейшее задание вида у задания листа.
   */
  readonly routeJobId?: string | null;
  readonly enabled: boolean;
}

export const routes3dKey = (
  input: Pick<ICadRoutes3dInput, 'projectId' | 'revisionId' | 'pageIndex' | 'view'>,
  mark: string,
) => ['cad-mep', 'routes3d', input.projectId, input.revisionId, input.pageIndex, input.view, mark] as const;

/**
 * Отметка route-задания для ключа кэша: id, статус, попытка и время завершения. Пересчёт новой
 * попыткой или завершение задания меняют отметку, и трассы читаются заново. Задания нет в списке
 * листа - отметка из одного id (сервер всё равно читает именно его).
 */
export const routeMark = (
  jobs: readonly Pick<CadJobSummaryRead, 'job_id' | 'status' | 'attempt' | 'finished_at'>[],
  jobId: string,
): string => {
  const job = jobs.find((item) => item.job_id === jobId);
  return job ? `${job.job_id}:${job.status}:${job.attempt}:${job.finished_at ?? ''}` : jobId;
};

export const useCadMepRoutes3d = ({
  projectId,
  revisionId,
  pageIndex,
  view,
  parentJobId,
  routeJobId,
  enabled,
}: ICadRoutes3dInput): CadRoutes3dState => {
  // Задания листа - тот же запрос и кэш, что у плана; пока трассы строятся, он опрашивается.
  const jobs = useCadJobs(projectId, enabled ? revisionId : null, pageIndex);
  const items = useMemo(() => jobs.data?.items ?? [], [jobs.data]);
  const auto = routeJobId === undefined;
  const jobId = useMemo<string | null>(
    () =>
      routeJobId === undefined
        ? (pickAutoRoute(items, { parentJobId, pageIndex, view })?.job_id ?? null)
        : routeJobId,
    [items, parentJobId, pageIndex, view, routeJobId],
  );
  const mark = jobId === null ? 'none' : routeMark(items, jobId);
  const query = useQuery<Fetched>({
    queryKey: routes3dKey({ projectId, revisionId, pageIndex, view }, mark),
    enabled: enabled && jobId !== null,
    queryFn: async () => {
      if (jobId === null) return { status: 'none' };
      try {
        const data = unwrap(
          await readCadMepRoutes3D({
            throwOnError: true,
            path: { project_id: projectId },
            query: { revision_id: revisionId, page_index: pageIndex, view, job_id: jobId },
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

  if (!enabled) return { status: 'loading' };
  if (jobId === null) {
    if (auto && jobs.isPending) return { status: 'loading' };
    return auto && jobs.isError ? { status: 'error' } : { status: 'none' };
  }
  if (query.data !== undefined) return query.data;
  return query.isError ? { status: 'error' } : { status: 'loading' };
};
