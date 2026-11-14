'use client';

import {
  bulkFrameStatus,
  createFrameNode,
  deleteFrameNode,
  getBuildingFrame,
  patchFrameNode,
  rebuildBuildingFrame,
  type FrameBulkOut,
  type FrameNodeCreate,
  type FrameNodeOut,
  type FrameNodePatch,
  type FrameOut,
  type FrameRebuildOut,
  type NodeStatus,
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
 * Запросы каркаса здания (ADR-0043, С2; флаг `project.consistency`).
 *
 * Один запрос отдаёт узлы, проверки и счётчики планов; любая правка инвалидирует его целиком:
 * проверки зависят от всех узлов сразу.
 */

export const frameKeys = {
  project: (projectId: string) => ['building-frame', projectId] as const,
};

export const useBuildingFrame = (projectId: string, enabled: boolean): UseQueryResult<FrameOut> =>
  useQuery({
    queryKey: frameKeys.project(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await getBuildingFrame({ throwOnError: true, path: { project_id: projectId } })),
  });

const useInvalidate = (projectId: string) => {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: frameKeys.project(projectId) });
};

export const useRebuildFrame = (
  projectId: string,
): UseMutationResult<FrameRebuildOut, unknown, void> => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    mutationFn: async () =>
      unwrap(await rebuildBuildingFrame({ throwOnError: true, path: { project_id: projectId } })),
    onSuccess: invalidate,
  });
};

export interface IPatchFrameNode {
  readonly id: string;
  readonly patch: FrameNodePatch;
}

export const usePatchFrameNode = (
  projectId: string,
): UseMutationResult<FrameNodeOut, unknown, IPatchFrameNode> => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    mutationFn: async ({ id, patch }) =>
      unwrap(
        await patchFrameNode({
          throwOnError: true,
          path: { project_id: projectId, node_id: id },
          body: patch,
        }),
      ),
    onSuccess: invalidate,
  });
};

export interface IBulkFrameStatus {
  readonly ids: readonly string[];
  readonly status: NodeStatus;
}

export const useBulkFrameStatus = (
  projectId: string,
): UseMutationResult<FrameBulkOut, unknown, IBulkFrameStatus> => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    mutationFn: async ({ ids, status }) =>
      unwrap(
        await bulkFrameStatus({
          throwOnError: true,
          path: { project_id: projectId },
          body: { ids: [...ids], status },
        }),
      ),
    onSuccess: invalidate,
  });
};

export const useCreateFrameNode = (
  projectId: string,
): UseMutationResult<FrameNodeOut, unknown, FrameNodeCreate> => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    mutationFn: async (body) =>
      unwrap(await createFrameNode({ throwOnError: true, path: { project_id: projectId }, body })),
    onSuccess: invalidate,
  });
};

export const useDeleteFrameNode = (
  projectId: string,
): UseMutationResult<unknown, unknown, string> => {
  const invalidate = useInvalidate(projectId);
  return useMutation({
    // 204 без тела: `unwrap` здесь не нужен.
    mutationFn: async (id) =>
      deleteFrameNode({ throwOnError: true, path: { project_id: projectId, node_id: id } }),
    onSuccess: invalidate,
  });
};
