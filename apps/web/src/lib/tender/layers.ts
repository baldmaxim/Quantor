'use client';

import {
  readTenderBuildingLayers,
  readTenderCalcView,
  readTenderViewLayers,
  type TenderBuildingLayersRead,
  type TenderCalcViewRead,
  type TenderViewLayersRead,
} from '@quantor/api-client';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { unwrap, useFeatures } from '@/lib/queries';

import { createLimiter } from './limiter';

/**
 * Слой «Расчёты» (ADR-0051): запросы геометрии расчётов TENDER на видах. Возможность закрыта флагом
 * `tender.exchange` и на сервере, и здесь (ADR-0023): без флага ни одного запроса не уходит.
 * Трассы движка закрыты флагом `cad.mep_engine`.
 */

export const TENDER_EXCHANGE_FEATURE = 'tender.exchange';
export const MEP_ENGINE_FEATURE = 'cad.mep_engine';

/** Предел одновременных запросов геометрии видов в 3D здания. */
export const GEOMETRY_CONCURRENCY = 6;
const GEOMETRY_GATE = createLimiter(GEOMETRY_CONCURRENCY);

/** Слой «Расчёты» открыт флагом `tender.exchange`. */
export const useTenderExchangeEnabled = (): boolean =>
  useFeatures()[TENDER_EXCHANGE_FEATURE] === true;

/** Трассы ВИС движка (`cad_mep`, `cad_eom`) открыты флагом `cad.mep_engine`. */
export const useMepEngineEnabled = (): boolean => useFeatures()[MEP_ENGINE_FEATURE] === true;

export const tenderLayerKeys = {
  view: (projectId: string, revisionId: string, pageIndex: number, view: number) =>
    ['tender', 'view-layers', projectId, revisionId, pageIndex, view] as const,
  geometry: (
    projectId: string,
    versionId: string,
    revisionId: string,
    pageIndex: number,
    view: number,
  ) => ['tender', 'geometry', projectId, versionId, revisionId, pageIndex, view] as const,
  building: (projectId: string) => ['tender', 'building-layers', projectId] as const,
};

const STALE_MS = 30_000;

export interface ITenderViewInput {
  readonly projectId: string;
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly view: number;
}

/** Действующие версии расчётов, у которых есть геометрия на виде, - вместе с геометрией. */
export const useTenderViewLayers = (
  input: ITenderViewInput | null,
): UseQueryResult<TenderViewLayersRead> => {
  const enabled = useTenderExchangeEnabled();
  return useQuery({
    queryKey: input
      ? tenderLayerKeys.view(input.projectId, input.revisionId, input.pageIndex, input.view)
      : ['tender', 'view-layers', 'none'],
    enabled: enabled && input !== null,
    staleTime: STALE_MS,
    queryFn: async () => {
      if (input === null) throw new Error('Вид не задан');
      return unwrap(
        await readTenderViewLayers({
          throwOnError: true,
          path: { project_id: input.projectId },
          query: {
            revision_id: input.revisionId,
            page_index: input.pageIndex,
            view: input.view,
          },
        }),
      );
    },
  });
};

/** Параметры чтения геометрии одной версии на одном виде. */
export interface ITenderGeometryInput extends ITenderViewInput {
  readonly versionId: string;
}

/** Запрос геометрии версии на виде с общим пределом одновременных запросов. */
export const tenderGeometryQuery = (input: ITenderGeometryInput) => ({
  queryKey: tenderLayerKeys.geometry(
    input.projectId,
    input.versionId,
    input.revisionId,
    input.pageIndex,
    input.view,
  ),
  staleTime: STALE_MS,
  queryFn: (): Promise<TenderCalcViewRead> =>
    GEOMETRY_GATE.run(async () =>
      unwrap(
        await readTenderCalcView({
          throwOnError: true,
          path: {
            project_id: input.projectId,
            version_id: input.versionId,
            revision_id: input.revisionId,
            page_index: input.pageIndex,
            view: input.view,
          },
        }),
      ),
    ),
});

const NO_GEOMETRY: ITenderGeometryInput = {
  projectId: '',
  versionId: '',
  revisionId: '',
  pageIndex: 0,
  view: 0,
};

/** Геометрия версии расчёта на одном виде. */
export const useTenderViewGeometry = (
  input: ITenderGeometryInput | null,
): UseQueryResult<TenderCalcViewRead> => {
  const enabled = useTenderExchangeEnabled();
  return useQuery({
    ...tenderGeometryQuery(input ?? NO_GEOMETRY),
    enabled: enabled && input !== null,
  });
};

/** Действующие версии проекта и виды, на которых у них есть геометрия (слой в 3D здания). */
export const useTenderBuildingLayers = (
  projectId: string | null,
): UseQueryResult<TenderBuildingLayersRead> => {
  const enabled = useTenderExchangeEnabled();
  return useQuery({
    queryKey: tenderLayerKeys.building(projectId ?? ''),
    enabled: enabled && projectId !== null,
    staleTime: STALE_MS,
    queryFn: async () =>
      unwrap(
        await readTenderBuildingLayers({
          throwOnError: true,
          path: { project_id: projectId ?? '' },
        }),
      ),
  });
};
