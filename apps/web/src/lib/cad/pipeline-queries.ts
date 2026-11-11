'use client';

import { readCadPipeline, readJob, type CadPipelineRead, type JobRead } from '@quantor/api-client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

import { pipelineHasActive } from './pipeline';

/**
 * Конвейер CAD по листам ревизии: калибровка, преобразование, конструкции, зоны, одобрение,
 * трассы, 3D DXF. Пока хоть один этап в очереди или идёт, ответ опрашивается.
 */

/** Ключ конвейера ревизии: по нему другие экраны сбрасывают ответ после своих действий. */
export const cadPipelineKey = (projectId: string, revisionId: string) =>
  ['cad', projectId, revisionId, 'pipeline'] as const;

export const CAD_PIPELINE_POLL_MS = 3000;

/** Свежесть ответа, в котором ничего не идёт; решения человека сбрасывают его явно. */
const SETTLED_STALE_MS = 15_000;

export const useCadPipeline = (
  projectId: string,
  revisionId: string | null,
  enabled: boolean,
): UseQueryResult<CadPipelineRead> =>
  useQuery({
    queryKey: cadPipelineKey(projectId, revisionId ?? ''),
    enabled: enabled && revisionId !== null,
    queryFn: async () => {
      const pipeline = unwrap(
        await readCadPipeline({
          throwOnError: true,
          path: { project_id: projectId, revision_id: revisionId ?? '' },
        }),
      );
      // Ответ чужой ревизии не показываем: защита сверх ключа запроса.
      if (pipeline.revision_id !== revisionId) {
        throw new Error('Ответ не относится к выбранной ревизии');
      }
      return pipeline;
    },
    staleTime: (query) => (pipelineHasActive(query.state.data) ? 0 : SETTLED_STALE_MS),
    refetchInterval: (query) => (pipelineHasActive(query.state.data) ? CAD_PIPELINE_POLL_MS : false),
  });

/**
 * Общее чтение задания этапа (`GET /jobs/{id}`): подходит любому типу задания конвейера, в том
 * числе конструкциям, зонам и 3D DXF, которых нет в CAD-маршрутах заданий. Грузится только по
 * `enabled` (подробности отказа открыты).
 */
export const useCadStageJob = (
  projectId: string,
  revisionId: string,
  jobId: string,
  enabled: boolean,
): UseQueryResult<JobRead> =>
  useQuery({
    queryKey: ['cad', projectId, revisionId, 'stage-job', jobId] as const,
    enabled,
    queryFn: async () => {
      const job = unwrap(await readJob({ throwOnError: true, path: { job_id: jobId } }));
      if (job.id !== jobId) throw new Error('Ответ не относится к выбранному заданию');
      return job;
    },
  });
