'use client';

import { getMepScenario, listMepScenarios } from '@quantor/api-client';
import { useQuery } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Запросы страницы MEP-эксперимента. Отдельно от общих: закрыты флагом и не выполняются, пока
 * страница скрыта. Сценарии синтетические и неизменные — перезапрашивать их незачем.
 */

export const mepQueryKeys = {
  scenarios: ['mep', 'scenarios'] as const,
  scenario: (scenarioId: string) => ['mep', 'scenario', scenarioId] as const,
};

export const useMepScenarios = (enabled: boolean) =>
  useQuery({
    queryKey: mepQueryKeys.scenarios,
    enabled,
    queryFn: async () => unwrap(await listMepScenarios({ throwOnError: true })),
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useMepScenario = (scenarioId: string | null) =>
  useQuery({
    queryKey: mepQueryKeys.scenario(scenarioId ?? ''),
    enabled: scenarioId !== null,
    queryFn: async () =>
      unwrap(await getMepScenario({ throwOnError: true, path: { scenario_id: scenarioId ?? '' } })),
    staleTime: Number.POSITIVE_INFINITY,
  });
