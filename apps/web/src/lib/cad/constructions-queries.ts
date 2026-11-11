'use client';

import {
  bulkCadConstructionProps,
  putCadConstructionProps,
  putCadSheetLevels,
  readCadConstructions,
  recomputeCadWalls,
  type CadConstructionProps,
  type CadConstructionRead,
  type CadConstructionsBulkRead,
  type CadConstructionsRead,
  type CadConstructionsTotalsRead,
  type CadSheetLevelsWrite,
  type CadWallsJobRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { cadCodeText } from './errors';
import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import type { ICadViewParams } from './view-queries';

/**
 * Конструкции листа (ADR-0038, флаг `cad.export`): чтение результата `cad_walls` с величинами,
 * параметры конструкций, высоты листа и пересчёт. Адрес - по родителю `cad_pdf_convert` и виду.
 * Все величины считает сервер; здесь их только показывают.
 */

export const WALLS_NOT_READY = 'CAD_WALLS_NOT_READY';
export const WALLS_BUSY = 'CAD_WALLS_BUSY';

/** Период опроса, пока расчёт идёт. */
export const WALLS_POLL_MS = 5000;

export const constructionKeys = {
  view: (params: ICadViewParams) =>
    ['cad-constructions', params.projectId, params.revisionId, params.jobId, params.pageIndex, params.view] as const,
};

const need = (params: ICadViewParams | null): ICadViewParams => {
  if (params === null) throw new Error('Вид листа не выбран');
  return params;
};

const pathOf = (params: ICadViewParams) => ({
  project_id: params.projectId,
  job_id: params.jobId,
  page_index: params.pageIndex,
  view: params.view,
});

/** Статус последнего задания расчёта из отказа 404 `CAD_WALLS_NOT_READY` (`detail.issue.job_status`). */
export const wallsJobStatus = (error: unknown): string | null => {
  const read = (value: unknown): string | null => {
    const status = (value as { detail?: { issue?: { job_status?: unknown } } } | null)?.detail?.issue
      ?.job_status;
    return typeof status === 'string' ? status : null;
  };
  return read(error) ?? read((error as { error?: unknown } | null)?.error);
};

/** Расчёт ещё идёт: задание в очереди или выполняется. */
export const isWallsActive = (status: string | null): boolean =>
  status === 'queued' || status === 'running';

/** Статус самого свежего задания расчёта в ответе: оно может быть новее показанного результата. */
export const latestWallsStatus = (data: CadConstructionsRead | undefined): string | null =>
  data?.latest_walls_job?.status ?? null;

/** Текст отказа самого свежего задания пересчёта; `null` - оно не упало. */
export const latestWallsFailure = (data: CadConstructionsRead | null): string | null => {
  const job = data?.latest_walls_job;
  if (!job || job.status !== 'failed') return null;
  return job.error_message ?? (job.error_code !== null ? cadCodeText(job.error_code) : null) ?? 'причина не указана';
};

export const useCadConstructions = (
  params: ICadViewParams | null,
  enabled: boolean,
): UseQueryResult<CadConstructionsRead> =>
  useQuery({
    queryKey: params ? constructionKeys.view(params) : ['cad-constructions', 'idle'],
    enabled: enabled && params !== null,
    queryFn: async () =>
      unwrap(await readCadConstructions({ throwOnError: true, path: pathOf(need(params)) })),
    // 404 (результата нет) и отказ доступа повтором не лечатся.
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
    refetchInterval: (query) => {
      if (query.state.error !== null && isWallsActive(wallsJobStatus(query.state.error))) {
        return WALLS_POLL_MS;
      }
      // Пока свежее задание идёт, старый результат остаётся на экране, а статус опрашивается.
      return isWallsActive(latestWallsStatus(query.state.data)) ? WALLS_POLL_MS : false;
    },
  });

export const useRecomputeCadWalls = (
  params: ICadViewParams | null,
): UseMutationResult<CadWallsJobRead, unknown, void> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(await recomputeCadWalls({ throwOnError: true, path: pathOf(need(params)) })),
    onSettled: () => {
      if (params) void client.invalidateQueries({ queryKey: constructionKeys.view(params) });
    },
  });
};

export interface ISaveProps {
  readonly key: string;
  readonly props: CadConstructionProps;
  /** Не передано - признак «принято» не меняется. */
  readonly accepted?: boolean;
}

/** Параметры одной конструкции: ответ подставляется в кэш сразу, итоги листа перечитываются. */
export const useSaveConstructionProps = (
  params: ICadViewParams | null,
): UseMutationResult<CadConstructionRead, unknown, ISaveProps> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ key, props, accepted }) =>
      unwrap(
        await putCadConstructionProps({
          throwOnError: true,
          path: { ...pathOf(need(params)), construction_key: key },
          body: accepted === undefined ? { props } : { props, accepted },
        }),
      ),
    onSuccess: (updated) => {
      if (!params) return;
      client.setQueryData<CadConstructionsRead>(constructionKeys.view(params), (current) =>
        current
          ? {
              ...current,
              constructions: current.constructions.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : current,
      );
      void client.invalidateQueries({ queryKey: constructionKeys.view(params) });
    },
  });
};

export interface IBulkProps {
  readonly keys: readonly string[];
  readonly patch: CadConstructionProps;
}

export const useBulkConstructionProps = (
  params: ICadViewParams | null,
): UseMutationResult<CadConstructionsBulkRead, unknown, IBulkProps> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ keys, patch }) =>
      unwrap(
        await bulkCadConstructionProps({
          throwOnError: true,
          path: pathOf(need(params)),
          body: { keys: [...keys], props_patch: patch },
        }),
      ),
    onSuccess: () => {
      if (params) void client.invalidateQueries({ queryKey: constructionKeys.view(params) });
    },
  });
};

export const useSaveSheetLevels = (
  params: ICadViewParams | null,
): UseMutationResult<CadConstructionsTotalsRead, unknown, CadSheetLevelsWrite> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (levels) =>
      unwrap(
        await putCadSheetLevels({
          throwOnError: true,
          path: pathOf(need(params)),
          body: levels,
        }),
      ),
    onSuccess: () => {
      if (params) void client.invalidateQueries({ queryKey: constructionKeys.view(params) });
    },
  });
};
