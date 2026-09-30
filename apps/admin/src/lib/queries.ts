'use client';

import {
  approveAdminUser,
  cancelAdminJob,
  disableAdminUser,
  enableAdminUser,
  listAdminUsers,
  listAdminWorkspaces,
  rejectAdminUser,
  setAdminUserMembership,
  setAdminUserPassword,
  checkModelProvider,
  deleteFeatureFlagOverride,
  deleteSettingOverride,
  listAdminJobs,
  listAuditEvents,
  listFeatureFlags,
  listJobWorkers,
  listModelProviders,
  listSettings,
  readDiagnostics,
  readJobStats,
  readMeta,
  readSession,
  readTenderhubStatus,
  setFeatureFlagOverride,
  retryAdminJob,
  setSettingOverride,
  testTenderhubConnection,
} from '@quantor/api-client';
import type { ApprovalStatus, Role } from '@quantor/api-client';
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
  audit: (page: AuditQuery) => ['audit', page] as const,
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

export interface AuditQuery {
  limit: number;
  offset: number;
  action?: string;
  resource_type?: string;
  result?: 'success' | 'failure' | 'denied';
  since?: string;
  until?: string;
}

export const useAuditEvents = (page: AuditQuery) =>
  useQuery({
    queryKey: queryKeys.audit(page),
    // Пагинация обязательна: журнал растёт всё время работы установки.
    // Фильтры уходят на сервер, а не применяются к загруженной странице: иначе
    // «показать отказы» показывало бы отказы только из первых пятидесяти записей.
    queryFn: async () =>
      unwrap(await listAuditEvents({ query: page as never, throwOnError: true })),
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

/* --------------------------------------------------- задания, состояние, модели */

export const jobKeys = {
  list: (page: { limit: number; offset: number; status?: string }) => ['jobs', page] as const,
  stats: ['jobs', 'stats'] as const,
  workers: ['jobs', 'workers'] as const,
  diagnostics: ['diagnostics'] as const,
  modelProviders: ['model-providers'] as const,
} as const;

export const useAdminJobs = (page: { limit: number; offset: number; status?: string }) =>
  useQuery({
    queryKey: jobKeys.list(page),
    queryFn: async () =>
      unwrap(
        await listAdminJobs({
          query: {
            limit: page.limit,
            offset: page.offset,
            ...(page.status ? { status: page.status as never } : {}),
          },
          throwOnError: true,
        }),
      ),
  });

export const useJobStats = () =>
  useQuery({
    queryKey: jobKeys.stats,
    queryFn: async () => unwrap(await readJobStats({ throwOnError: true })),
  });

export const useJobWorkers = () =>
  useQuery({
    queryKey: jobKeys.workers,
    queryFn: async () => unwrap(await listJobWorkers({ throwOnError: true })),
  });

export const useDiagnostics = () =>
  useQuery({
    queryKey: jobKeys.diagnostics,
    queryFn: async () => unwrap(await readDiagnostics({ throwOnError: true })),
    // Обновление по кнопке. Автоматический опрос добавляет нагрузку ровно тогда,
    // когда система нездорова, — а сюда приходят именно в этот момент.
    refetchInterval: false,
  });

export const useModelProviders = () =>
  useQuery({
    queryKey: jobKeys.modelProviders,
    queryFn: async () => unwrap(await listModelProviders({ throwOnError: true })),
  });

export const useRetryJob = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: string) =>
      unwrap(await retryAdminJob({ path: { job_id: jobId }, throwOnError: true })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
};

export const useCancelJob = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (jobId: string) =>
      unwrap(await cancelAdminJob({ path: { job_id: jobId }, throwOnError: true })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
};

export const useCheckModelProvider = () => {
  const queryClient = useQueryClient();
  return useMutation({
    // Явное действие: открытие страницы к моделям не обращается.
    mutationFn: async (providerId: string) =>
      unwrap(await checkModelProvider({ path: { provider_id: providerId }, throwOnError: true })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: jobKeys.modelProviders }),
  });
};

/* ----------------------------------------------------------- пользователи и доступ */

/** Роль, которую выдаёт членство. Платформенные роли через членство не выдаются. */
export type WorkspaceRole = Exclude<Role, 'platform_admin' | 'service'>;

export interface UsersQuery {
  limit: number;
  offset: number;
  status?: ApprovalStatus;
}

export const userKeys = {
  all: ['users'] as const,
  list: (page: UsersQuery) => ['users', 'list', page] as const,
  pendingCount: ['users', 'pending-count'] as const,
  workspaces: ['workspaces'] as const,
} as const;

export const useAdminUsers = (page: UsersQuery) =>
  useQuery({
    queryKey: userKeys.list(page),
    queryFn: async () =>
      unwrap(
        await listAdminUsers({
          query: {
            limit: page.limit,
            offset: page.offset,
            ...(page.status ? { status: page.status } : {}),
          },
          throwOnError: true,
        }),
      ),
  });

/**
 * Число заявок, ждущих решения, — для отметок в навигации, шапке и на обзоре.
 *
 * Без опроса по таймеру: контур управления сам сервер не опрашивает. Число обновляется,
 * когда администратор возвращается на вкладку, и после каждого действия с пользователями.
 */
export const usePendingUsersCount = () =>
  useQuery({
    queryKey: userKeys.pendingCount,
    queryFn: async () =>
      unwrap(
        await listAdminUsers({
          query: { status: 'pending', limit: 1, offset: 0 },
          throwOnError: true,
        }),
      ).total,
    refetchOnWindowFocus: true,
  });

export const useAdminWorkspaces = () =>
  useQuery({
    queryKey: userKeys.workspaces,
    queryFn: async () => unwrap(await listAdminWorkspaces({ throwOnError: true })),
    staleTime: 5 * 60_000,
  });

/** Изменение пользователя: список, счётчик заявок и журнал обновляются вместе. */
const useUserMutation = <TInput>(run: (input: TInput) => Promise<unknown>) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: userKeys.all });
      void queryClient.invalidateQueries({ queryKey: ['audit'] });
    },
  });
};

export const useApproveUser = () =>
  useUserMutation(async (input: { userId: string; workspaceId: string; role: WorkspaceRole }) =>
    unwrap(
      await approveAdminUser({
        path: { user_id: input.userId },
        body: { workspace_id: input.workspaceId, role: input.role },
        throwOnError: true,
      }),
    ),
  );

export const useSetUserMembership = () =>
  useUserMutation(async (input: { userId: string; workspaceId: string; role: WorkspaceRole }) =>
    unwrap(
      await setAdminUserMembership({
        path: { user_id: input.userId },
        body: { workspace_id: input.workspaceId, role: input.role },
        throwOnError: true,
      }),
    ),
  );

export const useRejectUser = () =>
  useUserMutation(async (userId: string) =>
    unwrap(await rejectAdminUser({ path: { user_id: userId }, throwOnError: true })),
  );

export const useSetUserActive = () =>
  useUserMutation(async (input: { userId: string; active: boolean }) =>
    unwrap(
      input.active
        ? await enableAdminUser({ path: { user_id: input.userId }, throwOnError: true })
        : await disableAdminUser({ path: { user_id: input.userId }, throwOnError: true }),
    ),
  );

export const useSetUserPassword = () =>
  useUserMutation(async (input: { userId: string; password: string }) =>
    unwrap(
      await setAdminUserPassword({
        path: { user_id: input.userId },
        body: { password: input.password },
        throwOnError: true,
      }),
    ),
  );
