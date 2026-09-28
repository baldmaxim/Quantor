'use client';

import {
  createCalcVkPassports,
  getCalcVkPassport,
  getCalcVkReadiness,
  getCalcVkStructure,
  getCalcVkVolumeTrace,
  listCalcVkAssumptions,
  listCalcVkCalculators,
  listCalcVkPassports,
  listCalcVkVolumes,
  type CalcScenario,
  type CalcVkRunCreate,
} from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { calcQueryKeys } from '@/lib/calc/queries';
import { unwrap } from '@/lib/queries';

/**
 * Запросы экрана «Расчёты → ВК». Паспорт и позиции неизменяемы — однажды загруженные не
 * устаревают; готовность и история зависят от фактов и правил — перезапрашиваются.
 */

export const vkQueryKeys = {
  calculators: ['calc', 'vk', 'calculators'] as const,
  readiness: (projectId: string, building: string, section: string) =>
    ['project', projectId, 'calc', 'vk', 'readiness', building, section] as const,
  passports: (projectId: string) => ['project', projectId, 'calc', 'vk', 'passports'] as const,
  passport: (id: string) => ['calc', 'vk', 'passport', id] as const,
  volumes: (id: string, scenario: CalcScenario) => ['calc', 'vk', 'volumes', id, scenario] as const,
  structure: (id: string, scenario: CalcScenario) =>
    ['calc', 'vk', 'structure', id, scenario] as const,
  assumptions: (id: string) => ['calc', 'vk', 'assumptions', id] as const,
  trace: (quantityId: string) => ['calc', 'vk', 'trace', quantityId] as const,
};

export const useVkCalculators = () =>
  useQuery({
    queryKey: vkQueryKeys.calculators,
    queryFn: async () => unwrap(await listCalcVkCalculators({ throwOnError: true })),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useVkReadiness = (projectId: string, building: string, section: string) =>
  useQuery({
    queryKey: vkQueryKeys.readiness(projectId, building, section),
    enabled: building.length > 0,
    queryFn: async () =>
      unwrap(
        await getCalcVkReadiness({
          throwOnError: true,
          path: { project_id: projectId },
          query: { building, ...(section ? { section } : {}) },
        }),
      ),
  });

export const useVkPassports = (projectId: string) =>
  useQuery({
    queryKey: vkQueryKeys.passports(projectId),
    queryFn: async () =>
      unwrap(await listCalcVkPassports({ throwOnError: true, path: { project_id: projectId } })),
  });

export const useVkPassport = (id: string | null) =>
  useQuery({
    queryKey: vkQueryKeys.passport(id ?? ''),
    enabled: id !== null,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () =>
      unwrap(await getCalcVkPassport({ throwOnError: true, path: { passport_id: id ?? '' } })),
  });

export const useVkVolumes = (id: string | null, scenario: CalcScenario) =>
  useQuery({
    queryKey: vkQueryKeys.volumes(id ?? '', scenario),
    enabled: id !== null,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () =>
      unwrap(
        await listCalcVkVolumes({
          throwOnError: true,
          path: { passport_id: id ?? '' },
          query: { scenario },
        }),
      ),
  });

export const useVkStructure = (id: string | null, scenario: CalcScenario) =>
  useQuery({
    queryKey: vkQueryKeys.structure(id ?? '', scenario),
    enabled: id !== null,
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
    queryFn: async () =>
      unwrap(
        await getCalcVkStructure({
          throwOnError: true,
          path: { passport_id: id ?? '' },
          query: { scenario },
        }),
      ),
  });

export const useVkAssumptions = (id: string | null) =>
  useQuery({
    queryKey: vkQueryKeys.assumptions(id ?? ''),
    enabled: id !== null,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () =>
      unwrap(await listCalcVkAssumptions({ throwOnError: true, path: { passport_id: id ?? '' } })),
  });

export const useVkTrace = (quantityId: string | null) =>
  useQuery({
    queryKey: vkQueryKeys.trace(quantityId ?? ''),
    enabled: quantityId !== null,
    staleTime: Number.POSITIVE_INFINITY,
    queryFn: async () =>
      unwrap(
        await getCalcVkVolumeTrace({
          throwOnError: true,
          path: { quantity_id: quantityId ?? '' },
        }),
      ),
  });

export const useCalculateVk = (projectId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CalcVkRunCreate) =>
      unwrap(
        await createCalcVkPassports({ throwOnError: true, path: { project_id: projectId }, body }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: calcQueryKeys.project(projectId) }),
  });
};
