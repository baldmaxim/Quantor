'use client';

import {
  readCadQueue,
  readCadSummary,
  type CadProjectSummaryRead,
  type CadQueueRead,
} from '@quantor/api-client';
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

export const useCadQueue = (projectId: string, enabled: boolean): UseQueryResult<CadQueueRead> =>
  useQuery({
    queryKey: cadQueueKey(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await readCadQueue({ throwOnError: true, path: { project_id: projectId } })),
    staleTime: (query) => (cadQueueHasActive(query.state.data) ? 0 : CAD_QUEUE_IDLE_POLL_MS),
    refetchInterval: (query) =>
      cadQueueHasActive(query.state.data) ? CAD_QUEUE_POLL_MS : CAD_QUEUE_IDLE_POLL_MS,
  });

export const cadSummaryKey = (projectId: string) => ['cad', projectId, 'summary'] as const;

/**
 * Сводка распознавания чертежей проекта: листы готово / идёт / ошибка / не запускалось.
 * Пока хоть один лист в работе, ответ опрашивается как очередь, иначе - редко.
 */
// Сводка читает задания всего проекта — опрашиваем реже очереди.
const CAD_SUMMARY_POLL_MS = 10_000;
const CAD_SUMMARY_IDLE_POLL_MS = 60_000;

export const useCadSummary = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<CadProjectSummaryRead> =>
  useQuery({
    queryKey: cadSummaryKey(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await readCadSummary({ throwOnError: true, path: { project_id: projectId } })),
    staleTime: (query) =>
      (query.state.data?.sheets_running ?? 0) > 0 ? 0 : CAD_QUEUE_IDLE_POLL_MS,
    refetchInterval: (query) =>
      (query.state.data?.sheets_running ?? 0) > 0 ? CAD_SUMMARY_POLL_MS : CAD_SUMMARY_IDLE_POLL_MS,
  });
