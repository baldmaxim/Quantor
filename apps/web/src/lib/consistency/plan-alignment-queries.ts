'use client';

import {
  bulkPlanAlignmentStatus,
  getPlanAlignments,
  startPlanAlign,
  type AlignmentStatus,
  type JobRead,
  type PlanAlignmentBulkOut,
  type PlanAlignmentsOut,
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
 * Запросы совмещения планов с уровнем (ADR-0043, С3; флаг `project.consistency`).
 *
 * Пока задание совмещения идёт, запрос опрашивается. Статус совмещения меняет проверку «план ↔
 * уровень» в каркасе, поэтому подтверждение инвалидирует и совмещения, и каркас.
 */

const JOB_POLL_MS = 2000;

export const alignKeys = {
  project: (projectId: string) => ['plan-alignments', projectId] as const,
};

export const isAlignActive = (data: PlanAlignmentsOut | undefined): boolean =>
  data?.last_run?.status === 'queued' || data?.last_run?.status === 'running';

export const usePlanAlignments = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<PlanAlignmentsOut> =>
  useQuery({
    queryKey: alignKeys.project(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await getPlanAlignments({ throwOnError: true, path: { project_id: projectId } })),
    refetchInterval: (state) => (isAlignActive(state.state.data) ? JOB_POLL_MS : false),
  });

const useInvalidateAll = (projectId: string) => {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: alignKeys.project(projectId) }),
      client.invalidateQueries({ queryKey: frameKeys.project(projectId) }),
    ]);
};

export const useStartPlanAlign = (projectId: string): UseMutationResult<JobRead, unknown, void> => {
  const invalidate = useInvalidateAll(projectId);
  return useMutation({
    mutationFn: async () =>
      unwrap(await startPlanAlign({ throwOnError: true, path: { project_id: projectId } })),
    onSuccess: invalidate,
  });
};

export interface IBulkAlignmentStatus {
  readonly ids: readonly string[];
  readonly status: AlignmentStatus;
}

export const useBulkAlignmentStatus = (
  projectId: string,
): UseMutationResult<PlanAlignmentBulkOut, unknown, IBulkAlignmentStatus> => {
  const invalidate = useInvalidateAll(projectId);
  return useMutation({
    mutationFn: async ({ ids, status }) =>
      unwrap(
        await bulkPlanAlignmentStatus({
          throwOnError: true,
          path: { project_id: projectId },
          body: { ids: [...ids], status },
        }),
      ),
    onSuccess: invalidate,
  });
};
