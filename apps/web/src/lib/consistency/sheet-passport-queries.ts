'use client';

import {
  bulkSheetPassportStatus,
  getSheetPassportExtractSummary,
  listSheetPassports,
  patchSheetPassport,
  startSheetPassportExtract,
  type JobRead,
  type SheetPassportBulkOut,
  type SheetPassportExtractSummary,
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

export interface IPassportFilters {
  readonly status: SheetPassportStatus | null;
  readonly sectionMark: string | null;
  readonly offset: number;
  readonly limit: number;
}

export const passportKeys = {
  project: (projectId: string) => ['sheet-passports', projectId] as const,
  list: (projectId: string, filters: IPassportFilters) =>
    ['sheet-passports', projectId, 'list', filters] as const,
  confirmed: (projectId: string, sectionMark: string | null) =>
    ['sheet-passports', projectId, 'confirmed', sectionMark] as const,
  extractSummary: (projectId: string) => ['sheet-passports', projectId, 'extract-summary'] as const,
};

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
            status: filters.status,
            section_mark: filters.sectionMark,
            limit: filters.limit,
            offset: filters.offset,
          },
        }),
      ),
  });

/** Сколько подтверждено в выборке по разделу: нужен только `total` ответа, строки не грузятся. */
export const useConfirmedCount = (
  projectId: string,
  sectionMark: string | null,
  enabled: boolean,
): UseQueryResult<number> =>
  useQuery({
    queryKey: passportKeys.confirmed(projectId, sectionMark),
    enabled,
    queryFn: async () =>
      unwrap(
        await listSheetPassports({
          throwOnError: true,
          path: { project_id: projectId },
          query: { status: 'confirmed', section_mark: sectionMark, limit: 1, offset: 0 },
        }),
      ).total,
  });

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
