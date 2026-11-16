'use client';

import {
  createCadFacadesJob,
  decideCadFacadeViews,
  readCadFacades,
  type FacadesDecide,
  type FacadesJobRead,
  type FacadesRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

import { isFacadesJobActive } from './facades';

/**
 * Фасады ревизии (флаг `cad.export`): последнее задание, кандидаты видов и замечания одним ответом.
 * Пока задание идёт, ответ опрашивается.
 */

export const FACADES_POLL_MS = 3000;

export const facadeKeys = {
  revision: (projectId: string, revisionId: string) =>
    ['cad', projectId, revisionId, 'facades'] as const,
};

export const useCadFacades = (
  projectId: string,
  revisionId: string | null,
  enabled: boolean,
): UseQueryResult<FacadesRead> =>
  useQuery({
    queryKey: facadeKeys.revision(projectId, revisionId ?? ''),
    enabled: enabled && revisionId !== null,
    queryFn: async () =>
      unwrap(
        await readCadFacades({
          throwOnError: true,
          path: { project_id: projectId },
          query: { revision_id: revisionId ?? '' },
        }),
      ),
    refetchInterval: (query) =>
      isFacadesJobActive(query.state.data?.job?.status) ? FACADES_POLL_MS : false,
  });

/** Поставить разбор фасадов по ревизии: страницы не передаются, генератор находит их сам. */
export const useStartCadFacades = (
  projectId: string,
  revisionId: string | null,
): UseMutationResult<FacadesJobRead, unknown, void> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await createCadFacadesJob({
          throwOnError: true,
          path: { project_id: projectId },
          body: { revision_id: revisionId ?? '', page_indexes: null },
        }),
      ),
    onSettled: () =>
      client.invalidateQueries({ queryKey: facadeKeys.revision(projectId, revisionId ?? '') }),
  });
};

export interface IDecideFacades {
  readonly viewIds: readonly string[];
  readonly decision: FacadesDecide['decision'];
}

/** Решение человека по видам: ответ подставляется в кэш по id, затем ответ перечитывается. */
export const useDecideCadFacadeViews = (
  projectId: string,
  revisionId: string | null,
): UseMutationResult<FacadesRead['views'], unknown, IDecideFacades> => {
  const client = useQueryClient();
  const key = facadeKeys.revision(projectId, revisionId ?? '');
  return useMutation({
    mutationFn: async ({ viewIds, decision }) =>
      unwrap(
        await decideCadFacadeViews({
          throwOnError: true,
          path: { project_id: projectId },
          body: { view_ids: [...viewIds], decision },
        }),
      ).views,
    onSuccess: (decided) => {
      client.setQueryData<FacadesRead>(key, (current) =>
        current
          ? {
              ...current,
              views: current.views.map((view) => decided.find((item) => item.id === view.id) ?? view),
            }
          : current,
      );
    },
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  });
};
