'use client';

import {
  startCadZonesAuto,
  type CadPipelineSheetRead,
  type CadPipelineStageRead,
} from '@quantor/api-client';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { building3dKeys } from '@/lib/cad/building3d-queries';
import { cadErrorText } from '@/lib/cad/errors';
import {
  sheetSteps,
  sheetSummary,
  type IPipelineStep,
  type IPipelineSummary,
} from '@/lib/cad/pipeline';
import { cadPipelineKey, useCadPipeline } from '@/lib/cad/pipeline-queries';
import { cadKeys } from '@/lib/cad/queries';
import { zoneKeys } from '@/lib/cad/zones-queries';
import { unwrap } from '@/lib/queries';

/**
 * Конвейер CAD открытого листа для рабочей области: один запрос на ревизию, шаги и итог листа,
 * запуск автоматической разметки зон и самообновление холста и панелей, когда этап закончился.
 */

export interface IWorkspaceCadPipelineParams {
  readonly projectId: string;
  readonly revisionId: string | null;
  /** Индекс страницы открытого листа. */
  readonly pageIndex: number | null;
  /** Флаг `cad.export`. */
  readonly enabled: boolean;
}

export interface IWorkspaceCadPipeline {
  /** Лист в конвейере; `null` - лист ещё не обрабатывался или данные не получены. */
  readonly sheet: CadPipelineSheetRead | null;
  /** Все листы ревизии из конвейера (для подписей этажом в списке листов); данных нет - пусто. */
  readonly sheets: readonly CadPipelineSheetRead[];
  readonly steps: readonly IPipelineStep[];
  readonly summary: IPipelineSummary | null;
  readonly isPending: boolean;
  readonly isError: boolean;
  readonly refetch: () => void;
  readonly startAutoZones: () => Promise<void>;
  readonly startingZones: boolean;
  readonly zonesError: string | null;
}

type StageName = 'convert' | 'walls' | 'zones' | 'routes' | 'floor3d';

interface IStageSnapshot {
  readonly stage: StageName;
  readonly jobId: string;
  readonly active: boolean;
}

const NO_SHEETS: readonly CadPipelineSheetRead[] = [];

const isActive = (stage: CadPipelineStageRead): boolean =>
  stage.status === 'queued' || stage.status === 'running';

/** Этапы листа по ключам «этап:страница:вид» (у преобразования вид не нужен). */
const snapshotOf = (sheet: CadPipelineSheetRead): Map<string, IStageSnapshot> => {
  const result = new Map<string, IStageSnapshot>();
  const put = (key: string, stage: StageName, value: CadPipelineStageRead | null) => {
    if (value !== null) {
      result.set(key, { stage, jobId: value.job_id, active: isActive(value) });
    }
  };
  put('convert', 'convert', sheet.convert);
  for (const view of sheet.views) {
    const at = `${view.page}:${view.view}`;
    put(`walls:${at}`, 'walls', view.walls);
    put(`zones:${at}`, 'zones', view.zones);
    put(`routes:${at}`, 'routes', view.routes);
    put(`floor3d:${at}`, 'floor3d', view.floor3d);
  }
  return result;
};

/** Этапы, у которых был идущий этап, а теперь его нет (закончился или заменён другим заданием). */
export const finishedStages = (
  before: ReadonlyMap<string, IStageSnapshot>,
  after: ReadonlyMap<string, IStageSnapshot>,
): StageName[] => {
  const done = new Set<StageName>();
  before.forEach((was, key) => {
    if (!was.active) return;
    const now = after.get(key);
    if (now === undefined || now.jobId !== was.jobId || !now.active) done.add(was.stage);
  });
  return [...done];
};

/** Сбрасывает ответы, которые зависят от закончившегося этапа. Ключи - по префиксу. */
export const invalidateForStage = (
  client: QueryClient,
  projectId: string,
  revisionId: string,
  stage: StageName,
): void => {
  const reset = (queryKey: readonly unknown[]) => void client.invalidateQueries({ queryKey });
  const constructions = () => reset(['cad-constructions', projectId, revisionId]);
  const floor3d = () => {
    reset(['cad-floor3d', projectId, revisionId]);
    reset(building3dKeys.project(projectId));
  };

  if (stage === 'convert') {
    reset(cadKeys.jobs(projectId, revisionId));
    reset(['cad', projectId, revisionId, 'job']);
    reset(['cad-view']);
  } else if (stage === 'walls') {
    constructions();
    floor3d();
  } else if (stage === 'zones') {
    reset(zoneKeys.revision(projectId, revisionId));
  } else if (stage === 'routes') {
    reset(cadKeys.jobs(projectId, revisionId));
    reset(['cad-view']);
    reset(['cad-mep']);
    floor3d();
  } else {
    reset(cadKeys.jobs(projectId, revisionId));
    floor3d();
  }
};

export const useWorkspaceCadPipeline = ({
  projectId,
  revisionId,
  pageIndex,
  enabled,
}: IWorkspaceCadPipelineParams): IWorkspaceCadPipeline => {
  const client = useQueryClient();
  const query = useCadPipeline(projectId, revisionId, enabled);
  const data = query.data;

  const sheet = useMemo(
    () => (pageIndex === null ? null : (data?.sheets.find((row) => row.page_index === pageIndex) ?? null)),
    [data, pageIndex],
  );

  // Лист, которого нет в конвейере, - с чистого листа: калибровка и преобразование впереди.
  const steps = useMemo<readonly IPipelineStep[]>(() => {
    if (sheet !== null) return sheetSteps(sheet);
    if (pageIndex === null || !data) return [];
    return sheetSteps({ page_index: pageIndex, page_label: null, calibrated: false, convert: null, views: [] });
  }, [sheet, pageIndex, data]);
  const summary = useMemo(() => (sheet ? sheetSummary(sheet) : null), [sheet]);

  // Предыдущий снимок этапов листа: переход «идёт -> закончился» сбрасывает связанные запросы.
  const previous = useRef<{ page: number | null; stages: Map<string, IStageSnapshot> } | null>(null);
  useEffect(() => {
    if (revisionId === null || !data) return;
    const stages = sheet ? snapshotOf(sheet) : new Map<string, IStageSnapshot>();
    const before = previous.current;
    previous.current = { page: pageIndex, stages };
    if (before === null || before.page !== pageIndex) return;
    const finished = finishedStages(before.stages, stages);
    if (finished.length === 0) return;
    finished.forEach((stage) => invalidateForStage(client, projectId, revisionId, stage));
    void client.invalidateQueries({ queryKey: cadPipelineKey(projectId, revisionId) });
  }, [client, data, sheet, pageIndex, projectId, revisionId]);

  const [startingZones, setStartingZones] = useState(false);
  const [zonesError, setZonesError] = useState<string | null>(null);
  const starting = useRef(false);

  const startAutoZones = useCallback(async (): Promise<void> => {
    const view = sheet?.views.find((row) => row.has_dxf);
    const jobId = sheet?.convert?.job_id;
    if (starting.current || revisionId === null || !sheet || !view || !jobId) return;
    starting.current = true;
    setStartingZones(true);
    setZonesError(null);
    try {
      unwrap(
        await startCadZonesAuto({
          throwOnError: true,
          path: { project_id: projectId, job_id: jobId, page_index: sheet.page_index, view: view.view },
        }),
      );
    } catch (error) {
      setZonesError(cadErrorText(error));
    } finally {
      starting.current = false;
      setStartingZones(false);
      void client.invalidateQueries({ queryKey: cadPipelineKey(projectId, revisionId) });
    }
  }, [client, projectId, revisionId, sheet]);

  const { refetch } = query;
  const reload = useCallback(() => void refetch(), [refetch]);

  return {
    sheet,
    sheets: data?.sheets ?? NO_SHEETS,
    steps,
    summary,
    isPending: enabled && revisionId !== null && query.isPending,
    isError: query.isError,
    refetch: reload,
    startAutoZones,
    startingZones,
    zonesError,
  };
};
