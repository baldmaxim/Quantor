'use client';

import {
  createCalcInspection,
  getCalcRun,
  getCalcRunTrace,
  getCalcSynthesisGraph,
  getCalcSynthesisRun,
  getCalcSynthesisTrace,
  listCalcDocuments,
  listCalcFactTypes,
  listCalcInputFacts,
  listCalcLegacyRules,
  listCalcRules,
  listCalcRuns,
  listCalcSynthesisRuns,
  readCalcReadiness,
  type CalcInspectionCreate,
} from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Запросы экрана «Расчёты → Исходные данные». Закрыты флагом и не выполняются, пока экран
 * скрыт. Ключи проекта начинаются с общего префикса: сбор фактов меняет и готовность, и
 * таблицу фактов, и список документов — сбрасываются все разом.
 */

export const calcQueryKeys = {
  project: (projectId: string) => ['project', projectId, 'calc'] as const,
  documents: (projectId: string) => ['project', projectId, 'calc', 'documents'] as const,
  readiness: (projectId: string) => ['project', projectId, 'calc', 'readiness'] as const,
  inputFacts: (projectId: string, limit: number) =>
    ['project', projectId, 'calc', 'input-facts', limit] as const,
  factTypes: ['calc', 'fact-types'] as const,
  rules: ['calc', 'rules'] as const,
  runs: (projectId: string) => ['project', projectId, 'calc', 'runs'] as const,
  run: (runId: string) => ['calc', 'run', runId] as const,
  trace: (runId: string, resultKey: string) => ['calc', 'run', runId, 'trace', resultKey] as const,
  synthesisRuns: (projectId: string) => ['project', projectId, 'calc', 'synthesis'] as const,
  synthesisRun: (runId: string) => ['calc', 'synthesis', runId] as const,
  synthesisTrace: (runId: string, elementId: string) =>
    ['calc', 'synthesis', runId, 'trace', elementId] as const,
  legacyRules: ['calc', 'legacy-rules'] as const,
};

export const useCalcDocuments = (projectId: string, enabled: boolean) =>
  useQuery({
    queryKey: calcQueryKeys.documents(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await listCalcDocuments({ throwOnError: true, path: { project_id: projectId } })),
  });

export const useCalcReadiness = (projectId: string, enabled: boolean) =>
  useQuery({
    queryKey: calcQueryKeys.readiness(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await readCalcReadiness({ throwOnError: true, path: { project_id: projectId } })),
  });

export const useCalcInputFacts = (projectId: string, enabled: boolean, limit: number) =>
  useQuery({
    queryKey: calcQueryKeys.inputFacts(projectId, limit),
    enabled,
    queryFn: async () =>
      unwrap(
        await listCalcInputFacts({
          throwOnError: true,
          path: { project_id: projectId },
          query: { limit },
        }),
      ),
  });

/** Типы фактов меняются вместе с развёртыванием — перезапрашивать их незачем. */
export const useCalcFactTypes = (enabled: boolean) =>
  useQuery({
    queryKey: calcQueryKeys.factTypes,
    enabled,
    queryFn: async () => unwrap(await listCalcFactTypes({ throwOnError: true })),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useStartInspection = (projectId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CalcInspectionCreate) =>
      unwrap(
        await createCalcInspection({
          throwOnError: true,
          path: { project_id: projectId },
          body,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: calcQueryKeys.project(projectId) }),
  });
};

/** Правила рабочего пространства — не проекта: реестр общий для всех проектов пространства. */
export const useCalcRules = (enabled: boolean) =>
  useQuery({
    queryKey: calcQueryKeys.rules,
    enabled,
    queryFn: async () => unwrap(await listCalcRules({ throwOnError: true })),
  });

/** Карантин старого портала — данные развёртывания: меняются только новой версией каталога. */
export const useCalcLegacyRules = (enabled: boolean) =>
  useQuery({
    queryKey: calcQueryKeys.legacyRules,
    enabled,
    queryFn: async () => unwrap(await listCalcLegacyRules({ throwOnError: true })),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useCalcRuns = (projectId: string, enabled: boolean) =>
  useQuery({
    queryKey: calcQueryKeys.runs(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await listCalcRuns({ throwOnError: true, path: { project_id: projectId } })),
  });

/** Запуск неизменяем — однажды загруженный не устаревает. */
export const useCalcRun = (runId: string | null) =>
  useQuery({
    queryKey: calcQueryKeys.run(runId ?? ''),
    enabled: runId !== null,
    queryFn: async () =>
      unwrap(await getCalcRun({ throwOnError: true, path: { run_id: runId ?? '' } })),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useCalcRunTrace = (runId: string, resultKey: string | null) =>
  useQuery({
    queryKey: calcQueryKeys.trace(runId, resultKey ?? ''),
    enabled: resultKey !== null,
    queryFn: async () =>
      unwrap(
        await getCalcRunTrace({
          throwOnError: true,
          path: { run_id: runId, result_key: resultKey ?? '' },
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useCalcSynthesisRuns = (projectId: string) =>
  useQuery({
    queryKey: calcQueryKeys.synthesisRuns(projectId),
    queryFn: async () =>
      unwrap(await listCalcSynthesisRuns({ throwOnError: true, path: { project_id: projectId } })),
  });

/** Запуск синтеза неизменяем: однажды загруженный — не устаревает. */
export const useCalcSynthesisRun = (runId: string | null) =>
  useQuery({
    queryKey: calcQueryKeys.synthesisRun(runId ?? ''),
    enabled: runId !== null,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () => {
      const path = { run_id: runId ?? '' };
      const run = unwrap(await getCalcSynthesisRun({ throwOnError: true, path }));
      const graph = run.graph_sha256
        ? unwrap(await getCalcSynthesisGraph({ throwOnError: true, path }))
        : null;
      return { run, graph };
    },
  });

export const useCalcSynthesisTrace = (runId: string, elementId: string | null) =>
  useQuery({
    queryKey: calcQueryKeys.synthesisTrace(runId, elementId ?? ''),
    enabled: elementId !== null,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () =>
      unwrap(
        await getCalcSynthesisTrace({
          throwOnError: true,
          path: { run_id: runId },
          query: { element_id: elementId ?? '' },
        }),
      ),
  });
