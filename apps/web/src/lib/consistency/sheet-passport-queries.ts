'use client';

import {
  bulkSheetPassportStatus,
  getSheetPassportExtractSummary,
  groupSheetPassportStatus,
  listSheetPassportGroups,
  listSheetPassports,
  patchSheetPassport,
  startSheetPassportExtract,
  type JobRead,
  type SheetPassportBulkOut,
  type SheetPassportExtractSummary,
  type SheetPassportGroupOut,
  type SheetPassportGroupsOut,
  type SheetPassportListOut,
  type SheetPassportOut,
  type SheetPassportPatch,
  type SheetPassportStatus,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { unwrap } from '@/lib/queries';

/**
 * Запросы «Листов комплекта» (ADR-0043, С1; флаг `project.consistency`).
 *
 * Список и счётчик «подтверждено» ключуются проектом: любая запись перечитывает весь проект.
 * Итог последнего разбора берётся из `extract-summary` проекта: после перезагрузки страницы он не теряется.
 */

const JOB_POLL_MS = 2000;

/**
 * Отбор по полям паспорта: null - без фильтра, пустая строка - поле не указано.
 * Пустая строка уходит на сервер как есть: так сервер ищет паспорта без корпуса, секции и т. п.
 */
export interface IPassportScope {
  readonly sectionMark: string | null;
  readonly sheetKind: string | null;
  readonly building: string | null;
  readonly section: string | null;
}

export interface IPassportFilters extends IPassportScope {
  readonly status: SheetPassportStatus | null;
  readonly offset: number;
  readonly limit: number;
}

export const passportKeys = {
  project: (projectId: string) => ['sheet-passports', projectId] as const,
  list: (projectId: string, filters: IPassportFilters) =>
    ['sheet-passports', projectId, 'list', filters] as const,
  confirmed: (projectId: string, scope: IPassportScope) =>
    ['sheet-passports', projectId, 'confirmed', scope] as const,
  groups: (projectId: string, sheetKind: string | null) =>
    ['sheet-passports', projectId, 'groups', sheetKind] as const,
  extractSummary: (projectId: string) => ['sheet-passports', projectId, 'extract-summary'] as const,
};

const scopeQuery = (scope: IPassportScope) => ({
  section_mark: scope.sectionMark,
  sheet_kind: scope.sheetKind,
  building: scope.building,
  section: scope.section,
});

export const useSheetPassports = (
  projectId: string,
  filters: IPassportFilters,
  enabled: boolean,
): UseQueryResult<SheetPassportListOut> =>
  useQuery({
    queryKey: passportKeys.list(projectId, filters),
    enabled,
    placeholderData: (previous) => previous,
    queryFn: async () =>
      unwrap(
        await listSheetPassports({
          throwOnError: true,
          path: { project_id: projectId },
          query: {
            ...scopeQuery(filters),
            status: filters.status,
            limit: filters.limit,
            offset: filters.offset,
          },
        }),
      ),
  });

/** Сколько подтверждено в выборке: нужен только `total` ответа, строки не грузятся. */
export const useConfirmedCount = (
  projectId: string,
  scope: IPassportScope,
  enabled: boolean,
): UseQueryResult<number> =>
  useQuery({
    queryKey: passportKeys.confirmed(projectId, scope),
    enabled,
    queryFn: async () =>
      unwrap(
        await listSheetPassports({
          throwOnError: true,
          path: { project_id: projectId },
          query: { ...scopeQuery(scope), status: 'confirmed', limit: 1, offset: 0 },
        }),
      ).total,
  });

/** Группы раздел · тип · корпус · секция; `sheetKind` - только этот тип листа, null - все. */
export const useSheetPassportGroups = (
  projectId: string,
  sheetKind: string | null,
  enabled: boolean,
): UseQueryResult<SheetPassportGroupsOut> =>
  useQuery({
    queryKey: passportKeys.groups(projectId, sheetKind),
    enabled,
    placeholderData: (previous) => previous,
    queryFn: async () =>
      unwrap(
        await listSheetPassportGroups({
          throwOnError: true,
          path: { project_id: projectId },
          query: { sheet_kind: sheetKind },
        }),
      ),
  });

export interface IGroupStatus {
  readonly group: SheetPassportGroupOut;
  readonly status: SheetPassportStatus;
}

/** Статус группе целиком: подтверждение и отклонение сервер применяет только к кандидатам. */
export const useGroupPassportStatus = (
  projectId: string,
): UseMutationResult<SheetPassportBulkOut, unknown, IGroupStatus> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ group, status }) =>
      unwrap(
        await groupSheetPassportStatus({
          throwOnError: true,
          path: { project_id: projectId },
          body: {
            section_mark: group.section_mark,
            sheet_kind: group.sheet_kind,
            building: group.building,
            section: group.section,
            status,
          },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: passportKeys.project(projectId) }),
  });
};

const isActive = (summary: SheetPassportExtractSummary | null | undefined): boolean =>
  summary?.status === 'queued' || summary?.status === 'running';

/** Итог последнего разбора листов проекта (null - заданий не было); пока задание идёт - опрашивается. */
export const useExtractSummary = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<SheetPassportExtractSummary | null> => {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: passportKeys.extractSummary(projectId),
    enabled,
    queryFn: async (): Promise<SheetPassportExtractSummary | null> => {
      const response = await getSheetPassportExtractSummary({
        throwOnError: true,
        path: { project_id: projectId },
      });
      // Заданий не было - сервер отдаёт null: это не пустой ответ, а штатный результат.
      return response.data ?? null;
    },
    refetchInterval: (state) => (isActive(state.state.data) ? JOB_POLL_MS : false),
  });

  // Задание закончилось в этой сессии: таблица и счётчик перечитываются один раз.
  const wasActive = useRef(false);
  const active = isActive(query.data);
  useEffect(() => {
    if (active) {
      wasActive.current = true;
    } else if (wasActive.current) {
      wasActive.current = false;
      void client.invalidateQueries({ queryKey: passportKeys.project(projectId) });
    }
  }, [active, client, projectId]);

  return query;
};

export const useStartPassportExtract = (
  projectId: string,
): UseMutationResult<JobRead, unknown, void> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await startSheetPassportExtract({ throwOnError: true, path: { project_id: projectId } }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: passportKeys.extractSummary(projectId) }),
  });
};

export interface IPatchPassport {
  readonly id: string;
  readonly patch: SheetPassportPatch;
}

export const usePatchPassport = (
  projectId: string,
): UseMutationResult<SheetPassportOut, unknown, IPatchPassport> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }) =>
      unwrap(
        await patchSheetPassport({
          throwOnError: true,
          path: { project_id: projectId, passport_id: id },
          body: patch,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: passportKeys.project(projectId) }),
  });
};

export interface IBulkPassportStatus {
  readonly ids: readonly string[];
  readonly status: SheetPassportStatus;
}

export const useBulkPassportStatus = (
  projectId: string,
): UseMutationResult<SheetPassportBulkOut, unknown, IBulkPassportStatus> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ ids, status }) =>
      unwrap(
        await bulkSheetPassportStatus({
          throwOnError: true,
          path: { project_id: projectId },
          body: { ids: [...ids], status },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: passportKeys.project(projectId) }),
  });
};
