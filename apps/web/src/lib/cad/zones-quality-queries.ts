'use client';

import {
  acceptCadZone,
  deleteCadZonesOfSheet,
  readCadZonesSummary,
  type CadZoneRead,
  type CadZonesDeleteRead,
  type CadZonesSheetSummaryRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

import { invalidateFinishSheets } from './finishes-queries';
import { cadPipelineKey } from './pipeline-queries';
import { zoneKeys } from './zones-queries';

/**
 * Сверка зон листа с экспликацией (флаг `cad.export`): сводка листа, принятие зоны вне допуска и
 * массовое удаление зон. Ключ сводки лежит под ключом зон листа: любая запись зон её перечитывает.
 */

export type ZonesDeleteScope = 'auto' | 'all';

export const zonesSummaryKey = (projectId: string, revisionId: string, pageIndex: number) =>
  [...zoneKeys.page(projectId, revisionId, pageIndex), 'summary'] as const;

export const useCadZonesSummary = (
  projectId: string,
  revisionId: string | null,
  pageIndex: number | null,
  enabled: boolean,
): UseQueryResult<CadZonesSheetSummaryRead> =>
  useQuery({
    queryKey: zonesSummaryKey(projectId, revisionId ?? '', pageIndex ?? -1),
    enabled: enabled && revisionId !== null && pageIndex !== null,
    queryFn: async () =>
      unwrap(
        await readCadZonesSummary({
          throwOnError: true,
          path: { project_id: projectId },
          query: { revision_id: revisionId ?? '', page_index: pageIndex ?? 0 },
        }),
      ),
  });

/** Зоны листа изменились: перечитать зоны со сводкой, отделку, конвейер и конструкции листа. */
const invalidateZoneData = (
  client: QueryClient,
  projectId: string,
  revisionId: string,
): Promise<unknown> =>
  Promise.all([
    client.invalidateQueries({ queryKey: zoneKeys.revision(projectId, revisionId) }),
    invalidateFinishSheets(client, projectId, revisionId),
    client.invalidateQueries({ queryKey: cadPipelineKey(projectId, revisionId) }),
    client.invalidateQueries({ queryKey: ['cad-constructions', projectId, revisionId] }),
  ]);

export const useAcceptCadZone = (
  projectId: string,
): UseMutationResult<CadZoneRead, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id) =>
      unwrap(await acceptCadZone({ throwOnError: true, path: { zone_id: id } })),
    onSuccess: (zone) => invalidateZoneData(client, projectId, zone.revision_id),
  });
};

export const useDeleteCadZonesOfSheet = (
  projectId: string,
  revisionId: string,
  pageIndex: number,
): UseMutationResult<CadZonesDeleteRead, unknown, ZonesDeleteScope> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (scope) =>
      unwrap(
        await deleteCadZonesOfSheet({
          throwOnError: true,
          path: { project_id: projectId },
          query: { revision_id: revisionId, page_index: pageIndex, scope },
        }),
      ),
    onSuccess: () => invalidateZoneData(client, projectId, revisionId),
  });
};
