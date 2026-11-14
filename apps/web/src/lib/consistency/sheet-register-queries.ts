'use client';

import {
  bulkSheetRegisterStatus,
  getSheetRegisters,
  startSheetRegisterExtract,
  type JobRead,
  type RegisterStatus,
  type SheetRegisterBulkOut,
  type SheetRegistersOut,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

import { frameKeys } from './building-frame-queries';

/**
 * Запросы ведомостей листов (ADR-0043, С2, «ведомость ↔ листы»; флаг `project.consistency`).
 *
 * Пока задание разбора идёт, запрос опрашивается. Статус ведомости меняет проверки каркаса,
 * поэтому подтверждение инвалидирует и ведомости, и каркас; конец разбора — тоже.
 */

const JOB_POLL_MS = 2000;

export const registerKeys = {
  project: (projectId: string) => ['sheet-registers', projectId] as const,
};

export const isExtractActive = (data: SheetRegistersOut | undefined): boolean =>
  data?.last_extract?.status === 'queued' || data?.last_extract?.status === 'running';

export const useSheetRegisters = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<SheetRegistersOut> =>
  useQuery({
    queryKey: registerKeys.project(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await getSheetRegisters({ throwOnError: true, path: { project_id: projectId } })),
    refetchInterval: (state) => (isExtractActive(state.state.data) ? JOB_POLL_MS : false),
  });

const useInvalidateAll = (projectId: string) => {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: registerKeys.project(projectId) }),
      client.invalidateQueries({ queryKey: frameKeys.project(projectId) }),
    ]);
};

export const useStartRegisterExtract = (
  projectId: string,
): UseMutationResult<JobRead, unknown, void> => {
  const invalidate = useInvalidateAll(projectId);
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await startSheetRegisterExtract({ throwOnError: true, path: { project_id: projectId } }),
      ),
    onSuccess: invalidate,
  });
};

export interface IBulkRegisterStatus {
  readonly ids: readonly string[];
  readonly status: RegisterStatus;
}

export const useBulkRegisterStatus = (
  projectId: string,
): UseMutationResult<SheetRegisterBulkOut, unknown, IBulkRegisterStatus> => {
  const invalidate = useInvalidateAll(projectId);
  return useMutation({
    mutationFn: async ({ ids, status }) =>
      unwrap(
        await bulkSheetRegisterStatus({
          throwOnError: true,
          path: { project_id: projectId },
          body: { ids: [...ids], status },
        }),
      ),
    onSuccess: invalidate,
  });
};
