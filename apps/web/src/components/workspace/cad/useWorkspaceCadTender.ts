'use client';

import type { TenderViewLayerRead } from '@quantor/api-client';
import { useEffect, useMemo, useRef, useState } from 'react';

import type { ICadTenderLayers } from '@/components/cad/tender/CadTenderLayers';
import type { ICadTenderPicker } from '@/components/cad/tender/CadTenderPicker';
import type { ICadFrame, IPageSize } from '@/lib/cad/frame';
import { tenderInfo, type ITenderRef } from '@/lib/tender/info';
import { readTenderColors } from '@/lib/tender/colors';
import { buildTenderPaintData, layerTitle } from '@/lib/tender/geometry';
import { useTenderViewLayers } from '@/lib/tender/layers';
import { createTenderPainter, hitTender } from '@/lib/tender/painter';
import { systemColorToken } from '@/lib/tender/systems';
import { tenderLayerKey } from '@/lib/tender/view-key';
import { useTheme } from '@/lib/theme';
import type { Camera } from '@/lib/viewer/camera';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';

import type { ICadLayerVisibility } from './useCadLayerVisibility';

interface IUseWorkspaceCadTenderInput {
  readonly projectId: string;
  readonly revisionId: string | null;
  readonly pageIndex: number | null;
  readonly view: number | null;
  readonly frame: ICadFrame | null;
  readonly pageSize: IPageSize | null;
  readonly camera: Camera;
  /** Видимость слоёв листа: расчёты хранятся в ней же по ключам `tender:<calc_id>`. */
  readonly visibility: Pick<ICadLayerVisibility, 'hiddenLayerNames' | 'setNamesHidden'>;
  /** Геометрия CAD сейчас показана на листе (режим «PDF» её не рисует). */
  readonly shown: boolean;
  /** Идентификатор расчёта из адреса («Открыть на листе»): слой гарантированно включён. */
  readonly tenderParam: string | null;
}

export interface IWorkspaceCadTender {
  /** Группа «Расчёты» панели «Слои»; `null` - на виде расчётов нет. */
  readonly layers: ICadTenderLayers | null;
  /** Слой наложения; `null` - рисовать нечего. Нужен `clear`: слой без других рисовальщиков чистит холст. */
  readonly painter: (clear: boolean) => LayerPainter | null;
  /** Выбор объекта щелчком; `null` - выключен. */
  readonly picker: ICadTenderPicker | null;
}

const NO_LAYERS: readonly TenderViewLayerRead[] = [];

/**
 * Слой «Расчёты» на плане (ADR-0051): версии расчётов на виде листа, видимость в общем хранилище слоёв
 * CAD, наложение по кадру вида и выбор щелчком. Без флага `tender.exchange` запросов нет.
 */
export const useWorkspaceCadTender = ({
  projectId,
  revisionId,
  pageIndex,
  view,
  frame,
  pageSize,
  camera,
  visibility,
  shown,
  tenderParam,
}: IUseWorkspaceCadTenderInput): IWorkspaceCadTender => {
  const theme = useTheme();
  const colors = useMemo(() => {
    void theme;
    return readTenderColors();
  }, [theme]);

  const input = useMemo(
    () =>
      revisionId !== null && pageIndex !== null && view !== null
        ? { projectId, revisionId, pageIndex, view }
        : null,
    [projectId, revisionId, pageIndex, view],
  );
  const query = useTenderViewLayers(input);
  const allLayers = query.data?.layers ?? NO_LAYERS;
  const { hiddenLayerNames, setNamesHidden } = visibility;

  // «Открыть на листе»: расчёт из адреса включается один раз на значение адреса.
  const appliedParam = useRef<string | null>(null);
  useEffect(() => {
    if (tenderParam === null || appliedParam.current === tenderParam) return;
    if (!allLayers.some((layer) => layer.calc_id === tenderParam)) return;
    appliedParam.current = tenderParam;
    const key = tenderLayerKey(tenderParam);
    if (hiddenLayerNames.has(key)) setNamesHidden([key], false);
  }, [tenderParam, allLayers, hiddenLayerNames, setNamesHidden]);

  const visibleLayers = useMemo(
    () => allLayers.filter((layer) => !hiddenLayerNames.has(tenderLayerKey(layer.calc_id))),
    [allLayers, hiddenLayerNames],
  );

  const layers = useMemo<ICadTenderLayers | null>(
    () =>
      allLayers.length === 0
        ? null
        : {
            items: allLayers.map((layer) => ({
              calcId: layer.calc_id,
              title: layerTitle(layer),
              color: `var(${systemColorToken(layer.system)})`,
              visible: !hiddenLayerNames.has(tenderLayerKey(layer.calc_id)),
              baseStale: layer.base_stale,
            })),
            onSetVisible: (calcIds, visible) =>
              setNamesHidden(calcIds.map(tenderLayerKey), !visible),
          },
    [allLayers, hiddenLayerNames, setNamesHidden],
  );

  // --- выбор объекта: плашка у точки клика, выделение остаётся после закрытия плашки ---
  const sheetKey = input ? `${input.revisionId}:${input.pageIndex}:${input.view}` : null;
  const [picked, setPicked] = useState<{
    readonly sheetKey: string | null;
    readonly ref: ITenderRef;
    readonly anchor: { x: number; y: number } | null;
  } | null>(null);
  const selected = picked !== null && picked.sheetKey === sheetKey ? picked : null;

  const paintData = useMemo(
    () =>
      shown && frame !== null && pageSize !== null && visibleLayers.length > 0
        ? buildTenderPaintData({
            layers: visibleLayers,
            frame,
            page: pageSize,
            colorOf: colors.colorOf,
            accent: colors.accent,
            halo: colors.halo,
            selected: selected?.ref ?? null,
          })
        : null,
    [shown, frame, pageSize, visibleLayers, colors, selected?.ref],
  );

  const painter = useMemo(
    () => (clear: boolean) => (paintData ? createTenderPainter(paintData, { clear }) : null),
    [paintData],
  );

  const picker = useMemo<ICadTenderPicker | null>(
    () =>
      paintData !== null && pageSize !== null
        ? {
            camera,
            page: pageSize,
            hit: (point, tolerance) => hitTender(paintData, point, tolerance),
            onPick: (ref, anchor) => setPicked(ref === null ? null : { sheetKey, ref, anchor }),
            onDismiss: () =>
              setPicked((current) =>
                current === null || current.anchor === null ? current : { ...current, anchor: null },
              ),
            popover:
              selected?.anchor != null
                ? { info: tenderInfo(selected.ref), anchor: selected.anchor }
                : null,
          }
        : null,
    [paintData, pageSize, camera, sheetKey, selected],
  );

  return { layers, painter, picker };
};
