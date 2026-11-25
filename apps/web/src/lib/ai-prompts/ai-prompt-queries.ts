'use client';

import {
  activateAiPrompt,
  aiPromptStats,
  createAiPrompt,
  getAiPrompt,
  listAiPrompts,
  type AiPromptCreate,
  type AiPromptRead,
  type AiPromptStats,
  type AiPromptSummary,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/** Версии промтов ИИ-проверки и статистика прогонов (админка, право `system.admin`). */

export type AiPromptRole = 'corrector' | 'verifier';

export const AI_PROMPT_ROLE_LABEL: Readonly<Record<AiPromptRole, string>> = {
  corrector: 'Правщик',
  verifier: 'Проверщик',
};

const ROOT = ['ai-prompts'] as const;

export const useAiPromptList = (role: AiPromptRole): UseQueryResult<AiPromptSummary[]> =>
  useQuery({
    queryKey: [...ROOT, 'list', role],
    queryFn: async () => unwrap(await listAiPrompts({ throwOnError: true, query: { role } })),
    retry: false,
  });

export const useAiPrompt = (id: string | null): UseQueryResult<AiPromptRead> =>
  useQuery({
    queryKey: [...ROOT, 'one', id],
    queryFn: async () =>
      unwrap(await getAiPrompt({ throwOnError: true, path: { prompt_id: id ?? '' } })),
    enabled: id !== null,
    retry: false,
  });

export const useAiPromptStats = (): UseQueryResult<AiPromptStats> =>
  useQuery({
    queryKey: [...ROOT, 'stats'],
    queryFn: async () => unwrap(await aiPromptStats({ throwOnError: true })),
    retry: false,
  });

export const useCreateAiPrompt = (): UseMutationResult<AiPromptRead, Error, AiPromptCreate> => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: AiPromptCreate) =>
      unwrap(await createAiPrompt({ throwOnError: true, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ROOT }),
  });
};

export const useActivateAiPrompt = (): UseMutationResult<AiPromptRead, Error, string> => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (promptId: string) =>
      unwrap(await activateAiPrompt({ throwOnError: true, path: { prompt_id: promptId } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ROOT }),
  });
};
