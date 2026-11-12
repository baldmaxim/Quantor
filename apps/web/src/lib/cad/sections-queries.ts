'use client';

import {
  createCadSectionsJob,
  decideCadSectionLevels,
  readCadSections,
  type SectionsDecide,
  type SectionsJobRead,
  type SectionsRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

import { isSectionsJobActive } from './sections';

/**
 * Разрезы ревизии (флаг `cad.export`): последнее задание, кандидаты уровней, замечания и страницы
 * разрезов одним ответом. Пока задание идёт, ответ опрашивается.
 */

export const SECTIONS_POLL_MS = 3000;

export const sectionKeys = {
  revision: (projectId: string, revisionId: string) =>
    ['cad', projectId, revisionId, 'sections'] as const,
};

export const useCadSections = (
  projectId: string,
  revisionId: string | null,
  enabled: boolean,
): UseQueryResult<SectionsRead> =>
  useQuery({
    queryKey: sectionKeys.revision(projectId, revisionId ?? ''),
    enabled: enabled && revisionId !== null,
    queryFn: async () =>
      unwrap(
        await readCadSections({
          throwOnError: true,
          path: { project_id: projectId },
          query: { revision_id: revisionId ?? '' },
        }),
      ),
    refetchInterval: (query) =>
      isSectionsJobActive(query.state.data?.job?.status) ? SECTIONS_POLL_MS : false,
  });

/** Поставить распознавание разрезов: вся ревизия или выбранные страницы (индексы с 0). */
export const useStartCadSections = (
  projectId: string,
  revisionId: string | null,
): UseMutationResult<SectionsJobRead, unknown, readonly number[] | null> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (pageIndexes) =>
      unwrap(
        await createCadSectionsJob({
          throwOnError: true,
          path: { project_id: projectId },
          body: {
            revision_id: revisionId ?? '',
            ...(pageIndexes !== null ? { page_indexes: [...pageIndexes] } : {}),
          },
        }),
      ),
    onSettled: () =>
      client.invalidateQueries({ queryKey: sectionKeys.revision(projectId, revisionId ?? '') }),
  });
};

export interface IDecideLevels {
  readonly levelIds: readonly string[];
  readonly decision: SectionsDecide['decision'];
}

/**
 * Решение человека по уровням. Ответ сразу подставляется в кэш (по id), затем ответ перечитывается:
 * на принятое сервер опирается запуск трасс, и расхождения с базой быть не должно.
 */
export const useDecideCadSectionLevels = (
  projectId: string,
  revisionId: string | null,
): UseMutationResult<SectionsRead['levels'], unknown, IDecideLevels> => {
  const client = useQueryClient();
  const key = sectionKeys.revision(projectId, revisionId ?? '');
  return useMutation({
    mutationFn: async ({ levelIds, decision }) =>
      unwrap(
        await decideCadSectionLevels({
          throwOnError: true,
          path: { project_id: projectId },
          body: { level_ids: [...levelIds], decision },
        }),
      ).levels,
    onSuccess: (decided) => {
      client.setQueryData<SectionsRead>(key, (current) =>
        current
          ? {
              ...current,
              levels: current.levels.map(
                (level) => decided.find((item) => item.id === level.id) ?? level,
              ),
            }
          : current,
      );
    },
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  });
};
