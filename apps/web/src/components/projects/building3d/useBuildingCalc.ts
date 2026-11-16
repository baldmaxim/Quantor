'use client';

import type {
  CadBuilding3dFloorRead,
  TenderBuildingLayerRead,
  TenderCalcViewRead,
} from '@quantor/api-client';
import { useQueries } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { floorKey } from '@/lib/cad/building3d-geometry';
import { floorsOfLayer, type IBuildingCalcItem } from '@/lib/tender/building-calc-layer';
import {
  tenderGeometryQuery,
  useTenderBuildingLayers,
  useTenderExchangeEnabled,
} from '@/lib/tender/layers';

/** Расчёт в панели просмотрщика: версия, этажи, на которых у неё есть геометрия, и состояние загрузки. */
export interface IBuildingCalcRow {
  readonly layer: TenderBuildingLayerRead;
  /** Этажей текущего здания, на которых у расчёта есть геометрия. */
  readonly floors: number;
  readonly selected: boolean;
  /** Загружено видов / всего (только у включённого расчёта). */
  readonly loaded: number;
  readonly failed: number;
}

export interface IBuildingCalc {
  /** Слой «Расчёты» доступен: флаг открыт и есть расчёты с геометрией на этажах здания. */
  readonly available: boolean;
  readonly rows: readonly IBuildingCalcRow[];
  readonly onToggle: (calcId: string, selected: boolean) => void;
  /** Геометрия включённых расчётов по этажам для холста; пока ничего не загружено - пусто. */
  readonly items: readonly IBuildingCalcItem[];
}

interface IWanted {
  readonly layer: TenderBuildingLayerRead;
  readonly floor: CadBuilding3dFloorRead;
}

const NO_FLOORS: readonly CadBuilding3dFloorRead[] = [];

interface ICombinedGeometry {
  readonly data: readonly (TenderCalcViewRead | undefined)[];
  readonly failed: readonly boolean[];
}

/**
 * Свод результатов запросов. Функция стабильна (на уровне модуля): она пересчитывается только при смене
 * результатов, а не на каждый рендер, и холст не пересобирает сцену от наведения мыши.
 */
const combineGeometry = (
  results: readonly { readonly data: TenderCalcViewRead | undefined; readonly isError: boolean }[],
): ICombinedGeometry => ({
  data: results.map((result) => result.data),
  failed: results.map((result) => result.isError),
});

/**
 * Слой «Расчёты» в просмотрщике объекта: список расчётов проекта с геометрией на этажах здания,
 * переключатель и ленивая загрузка видов - только включённых расчётов и только этажей здания; одновременно
 * не больше 6 запросов (`GEOMETRY_CONCURRENCY`). По умолчанию все расчёты выключены.
 */
export const useBuildingCalc = (
  projectId: string,
  floors: readonly CadBuilding3dFloorRead[] = NO_FLOORS,
): IBuildingCalc => {
  const enabled = useTenderExchangeEnabled();
  const layersQuery = useTenderBuildingLayers(projectId);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());

  const rows = useMemo(
    () =>
      (layersQuery.data?.layers ?? []).flatMap((layer) => {
        const count = floorsOfLayer(layer, floors).length;
        return count > 0 ? [{ layer, count }] : [];
      }),
    [layersQuery.data, floors],
  );

  const wanted = useMemo<IWanted[]>(
    () =>
      rows
        .filter((row) => selected.has(row.layer.calc_id))
        .flatMap((row) => floorsOfLayer(row.layer, floors).map((floor) => ({ layer: row.layer, floor }))),
    [rows, selected, floors],
  );

  const loaded = useQueries({
    queries: wanted.map(({ layer, floor }) => ({
      ...tenderGeometryQuery({
        projectId,
        versionId: layer.version_id,
        revisionId: floor.revision_id,
        pageIndex: floor.page_index,
        view: floor.view,
      }),
      enabled,
    })),
    combine: combineGeometry,
  });

  const items = useMemo<IBuildingCalcItem[]>(
    () =>
      wanted.flatMap(({ layer, floor }, index) => {
        const data: TenderCalcViewRead | undefined = loaded.data[index];
        if (data === undefined) return [];
        return [
          {
            floorKey: floorKey(floor),
            layer: {
              calc_id: layer.calc_id,
              version_id: layer.version_id,
              title: layer.title,
              number: layer.number,
              label: layer.label,
              system: layer.system,
              discipline: layer.discipline,
              base_stale: data.base_stale,
              polylines: data.polylines,
              elements: data.elements,
            },
          },
        ];
      }),
    [wanted, loaded.data],
  );

  const state = useMemo<IBuildingCalcRow[]>(
    () =>
      rows.map(({ layer, count }) => {
        const mine = wanted.flatMap((item, index) => (item.layer.calc_id === layer.calc_id ? [index] : []));
        return {
          layer,
          floors: count,
          selected: selected.has(layer.calc_id),
          loaded: mine.filter((index) => loaded.data[index] !== undefined).length,
          failed: mine.filter((index) => loaded.failed[index] === true).length,
        };
      }),
    [rows, wanted, loaded, selected],
  );

  return {
    available: enabled && rows.length > 0,
    rows: state,
    onToggle: (calcId, on) =>
      setSelected((current) => {
        const next = new Set(current);
        if (on) next.add(calcId);
        else next.delete(calcId);
        return next;
      }),
    items,
  };
};

