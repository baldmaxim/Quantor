'use client';

import {
  createCadEomRoutes,
  readCadEomJob,
  readCadEomRoutes3D,
  type CadEomJobRead,
  type CadEomRoutes3dOut,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import type { ICadViewParams } from './view-queries';

/**
 * ЭОМ и СС этажа (генератор `cad_eom`): постановка по одобренному виду, ход задания листа, сети и
 * приборы в 3D с ведомостью. Одобрение вида и уровни - общие с трассами механики.
 */

export const EOM_NOT_FOUND = 'CAD_EOM_NOT_FOUND';
/** Пока задание в очереди или идёт, его состояние опрашивается с этим шагом. */
export const EOM_POLL_MS = 3000;

export interface ICadEomSheet {
  readonly projectId: string;
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly view: number;
}

export const eomKeys = {
  job: (sheet: ICadEomSheet) =>
    ['cad-eom', 'job', sheet.projectId, sheet.revisionId, sheet.pageIndex, sheet.view] as const,
  routes3d: (sheet: ICadEomSheet, mark: string) =>
    ['cad-eom', 'routes3d', sheet.projectId, sheet.revisionId, sheet.pageIndex, sheet.view, mark] as const,
};

const queryOf = (sheet: ICadEomSheet) => ({
  revision_id: sheet.revisionId,
  page_index: sheet.pageIndex,
  view: sheet.view,
});

const isActive = (job: CadEomJobRead | null | undefined): boolean =>
  job != null && (job.status === 'queued' || job.status === 'running');

/** Новейшее задание ЭОМ и СС листа; `null` - ни разу не строились. Пока идёт - опрашивается. */
export const useCadEomJob = (
  sheet: ICadEomSheet,
  enabled: boolean,
): UseQueryResult<CadEomJobRead | null> =>
  useQuery({
    queryKey: eomKeys.job(sheet),
    enabled,
    queryFn: async () => {
      try {
        return unwrap(
          await readCadEomJob({
            throwOnError: true,
            path: { project_id: sheet.projectId },
            query: queryOf(sheet),
          }),
        );
      } catch (error) {
        if (extractCode(error) === EOM_NOT_FOUND) return null;
        throw error;
      }
    },
    refetchInterval: (query) => (isActive(query.state.data) ? EOM_POLL_MS : false),
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });

/** Отметка успешного задания для ключа кэша 3D: новое задание или попытка - чтение заново. */
export const eomMark = (job: CadEomJobRead | null | undefined): string =>
  job && job.status === 'succeeded' ? `${job.job_id}:${job.finished_at ?? ''}` : 'none';

export type CadEomRoutes3dState =
  | { readonly status: 'loading' }
  | { readonly status: 'error' }
  | { readonly status: 'none' }
  | { readonly status: 'ready'; readonly data: CadEomRoutes3dOut };

/** Сети и приборы ЭОМ и СС листа; нет построенных - `none`, это не ошибка вида. */
export const useCadEomRoutes3d = (sheet: ICadEomSheet, enabled: boolean): CadEomRoutes3dState => {
  const job = useCadEomJob(sheet, enabled);
  const mark = eomMark(job.data);
  const query = useQuery<CadEomRoutes3dOut | null>({
    queryKey: eomKeys.routes3d(sheet, mark),
    enabled: enabled && mark !== 'none',
    queryFn: async () => {
      try {
        return unwrap(
          await readCadEomRoutes3D({
            throwOnError: true,
            path: { project_id: sheet.projectId },
            query: queryOf(sheet),
          }),
        );
      } catch (error) {
        if (extractCode(error) === EOM_NOT_FOUND) return null;
        throw error;
      }
    },
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });
  if (mark === 'none') return job.isError ? { status: 'error' } : job.isPending && enabled ? { status: 'loading' } : { status: 'none' };
  if (query.data === null) return { status: 'none' };
  if (query.data !== undefined) return { status: 'ready', data: query.data };
  return query.isError ? { status: 'error' } : { status: 'loading' };
};

/** Построить ЭОМ и СС по одобренному виду (`parent` - задание CAD и попытка вида). */
export const useBuildEom = (
  parent: ICadViewParams,
): UseMutationResult<CadEomJobRead, unknown, void> => {
  const client = useQueryClient();
  const sheet: ICadEomSheet = parent;
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await createCadEomRoutes({
          throwOnError: true,
          path: {
            project_id: parent.projectId,
            revision_id: parent.revisionId,
            job_id: parent.jobId,
            page_index: parent.pageIndex,
            view: parent.view,
          },
          body: { attempt: parent.attempt, floor_elevation_mm: null, floor_height_mm: null },
        }),
      ),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: eomKeys.job(sheet) });
    },
  });
};
