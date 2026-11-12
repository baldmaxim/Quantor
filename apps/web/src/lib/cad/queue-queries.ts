'use client';

import { readCadQueue, type CadQueueRead } from '@quantor/api-client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Очередь исполнителя CAD по проекту: свои задания с местом в очереди и общие счётчики по всем
 * проектам. Пока есть выполняющееся или ожидающее задание, ответ опрашивается часто.
 */

export const CAD_QUEUE_POLL_MS = 3000;
export const CAD_QUEUE_IDLE_POLL_MS = 15_000;

export const cadQueueKey = (projectId: string) => ['cad', projectId, 'queue'] as const;

/** В очереди или идёт хоть одно задание проекта либо исполнитель занят чужими заданиями. */
export const cadQueueHasActive = (data: CadQueueRead | null | undefined): boolean =>
  (data?.items ?? []).some((item) => item.status === 'queued' || item.status === 'running');

export const useCadQueue = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<CadQueueRead> =>
  useQuery({
    queryKey: cadQueueKey(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await readCadQueue({ throwOnError: true, path: { project_id: projectId } })),
    staleTime: (query) => (cadQueueHasActive(query.state.data) ? 0 : CAD_QUEUE_IDLE_POLL_MS),
    refetchInterval: (query) =>
      cadQueueHasActive(query.state.data) ? CAD_QUEUE_POLL_MS : CAD_QUEUE_IDLE_POLL_MS,
  });
