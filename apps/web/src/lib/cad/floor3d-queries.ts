'use client';

import {
  putCadFloor3dHole,
  putCadProjectLevels,
  putCadSheetLevels,
  readCadFloor3D,
  readCadProjectLevels,
  type CadFloor3dRead,
  type CadProjectLevelsRead,
  type CadProjectLevelsWrite,
  type CadSheetLevelsWrite,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { WALLS_POLL_MS, isWallsActive, wallsJobStatus } from './constructions-queries';
import type { ICadViewParams } from './view-queries';

/**
 * 3D-вид этажа (ADR-0039, флаг `cad.export`): модель этажа листа, решения по отверстиям плиты,
 * высоты листа и толщина плиты проекта. Модель собирает сервер; здесь её только читают и пишут
 * решения человека. Ответ PUT отверстия - обновлённая модель, она кладётся в кэш сразу.
 */

export const floor3dKeys = {
  /** Все модели этажей проекта (после изменения уровня проекта). */
  project: (projectId: string) => ['cad-floor3d', projectId] as const,
  view: (params: ICadViewParams) =>
    ['cad-floor3d', params.projectId, params.revisionId, params.jobId, params.pageIndex, params.view] as const,
  projectLevels: (projectId: string) => ['cad-project-levels', projectId] as const,
};

const pathOf = (params: ICadViewParams) => ({
  project_id: params.projectId,
  job_id: params.jobId,
  page_index: params.pageIndex,
  view: params.view,
});

const need = (params: ICadViewParams | null): ICadViewParams => {
  if (params === null) throw new Error('Вид листа не выбран');
  return params;
};

/**
 * Модель этажа. Отказ 404 `CAD_WALLS_NOT_READY` - конструкции листа не посчитаны; пока их задание
 * идёт, статус опрашивается. Свежесть нулевая: модель зависит от параметров конструкций, которые
 * правятся в другом разделе, поэтому при каждом открытии вида она читается заново.
 */
export const useCadFloor3d = (
  params: ICadViewParams | null,
  enabled: boolean,
): UseQueryResult<CadFloor3dRead> =>
  useQuery({
    queryKey: params ? floor3dKeys.view(params) : ['cad-floor3d', 'idle'],
    enabled: enabled && params !== null,
    queryFn: async () => unwrap(await readCadFloor3D({ throwOnError: true, path: pathOf(need(params)) })),
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
    refetchInterval: (query) =>
      query.state.error !== null && isWallsActive(wallsJobStatus(query.state.error))
        ? WALLS_POLL_MS
        : false,
  });

export interface IHoleDecision {
  readonly key: string;
  readonly enabled: boolean;
}

/** Решение по отверстию: включено - вырез в плите, выключено - плита сплошная. */
export const useSetFloor3dHole = (
  params: ICadViewParams | null,
): UseMutationResult<CadFloor3dRead, unknown, IHoleDecision> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ key, enabled }) =>
      unwrap(
        await putCadFloor3dHole({
          throwOnError: true,
          path: { ...pathOf(need(params)), hole_key: key },
          body: { enabled },
        }),
      ),
    onSuccess: (model) => {
      if (params) client.setQueryData<CadFloor3dRead>(floor3dKeys.view(params), model);
    },
  });
};

/**
 * Высоты листа целиком (сервер заменяет их все разом; пусто = снять). После записи перечитываются
 * модель этажа и конструкции листа: от высот зависят и призмы, и величины.
 */
export const useSaveFloor3dSheetLevels = (
  params: ICadViewParams | null,
): UseMutationResult<unknown, unknown, CadSheetLevelsWrite> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (levels) =>
      unwrap(await putCadSheetLevels({ throwOnError: true, path: pathOf(need(params)), body: levels })),
    onSuccess: () => {
      if (!params) return;
      void client.invalidateQueries({ queryKey: floor3dKeys.view(params) });
      void client.invalidateQueries({
        queryKey: ['cad-constructions', params.projectId, params.revisionId, params.jobId, params.pageIndex, params.view],
      });
    },
  });
};

export const useCadProjectLevels = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<CadProjectLevelsRead> =>
  useQuery({
    queryKey: floor3dKeys.projectLevels(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await readCadProjectLevels({ throwOnError: true, path: { project_id: projectId } })),
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });

/** Толщина плиты проекта из разреза: действует на все листы, поэтому перечитываются все модели проекта. */
export const useSaveCadProjectLevels = (
  projectId: string,
): UseMutationResult<CadProjectLevelsRead, unknown, CadProjectLevelsWrite> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (levels) =>
      unwrap(await putCadProjectLevels({ throwOnError: true, path: { project_id: projectId }, body: levels })),
    onSuccess: (saved) => {
      client.setQueryData<CadProjectLevelsRead>(floor3dKeys.projectLevels(projectId), saved);
      void client.invalidateQueries({ queryKey: floor3dKeys.project(projectId) });
      void client.invalidateQueries({ queryKey: ['cad-constructions', projectId] });
    },
  });
};

/** Режим холста листа CAD («План» или «3D») запоминается между сеансами. */
export const FLOOR3D_MODE_KEY = 'quantor.cad.view-3d';
