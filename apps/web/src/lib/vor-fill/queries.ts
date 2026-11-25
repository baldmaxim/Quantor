'use client';

import {
  exportVorFill,
  readVorAiMap,
  readVorFill,
  startVorAiMap,
  type AiVorMapRead,
  type VorFillExportRead,
  type VorFillRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { vorKeys } from '@/lib/cad/vor-queries';
import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

/**
 * Заполнение ВОР (флаг `cad.export`). Ключи лежат под `['cad-vor', projectId]`: смена связей
 * позиций ВОР (`usePutCadVorLinks`) инвалидирует сравнение вместе с остальным ВОР.
 */

export const vorFillKey = (projectId: string) => [...vorKeys.all(projectId), 'fill'] as const;

const retryNetworkOnly = (count: number, error: unknown): boolean =>
  extractCode(error) === 'NETWORK_ERROR' && count < 2;

/** Сравнение количеств: на сервере обходит все листы проекта, поэтому не обновляется само. */
export const useVorFill = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<VorFillRead, unknown> =>
  useQuery({
    queryKey: vorFillKey(projectId),
    enabled,
    staleTime: 60_000,
    queryFn: async () =>
      unwrap(await readVorFill({ throwOnError: true, path: { project_id: projectId } })),
    retry: retryNetworkOnly,
  });

/** Выгрузка копии формы Заказчика с колонками Quantor; файл отдаёт ссылка из ответа. */
export const useExportVorFill = (
  projectId: string,
): UseMutationResult<VorFillExportRead, unknown, void> => {
  return useMutation({
    mutationFn: async () =>
      unwrap(await exportVorFill({ throwOnError: true, path: { project_id: projectId } })),
  });
};

export const vorAiMapKey = (projectId: string) => [...vorKeys.all(projectId), 'ai-map'] as const;

const AI_MAP_POLL_MS = 5_000;

/** ИИ-сопоставление: последнее задание проекта; пока оно идёт, состояние читается раз в 5 с. */
export const useVorAiMap = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<AiVorMapRead, unknown> =>
  useQuery({
    queryKey: vorAiMapKey(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await readVorAiMap({ throwOnError: true, path: { project_id: projectId } })),
    refetchInterval: (query) =>
      query.state.data?.status === 'queued' || query.state.data?.status === 'running'
        ? AI_MAP_POLL_MS
        : false,
    retry: retryNetworkOnly,
  });

/** Запуск сопоставления (пилот, `cad.export`); идущее задание не дублируется на сервере. */
export const useStartVorAiMap = (
  projectId: string,
): UseMutationResult<AiVorMapRead, unknown, void> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(await startVorAiMap({ throwOnError: true, path: { project_id: projectId } })),
    onSettled: () => void client.invalidateQueries({ queryKey: vorAiMapKey(projectId) }),
  });
};
