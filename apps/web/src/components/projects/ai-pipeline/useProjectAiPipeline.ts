'use client';

import {
  readProjectAiPipeline,
  runProjectAiStage,
  startCadOutlineReview,
  type AiRunResult,
  type ProjectAiPipelineRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

export const AI_PIPELINE_POLL_MS = 10_000;

export const aiPipelineKey = (projectId: string) => ['project', projectId, 'ai-pipeline'] as const;

/** Этапы проекта; пока есть идущие задания, ответ опрашивается раз в 10 с. */
export const useProjectAiPipeline = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<ProjectAiPipelineRead> =>
  useQuery({
    queryKey: aiPipelineKey(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await readProjectAiPipeline({ throwOnError: true, path: { project_id: projectId } })),
    refetchInterval: (query) => (query.state.data?.active ? AI_PIPELINE_POLL_MS : false),
  });

export const useRunAiStage = (
  projectId: string,
): UseMutationResult<AiRunResult, Error, 'review' | 'verify'> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (stage) =>
      unwrap(
        await runProjectAiStage({
          throwOnError: true,
          path: { project_id: projectId, stage },
        }),
      ),
    onSettled: () => client.invalidateQueries({ queryKey: aiPipelineKey(projectId) }),
  });
};

export interface ICodexRunResult {
  readonly queued: number;
  readonly failed: number;
}

/** Проверка Codex: существующее задание `cad-outline-review` по каждому доступному виду. */
export const useRunCodexReview = (
  projectId: string,
): UseMutationResult<ICodexRunResult, Error, readonly string[]> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (wallsJobIds) => {
      const outcomes = await Promise.allSettled(
        wallsJobIds.map(async (jobId) =>
          unwrap(await startCadOutlineReview({ throwOnError: true, path: { job_id: jobId } })),
        ),
      );
      const failed = outcomes.filter((outcome) => outcome.status === 'rejected').length;
      return { queued: outcomes.length - failed, failed };
    },
    onSettled: () => client.invalidateQueries({ queryKey: aiPipelineKey(projectId) }),
  });
};
