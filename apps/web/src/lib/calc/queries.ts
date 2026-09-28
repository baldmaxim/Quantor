'use client';

import {
  createCalcInspection,
  listCalcDocuments,
  listCalcFactTypes,
  listCalcInputFacts,
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
