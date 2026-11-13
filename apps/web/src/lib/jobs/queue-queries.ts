'use client';

import {
  cancelAdminJobs,
  listAdminJobs,
  type AdminJobsCancelRequest,
  type AdminJobsCancelResult,
  type AdminJobRead,
  type PageAdminJobRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Очередь заданий по всем проектам (ожидающие и выполняющиеся) и её отмена.
 * Пока в очереди что-то есть, ответ опрашивается часто, иначе - редко.
 */

export const JOB_QUEUE_POLL_MS = 3000;
export const JOB_QUEUE_IDLE_POLL_MS = 15_000;

/** Предел страницы API (`MAX_PAGE_SIZE`): очередь запрашивается одной страницей. */
export const JOB_QUEUE_LIMIT = 500;

export const jobQueueKey = (projectId?: string) => ['jobs', 'queue', projectId ?? 'all'] as const;

export const useJobQueue = (projectId?: string): UseQueryResult<PageAdminJobRead> =>
  useQuery({
    queryKey: jobQueueKey(projectId),
    queryFn: async () =>
      unwrap(
        await listAdminJobs({
          throwOnError: true,
          query: { active: true, limit: JOB_QUEUE_LIMIT, project_id: projectId },
        }),
      ),
    // Отказ в правах (не системный администратор) повторами не лечится.
    retry: false,
    staleTime: (query) => ((query.state.data?.items.length ?? 0) > 0 ? 0 : JOB_QUEUE_IDLE_POLL_MS),
    refetchInterval: (query) =>
      (query.state.data?.items.length ?? 0) > 0 ? JOB_QUEUE_POLL_MS : JOB_QUEUE_IDLE_POLL_MS,
  });

export const useCancelJobs = (): UseMutationResult<
  AdminJobsCancelResult,
  Error,
  AdminJobsCancelRequest
> => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (body: AdminJobsCancelRequest) =>
      unwrap(await cancelAdminJobs({ throwOnError: true, body })),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['jobs', 'queue'] }),
        // Очередь CAD проекта, сводка распознавания и прочее под ключом 'cad'.
        queryClient.invalidateQueries({ queryKey: ['cad'] }),
      ]);
    },
  });
};

/** Сколько заданий выполняется и ждёт в загруженном списке. */
export const queueCounts = (
  items: readonly AdminJobRead[],
): { readonly running: number; readonly queued: number } => ({
  running: items.filter((job) => job.status === 'running').length,
  queued: items.filter((job) => job.status === 'queued').length,
});
