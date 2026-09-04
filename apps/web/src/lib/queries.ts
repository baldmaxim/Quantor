'use client';

import {
  listDocumentRevisions,
  listProjectDocuments,
  listProjects,
  listRevisionSheets,
  listSheetRegions,
  readJob,
  readMeta,
  readProject,
  readRevisionContentUrl,
  type DocumentRead,
  type MetaResponse,
  type ProjectSummary,
} from '@quantor/api-client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

/**
 * Обращения к API.
 *
 * Всё серверное состояние живёт в TanStack Query и только здесь. Ключи собраны в одном
 * месте: разъехавшиеся ключи — самая частая причина того, что данные не обновляются
 * после изменения или запрашиваются дважды.
 */

export const queryKeys = {
  meta: ['meta'] as const,
  projects: (params: ProjectsParams) => ['projects', params] as const,
  project: (projectId: string) => ['project', projectId] as const,
  documents: (projectId: string) => ['project', projectId, 'documents'] as const,
  revisions: (documentId: string) => ['document', documentId, 'revisions'] as const,
  sheets: (revisionId: string) => ['revision', revisionId, 'sheets'] as const,
  regions: (sheetId: string, blockType: string | null) =>
    ['sheet', sheetId, 'regions', blockType] as const,
  job: (jobId: string) => ['job', jobId] as const,
  contentUrl: (revisionId: string) => ['revision', revisionId, 'content-url'] as const,
};

export interface ProjectsParams {
  readonly search: string;
  readonly sort: 'recent' | 'name';
  readonly limit: number;
  readonly offset: number;
}

/** Задание в работе опрашивается регулярно; завершённое — нет. */
const JOB_POLL_INTERVAL = 2000;

const unwrap = <T>(response: { data?: T }): T => {
  if (response.data === undefined) {
    throw new Error('Пустой ответ API');
  }
  return response.data;
};

export const useMeta = (): UseQueryResult<MetaResponse> =>
  useQuery({
    queryKey: queryKeys.meta,
    queryFn: async () => unwrap(await readMeta({ throwOnError: true })),
    // Версии и флаги меняются вместе с развёртыванием, а не в ходе работы.
    staleTime: 5 * 60_000,
  });

/**
 * Флаги возможностей.
 *
 * Пока ответ не пришёл, всё считается выключенным: показать раздел, которого нет,
 * хуже, чем на мгновение не показать существующий.
 */
export const useFeatures = (): Record<string, boolean> => {
  const { data } = useMeta();
  return data?.features ?? {};
};

export const useProjects = (params: ProjectsParams) =>
  useQuery({
    queryKey: queryKeys.projects(params),
    queryFn: async () =>
      unwrap(
        await listProjects({
          throwOnError: true,
          query: {
            search: params.search || undefined,
            sort: params.sort,
            limit: params.limit,
            offset: params.offset,
          },
        }),
      ),
    // Список показывает ход импорта, поэтому обновляется, пока страница открыта.
    refetchInterval: (query) =>
      query.state.data?.items.some(isRunning) ? JOB_POLL_INTERVAL : false,
  });

export const useProject = (projectId: string) =>
  useQuery({
    queryKey: queryKeys.project(projectId),
    queryFn: async () =>
      unwrap(await readProject({ throwOnError: true, path: { project_id: projectId } })),
    refetchInterval: (query) => (isRunning(query.state.data) ? JOB_POLL_INTERVAL : false),
  });

export const useProjectDocuments = (projectId: string) =>
  useQuery({
    queryKey: queryKeys.documents(projectId),
    queryFn: async () =>
      unwrap(
        await listProjectDocuments({
          throwOnError: true,
          path: { project_id: projectId },
          query: { limit: 200 },
        }),
      ),
  });

export const useDocumentRevisions = (documentId: string | null) =>
  useQuery({
    queryKey: queryKeys.revisions(documentId ?? ''),
    enabled: documentId !== null,
    queryFn: async () =>
      unwrap(
        await listDocumentRevisions({
          throwOnError: true,
          path: { document_id: documentId ?? '' },
          query: { limit: 50 },
        }),
      ),
  });

export const useSheets = (revisionId: string | null) =>
  useQuery({
    queryKey: queryKeys.sheets(revisionId ?? ''),
    enabled: revisionId !== null,
    queryFn: async () =>
      unwrap(
        await listRevisionSheets({
          throwOnError: true,
          path: { revision_id: revisionId ?? '' },
          query: { limit: 500 },
        }),
      ),
    // Листы неизменяемой ревизии не меняются: перезапрашивать их незачем.
    staleTime: Number.POSITIVE_INFINITY,
  });

export const useRegions = (sheetId: string | null, blockType: string | null) =>
  useQuery({
    queryKey: queryKeys.regions(sheetId ?? '', blockType),
    enabled: sheetId !== null,
    queryFn: async () =>
      unwrap(
        await listSheetRegions({
          throwOnError: true,
          path: { sheet_id: sheetId ?? '' },
          query: { limit: 500, block_type: blockType ?? undefined },
        }),
      ),
    staleTime: Number.POSITIVE_INFINITY,
  });

/**
 * Временная ссылка на файл ревизии.
 *
 * Обновляется заранее, до истечения: просмотрщик держит документ открытым часами,
 * и протухшая ссылка посреди работы выглядит как поломка.
 */
export const useContentUrl = (revisionId: string | null) =>
  useQuery({
    queryKey: queryKeys.contentUrl(revisionId ?? ''),
    enabled: revisionId !== null,
    queryFn: async () =>
      unwrap(
        await readRevisionContentUrl({
          throwOnError: true,
          path: { revision_id: revisionId ?? '' },
        }),
      ),
    staleTime: 0,
    refetchInterval: (query) => {
      const expires = query.state.data?.expires_in;
      return expires ? Math.max(expires - 300, 60) * 1000 : false;
    },
  });

export const useJob = (jobId: string | null) =>
  useQuery({
    queryKey: queryKeys.job(jobId ?? ''),
    enabled: jobId !== null,
    queryFn: async () =>
      unwrap(await readJob({ throwOnError: true, path: { job_id: jobId ?? '' } })),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? JOB_POLL_INTERVAL : false;
    },
  });

const isRunning = (project: ProjectSummary | undefined): boolean => {
  const status = project?.last_job?.status;
  return status === 'queued' || status === 'running';
};

/** Документ, пригодный к открытию в рабочей области. */
export const isRenderable = (document: DocumentRead): boolean => document.document_kind === 'pdf';
