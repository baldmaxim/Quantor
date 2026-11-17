'use client';

import {
  approveModelVersion,
  listModelVersions,
  readLatestModelImport,
  readModelPart,
  readModelVersion,
  startModelImport,
  type ModelImportRead,
  type ModelPartRead,
  type ModelVersionDetail,
  type ModelVersionList,
} from '@quantor/api-client';
import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { parseElements, type IModelElement } from './model-elements';

export const modelKeys = {
  versions: (projectId: string) => ['model', projectId, 'versions'] as const,
  version: (projectId: string, versionId: string) =>
    ['model', projectId, 'version', versionId] as const,
  // Часть пакета неизменяема и определяется sha256: у новой версии те же части (неизменившиеся
  // дисциплины) берутся из кэша, а не скачиваются заново.
  part: (projectId: string, _versionId: string, sha256: string) =>
    ['model', projectId, 'part', sha256] as const,
  elements: (projectId: string, _versionId: string, sha256: string) =>
    ['model', projectId, 'elements', sha256] as const,
  import: (projectId: string) => ['model', projectId, 'import'] as const,
};

/** Живой вид: как часто страница спрашивает портал о новых версиях и ходе сборки (вкладка в фоне не опрашивает). */
const LIVE_POLL_MS = 8000;
const BUILD_POLL_MS = 3000;

const retryOnNetwork = (count: number, error: Error): boolean =>
  extractCode(error) === 'NETWORK_ERROR' && count < 2;

export const useModelVersions = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<ModelVersionList> =>
  useQuery({
    queryKey: modelKeys.versions(projectId),
    enabled,
    staleTime: LIVE_POLL_MS,
    refetchInterval: LIVE_POLL_MS,
    queryFn: async () =>
      unwrap(await listModelVersions({ throwOnError: true, path: { project_id: projectId } })),
    retry: retryOnNetwork,
  });

export const useModelVersion = (
  projectId: string,
  versionId: string | null,
): UseQueryResult<ModelVersionDetail> =>
  useQuery({
    queryKey: modelKeys.version(projectId, versionId ?? ''),
    enabled: versionId !== null,
    staleTime: 30_000,
    // Новая версия открывается поверх прежней, а не пустым экраном: живой вид не мигает.
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(
        await readModelVersion({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId ?? '' },
        }),
      ),
    retry: retryOnNetwork,
  });

/** Часть пакета целиком: неизменяема и ключуется по sha256, поэтому кэшируется надолго. */
const fetchPart = async (
  projectId: string,
  versionId: string,
  path: string,
  as: 'arrayBuffer' | 'text',
): Promise<ArrayBuffer | string> => {
  const response = await readModelPart({
    throwOnError: true,
    parseAs: as,
    path: { project_id: projectId, version_id: versionId, path },
  });
  const data: unknown = response.data;
  if (as === 'arrayBuffer' && data instanceof ArrayBuffer) {
    return data;
  }
  if (as === 'text' && typeof data === 'string') {
    return data;
  }
  throw new Error('Часть модели пришла в неожиданной форме');
};

const PART_STALE_MS = 60 * 60 * 1000;

export interface IStoreyGeometry {
  readonly key: string;
  readonly discipline: string;
  readonly buffer: ArrayBuffer;
}

export interface IStoreyGeometryState {
  readonly parts: readonly IStoreyGeometry[];
  readonly loading: boolean;
  readonly failed: boolean;
}

/** Все части GLB этажа: по одной на дисциплину (и на кусок, если этаж делился). */
export const useStoreyGeometry = (
  projectId: string,
  versionId: string | null,
  geometry: readonly ModelPartRead[],
): IStoreyGeometryState => {
  const results = useQueries({
    queries: geometry.map((part) => ({
      queryKey: modelKeys.part(projectId, versionId ?? '', part.sha256),
      enabled: versionId !== null,
      staleTime: PART_STALE_MS,
      gcTime: PART_STALE_MS,
      queryFn: async () => {
        const data = await fetchPart(projectId, versionId ?? '', part.path, 'arrayBuffer');
        return data as ArrayBuffer;
      },
    })),
  });
  const parts: IStoreyGeometry[] = [];
  results.forEach((result, index) => {
    const part = geometry[index];
    if (part !== undefined && result.data !== undefined) {
      parts.push({ key: part.sha256, discipline: part.discipline ?? '', buffer: result.data });
    }
  });
  return {
    parts,
    loading: results.some((result) => result.isPending && result.fetchStatus !== 'idle'),
    failed: results.some((result) => result.isError),
  };
};

/** Элементы этажа из части `elements/<этаж>.jsonl`; без неё геометрия рисуется без свойств. */
export const useStoreyElements = (
  projectId: string,
  versionId: string | null,
  part: ModelPartRead | null,
): UseQueryResult<Map<string, IModelElement>> =>
  useQuery({
    queryKey: modelKeys.elements(projectId, versionId ?? '', part?.sha256 ?? ''),
    enabled: versionId !== null && part !== null,
    staleTime: PART_STALE_MS,
    gcTime: PART_STALE_MS,
    queryFn: async () => {
      const text = await fetchPart(projectId, versionId ?? '', part?.path ?? '', 'text');
      return parseElements(text as string);
    },
  });

export const useApproveModelVersion = (
  projectId: string,
): UseMutationResult<ModelVersionDetail, Error, { versionId: string; comment?: string }> => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ versionId, comment }) =>
      unwrap(
        await approveModelVersion({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId },
          body: comment ? { comment } : {},
        }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['model', projectId] });
    },
  });
};

/** Новейшее задание «Модель из IFC» проекта; `null`, пока ни одного не ставили. */
export const useModelImport = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<ModelImportRead | null> =>
  useQuery({
    queryKey: modelKeys.import(projectId),
    enabled,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? BUILD_POLL_MS : LIVE_POLL_MS;
    },
    queryFn: async () => {
      try {
        return unwrap(
          await readLatestModelImport({ throwOnError: true, path: { project_id: projectId } }),
        );
      } catch (error) {
        if (extractCode(error) === 'NOT_FOUND') return null;
        throw error;
      }
    },
  });

export const useStartModelImport = (
  projectId: string,
): UseMutationResult<ModelImportRead, Error, void> => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await startModelImport({
          throwOnError: true,
          path: { project_id: projectId },
          body: {},
        }),
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: modelKeys.import(projectId) });
    },
  });
};
