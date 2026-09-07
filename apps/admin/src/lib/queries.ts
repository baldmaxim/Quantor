'use client';

import {
  deleteFeatureFlagOverride,
  deleteSettingOverride,
  listAuditEvents,
  listFeatureFlags,
  listSettings,
  readMeta,
  readSession,
  readTenderhubStatus,
  setFeatureFlagOverride,
  setSettingOverride,
  testTenderhubConnection,
} from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

/**
 * Обращения к API собраны здесь, а не разбросаны по страницам: иначе ключи кэша
 * расходятся, и после изменения настройки соседняя страница продолжает показывать
 * старое значение.
 */

export const queryKeys = {
  session: ['session'] as const,
  meta: ['meta'] as const,
  settings: ['settings'] as const,
  flags: ['feature-flags'] as const,
  tenderhub: ['integrations', 'tenderhub'] as const,
  audit: (page: { limit: number; offset: number }) => ['audit', page] as const,
} as const;

const unwrap = <T>(response: { data?: T }): T => {
  if (response.data === undefined) throw new Error('Пустой ответ API');
  return response.data;
};

export const useSession = () =>
  useQuery({
    queryKey: queryKeys.session,
    queryFn: async () => unwrap(await readSession({ throwOnError: true })),
    staleTime: 60_000,
    retry: false,
  });

export const useMeta = () =>
  useQuery({
    queryKey: queryKeys.meta,
    queryFn: async () => unwrap(await readMeta({ throwOnError: true })),
    staleTime: 5 * 60_000,
  });

export const useSettings = () =>
  useQuery({
    queryKey: queryKeys.settings,
    queryFn: async () => unwrap(await listSettings({ throwOnError: true })),
  });

export const useFeatureFlags = () =>
  useQuery({
    queryKey: queryKeys.flags,
    queryFn: async () => unwrap(await listFeatureFlags({ throwOnError: true })),
  });

export const useTenderHubStatus = () =>
  useQuery({
    queryKey: queryKeys.tenderhub,
    queryFn: async () => unwrap(await readTenderhubStatus({ throwOnError: true })),
  });

export const useAuditEvents = (page: { limit: number; offset: number }) =>
  useQuery({
    queryKey: queryKeys.audit(page),
    // Пагинация обязательна: журнал растёт всё время работы установки.
    queryFn: async () => unwrap(await listAuditEvents({ query: page, throwOnError: true })),
  });

/* ------------------------------------------------------------------ изменения */

export const useSetSetting = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { key: string; scope: 'system' | 'workspace'; value: unknown }) =>
      unwrap(
        await setSettingOverride({
          path: { key: input.key },
          body: { scope: input.scope, value: input.value as string },
          throwOnError: true,
        }),
      ),
    // Журнал тоже обновляется: изменение настройки оставляет в нём запись, и увидеть
    // её сразу полезнее, чем узнать о ней при следующем открытии страницы.
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.settings });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
};

export const useResetSetting = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { key: string; scope: 'system' | 'workspace' }) =>
      unwrap(
        await deleteSettingOverride({
          path: { key: input.key },
          query: { scope: input.scope },
          throwOnError: true,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.settings });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
};

export const useSetFlag = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      key: string;
      scope: 'system' | 'workspace';
      enabled: boolean;
      reason: string | null;
    }) =>
      unwrap(
        await setFeatureFlagOverride({
          path: { key: input.key },
          body: { scope: input.scope, enabled: input.enabled, reason: input.reason },
          throwOnError: true,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.flags });
      void queryClient.invalidateQueries({ queryKey: queryKeys.meta });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
};

export const useResetFlag = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { key: string; scope: 'system' | 'workspace' }) =>
      unwrap(
        await deleteFeatureFlagOverride({
          path: { key: input.key },
          query: { scope: input.scope },
          throwOnError: true,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.flags });
      void queryClient.invalidateQueries({ queryKey: queryKeys.meta });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
};

export const useTestTenderHub = () => {
  const queryClient = useQueryClient();
  return useMutation({
    // Явное действие по кнопке: страница состояния не ходит во внешнюю систему сама.
    mutationFn: async () => unwrap(await testTenderhubConnection({ throwOnError: true })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.tenderhub });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
};
