'use client';

import {
  draftCadRisersCopy,
  listCadRisersSheets,
  putCadSheetRisers,
  readCadSheetRisers,
  type CadRiserEntry,
  type CadRisersCopyOut,
  type CadRisersSheetsOut,
  type CadSheetRisersOut,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

import type { ICadViewParams } from './view-queries';

/**
 * Реестр стояков листа (флаг `cad.export`, ADR-0041). Ключ - ревизия, страница и вид: реестр
 * прежнего листа не может оказаться на экране нового.
 */

export interface IRisersSheet {
  readonly projectId: string;
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly view: number;
}

export const risersKeys = {
  sheet: (sheet: IRisersSheet) =>
    ['cad', sheet.projectId, sheet.revisionId, 'risers', sheet.pageIndex, sheet.view] as const,
};

export const risersSheetsKey = (projectId: string, revisionId: string) =>
  ['cad', projectId, revisionId, 'risers', 'sheets'] as const;

export const sheetOf = (params: ICadViewParams): IRisersSheet => ({
  projectId: params.projectId,
  revisionId: params.revisionId,
  pageIndex: params.pageIndex,
  view: params.view,
});

const queryOf = (sheet: IRisersSheet) => ({
  revision_id: sheet.revisionId,
  page_index: sheet.pageIndex,
  view: sheet.view,
});

export const useCadRisers = (sheet: IRisersSheet): UseQueryResult<CadSheetRisersOut> =>
  useQuery({
    queryKey: risersKeys.sheet(sheet),
    queryFn: async () =>
      unwrap(
        await readCadSheetRisers({
          throwOnError: true,
          path: { project_id: sheet.projectId },
          query: queryOf(sheet),
        }),
      ),
  });

export const useSaveCadRisers = (
  sheet: IRisersSheet,
): UseMutationResult<CadSheetRisersOut, unknown, readonly CadRiserEntry[]> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (risers) =>
      unwrap(
        await putCadSheetRisers({
          throwOnError: true,
          path: { project_id: sheet.projectId },
          query: queryOf(sheet),
          body: { risers: [...risers] },
        }),
      ),
    onSuccess: (saved) => {
      client.setQueryData(risersKeys.sheet(sheet), saved);
      // У листа мог появиться реестр: список листов-источников копирования устарел.
      void client.invalidateQueries({
        queryKey: risersSheetsKey(sheet.projectId, sheet.revisionId),
      });
    },
  });
};

/** Листы ревизии с непустым реестром: источники «Скопировать с другого листа». */
export const useCadRisersSheets = (
  projectId: string,
  revisionId: string,
): UseQueryResult<CadRisersSheetsOut> =>
  useQuery({
    queryKey: risersSheetsKey(projectId, revisionId),
    queryFn: async () =>
      unwrap(
        await listCadRisersSheets({
          throwOnError: true,
          path: { project_id: projectId },
          query: { revision_id: revisionId },
        }),
      ),
  });

export interface IRisersCopySource {
  readonly pageIndex: number;
  readonly view: number;
}

/** Черновик копии реестра с другого листа: ничего не пишет, строки уходят в форму. */
export const useDraftCadRisersCopy = (
  sheet: IRisersSheet,
): UseMutationResult<CadRisersCopyOut, unknown, IRisersCopySource> =>
  useMutation({
    mutationFn: async (source) =>
      unwrap(
        await draftCadRisersCopy({
          throwOnError: true,
          path: { project_id: sheet.projectId },
          query: {
            ...queryOf(sheet),
            source_page_index: source.pageIndex,
            source_view: source.view,
          },
        }),
      ),
  });
