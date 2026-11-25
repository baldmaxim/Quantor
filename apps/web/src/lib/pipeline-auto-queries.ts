'use client';

import { readPipelineAuto, type PipelineAutoState } from '@quantor/api-client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/** Включён ли автопайплайн для проекта (пилот): от этого зависят прямые вопросы человеку. */
export const useProjectPipelineAuto = (projectId: string): UseQueryResult<PipelineAutoState> =>
  useQuery({
    queryKey: ['project', projectId, 'pipeline-auto'] as const,
    queryFn: async () =>
      unwrap(await readPipelineAuto({ throwOnError: true, path: { project_id: projectId } })),
    // Настройка меняется только перезапуском сервера.
    staleTime: 5 * 60_000,
  });
