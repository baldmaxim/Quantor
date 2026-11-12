'use client';

import {
  getDocQuestions,
  putDocAnswer,
  rejectDocCandidate,
  removeDocAnswer,
  startDocQuestionsSearch,
  type DocQuestionCode,
  type DocQuestionsOut,
  type JobRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

import type { DocAnswerBody } from './doc-questions';

/**
 * Запросы «Вопросов к документации» (ADR-0043, шаг 2, В4; флаг `project.consistency`).
 *
 * Один запрос отдаёт вопросы, кандидатов, ответы и итог последнего поиска. Пока задание поиска
 * идёт, запрос опрашивается; последний опрос уже приносит готовых кандидатов.
 */

const JOB_POLL_MS = 2000;

export const docQuestionKeys = {
  project: (projectId: string) => ['doc-questions', projectId] as const,
};

export const isSearchActive = (data: DocQuestionsOut | undefined): boolean =>
  data?.last_search?.status === 'queued' || data?.last_search?.status === 'running';

export const useDocQuestions = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<DocQuestionsOut> =>
  useQuery({
    queryKey: docQuestionKeys.project(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await getDocQuestions({ throwOnError: true, path: { project_id: projectId } })),
    refetchInterval: (state) => (isSearchActive(state.state.data) ? JOB_POLL_MS : false),
  });

export const useStartDocSearch = (projectId: string): UseMutationResult<JobRead, unknown, void> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await startDocQuestionsSearch({ throwOnError: true, path: { project_id: projectId } }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: docQuestionKeys.project(projectId) }),
  });
};

export interface ISaveDocAnswer {
  /** Код вопроса из выдачи каталога. */
  readonly code: string;
  readonly body: DocAnswerBody;
}

export const useSaveDocAnswer = (
  projectId: string,
): UseMutationResult<unknown, unknown, ISaveDocAnswer> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ code, body }) =>
      unwrap(
        await putDocAnswer({
          throwOnError: true,
          // Код пришёл из каталога сервера; неизвестный сервер отклонит 422.
          path: { project_id: projectId, code: code as DocQuestionCode },
          body,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: docQuestionKeys.project(projectId) }),
  });
};

export const useRemoveDocAnswer = (
  projectId: string,
): UseMutationResult<unknown, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (answerId: string) =>
      removeDocAnswer({
        throwOnError: true,
        path: { project_id: projectId, answer_id: answerId },
      }),
    onSuccess: () => client.invalidateQueries({ queryKey: docQuestionKeys.project(projectId) }),
  });
};

export const useRejectDocCandidate = (
  projectId: string,
): UseMutationResult<unknown, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (candidateId: string) =>
      unwrap(
        await rejectDocCandidate({
          throwOnError: true,
          path: { project_id: projectId, candidate_id: candidateId },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: docQuestionKeys.project(projectId) }),
  });
};
