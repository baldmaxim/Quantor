'use client';

import {
  createCadEomRoutes,
  readCadEomJob,
  readCadEomPreview,
  readCadEomRoutes3D,
  type CadEomJobRead,
  type CadEomRoutes3dOut,
  type CadPreviewRead,
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

import type { ICadViewParams } from './view-queries';

/**
 * ЭОМ и СС этажа (генератор `cad_eom`): постановка по одобренному виду, ход задания листа, сети и
 * приборы в 3D с ведомостью. Одобрение вида и уровни - общие с трассами механики.
 */

export const EOM_NOT_FOUND = 'CAD_EOM_NOT_FOUND';
/** Пока задание в очереди или идёт, его состояние опрашивается с этим шагом. */
export const EOM_POLL_MS = 3000;

export interface ICadEomSheet {
  readonly projectId: string;
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly view: number;
}

export const eomKeys = {
  job: (sheet: ICadEomSheet) =>
    ['cad-eom', 'job', sheet.projectId, sheet.revisionId, sheet.pageIndex, sheet.view] as const,
  routes3d: (sheet: ICadEomSheet, mark: string) =>
    ['cad-eom', 'routes3d', sheet.projectId, sheet.revisionId, sheet.pageIndex, sheet.view, mark] as const,
};

const queryOf = (sheet: ICadEomSheet) => ({
  revision_id: sheet.revisionId,
  page_index: sheet.pageIndex,
  view: sheet.view,
});

const isActive = (job: CadEomJobRead | null | undefined): boolean =>
  job != null && (job.status === 'queued' || job.status === 'running');

/** Новейшее задание ЭОМ и СС листа; `null` - ни разу не строились. Пока идёт - опрашивается. */
export const useCadEomJob = (
  sheet: ICadEomSheet,
  enabled: boolean,
): UseQueryResult<CadEomJobRead | null> =>
  useQuery({
    queryKey: eomKeys.job(sheet),
    enabled,
    queryFn: async () => {
      try {
        return unwrap(
          await readCadEomJob({
            throwOnError: true,
            path: { project_id: sheet.projectId },
            query: queryOf(sheet),
          }),
        );
      } catch (error) {
        if (extractCode(error) === EOM_NOT_FOUND) return null;
        throw error;
      }
    },
    refetchInterval: (query) => (isActive(query.state.data) ? EOM_POLL_MS : false),
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });

/** Отметка успешного задания для ключа кэша 3D: новое задание или попытка - чтение заново. */
export const eomMark = (job: CadEomJobRead | null | undefined): string =>
  job && job.status === 'succeeded' ? `${job.job_id}:${job.finished_at ?? ''}` : 'none';

export type CadEomRoutes3dState =
  | { readonly status: 'loading' }
  | { readonly status: 'error' }
  | { readonly status: 'none' }
  | { readonly status: 'ready'; readonly data: CadEomRoutes3dOut };

/** Сети и приборы ЭОМ и СС листа; нет построенных - `none`, это не ошибка вида. */
export const useCadEomRoutes3d = (sheet: ICadEomSheet, enabled: boolean): CadEomRoutes3dState => {
  const job = useCadEomJob(sheet, enabled);
  const mark = eomMark(job.data);
  const query = useQuery<CadEomRoutes3dOut | null>({
    queryKey: eomKeys.routes3d(sheet, mark),
    enabled: enabled && mark !== 'none',
    queryFn: async () => {
      try {
        return unwrap(
          await readCadEomRoutes3D({
            throwOnError: true,
            path: { project_id: sheet.projectId },
            query: queryOf(sheet),
          }),
        );
      } catch (error) {
        if (extractCode(error) === EOM_NOT_FOUND) return null;
        throw error;
      }
    },
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });
  if (mark === 'none') return job.isError ? { status: 'error' } : job.isPending && enabled ? { status: 'loading' } : { status: 'none' };
  if (query.data === null) return { status: 'none' };
  if (query.data !== undefined) return { status: 'ready', data: query.data };
  return query.isError ? { status: 'error' } : { status: 'loading' };
};

/**
 * Отметка и высота этажа для ЭОМ и СС - те же, что у трасс механики: `null` (или без аргумента) -
 * генератор определяет их по документации, число - ручной ввод человека.
 */
export interface IEomBuildInput {
  floorElevationMm: number | null;
  floorHeightMm: number | null;
}

/** Построить ЭОМ и СС по одобренному виду (`parent` - задание CAD и попытка вида). */
export const useBuildEom = (
  parent: ICadViewParams,
): UseMutationResult<CadEomJobRead, unknown, IEomBuildInput | void> => {
  const client = useQueryClient();
  const sheet: ICadEomSheet = parent;
  return useMutation({
    mutationFn: async (input: IEomBuildInput | void) =>
      unwrap(
        await createCadEomRoutes({
          throwOnError: true,
          path: {
            project_id: parent.projectId,
            revision_id: parent.revisionId,
            job_id: parent.jobId,
            page_index: parent.pageIndex,
            view: parent.view,
          },
          body: {
            attempt: parent.attempt,
            floor_elevation_mm: input ? input.floorElevationMm : null,
            floor_height_mm: input ? input.floorHeightMm : null,
          },
        }),
      ),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: eomKeys.job(sheet) });
    },
  });
};

/** 2D ЭОМ и СС листа поверх PDF (формат превью трасс); нет построенных или нет файла - `null`. */
export const useCadEomPreview = (
  sheet: ICadEomSheet,
  enabled: boolean,
): CadPreviewRead | null => {
  const job = useCadEomJob(sheet, enabled);
  const mark = eomMark(job.data);
  const query = useQuery<CadPreviewRead | null>({
    queryKey: [...eomKeys.routes3d(sheet, mark), 'preview'] as const,
    enabled: enabled && mark !== 'none',
    queryFn: async () => {
      try {
        return unwrap(
          await readCadEomPreview({
            throwOnError: true,
            path: { project_id: sheet.projectId },
            query: queryOf(sheet),
          }),
        );
      } catch (error) {
        const code = extractCode(error);
        if (code === EOM_NOT_FOUND || code === 'NOT_FOUND') return null;
        throw error;
      }
    },
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });
  return mark === 'none' ? null : (query.data ?? null);
};

/**
 * Превью трасс механики и ЭОМ/СС одним наложением: слои ЭОМ дописываются после слоёв механики,
 * индексы их путей сдвигаются. Кадр общий (DXF вида родителя), поэтому пути складываются как есть.
 */
export const withEomPreview = (
  mep: CadPreviewRead | null,
  eom: CadPreviewRead | null,
): CadPreviewRead | null => {
  if (eom === null) return mep;
  if (mep === null) return eom;
  const shift = mep.layers.length;
  return {
    ...mep,
    layers: [...mep.layers, ...eom.layers],
    paths: [...mep.paths, ...eom.paths.map((path) => ({ ...path, layer: path.layer + shift }))],
    point_count: mep.point_count + eom.point_count,
    truncated: mep.truncated || eom.truncated,
  };
};
