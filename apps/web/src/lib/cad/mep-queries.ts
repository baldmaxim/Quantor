'use client';

import {
  acceptCadMepRoutes,
  approveCadView,
  createCadMepRoutes,
  downloadCadArtifact,
  type CadDecisionRead,
  type CadJobRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { cadArtifactUrl } from './artifacts';
import { parseCandidate, viewFolder, type MepCandidate } from './mep-candidate';
import { cadKeys } from './queries';
import { cadViewKeys, type ICadViewParams } from './view-queries';

/**
 * Решения человека и трассы механики (ADR-0036 п. 8): одобрить вид, построить трассы, принять их
 * этаж целиком; `candidate.json` route-задания. Запросы идут через клиент из OpenAPI.
 */

/** Ошибка разбора `candidate.json`: файл есть, но форма не та. */
export const CANDIDATE_INVALID = 'CAD_CANDIDATE_INVALID';

const pathOf = (params: ICadViewParams) => ({
  project_id: params.projectId,
  revision_id: params.revisionId,
  job_id: params.jobId,
  page_index: params.pageIndex,
  view: params.view,
});

/** После решения обновляются списки заданий, задание и диагностика видов (одобрение, принятие). */
const refresh = (client: QueryClient, params: ICadViewParams): void => {
  void client.invalidateQueries({ queryKey: cadKeys.jobs(params.projectId, params.revisionId) });
  void client.invalidateQueries({
    queryKey: cadKeys.job(params.projectId, params.revisionId, params.jobId),
  });
  void client.invalidateQueries({ queryKey: cadViewKeys.diagnostics(params) });
};

interface IDecisionInput {
  readonly comment?: string;
}

/** Одобрить вид: `params` - родитель и попытка, чей результат смотрел человек. */
export const useApproveCadView = (
  params: ICadViewParams,
): UseMutationResult<CadDecisionRead, unknown, IDecisionInput> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ comment }) =>
      unwrap(
        await approveCadView({
          throwOnError: true,
          path: pathOf(params),
          body: { attempt: params.attempt, comment: comment?.trim() ? comment.trim() : null },
        }),
      ),
    onSettled: () => refresh(client, params),
  });
};

interface IBuildInput {
  readonly floorElevationMm: number;
  readonly floorHeightMm: number;
}

/** Построить трассы по одобренному виду: возвращает поставленное route-задание. */
export const useBuildMepRoutes = (
  params: ICadViewParams,
): UseMutationResult<CadJobRead, unknown, IBuildInput> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ floorElevationMm, floorHeightMm }) =>
      unwrap(
        await createCadMepRoutes({
          throwOnError: true,
          path: pathOf(params),
          body: {
            attempt: params.attempt,
            floor_elevation_mm: floorElevationMm,
            floor_height_mm: floorHeightMm,
          },
        }),
      ),
    onSettled: () => refresh(client, params),
  });
};

/** Принять трассы этажа целиком: `params` - route-задание, его попытка, лист и вид. */
export const useAcceptMepRoutes = (
  params: ICadViewParams,
): UseMutationResult<CadDecisionRead, unknown, IDecisionInput> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ comment }) =>
      unwrap(
        await acceptCadMepRoutes({
          throwOnError: true,
          path: {
            project_id: params.projectId,
            revision_id: params.revisionId,
            job_id: params.jobId,
          },
          body: { attempt: params.attempt, comment: comment?.trim() ? comment.trim() : null },
        }),
      ),
    onSettled: () => refresh(client, params),
  });
};

/** `candidate.json` route-задания: длины, проблемы и допущения. Результат попытки неизменяем. */
export const useCadCandidate = (
  params: ICadViewParams,
  enabled: boolean,
): UseQueryResult<MepCandidate> =>
  useQuery({
    queryKey: ['cad-mep', 'candidate', params] as const,
    enabled,
    staleTime: 5 * 60_000,
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
    queryFn: async () => {
      const raw: unknown = unwrap(
        await downloadCadArtifact({
          throwOnError: true,
          path: {
            project_id: params.projectId,
            revision_id: params.revisionId,
            job_id: params.jobId,
            name: `${viewFolder(params.pageIndex, params.view)}/candidate.json`,
          },
        }),
      );
      const candidate = parseCandidate(raw);
      if (!candidate) {
        throw Object.assign(new Error('candidate.json не соответствует схеме'), {
          detail: { code: CANDIDATE_INVALID },
        });
      }
      return candidate;
    },
  });

/** Адрес скачивания 3D DXF трасс (доступен только после принятия). */
export const routesDxfUrl = (params: ICadViewParams): string =>
  cadArtifactUrl(
    params.projectId,
    params.revisionId,
    params.jobId,
    `${viewFolder(params.pageIndex, params.view)}/mep_routes.dxf`,
  );
