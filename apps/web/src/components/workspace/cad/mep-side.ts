import type { CadJobSummaryRead, CadViewDiagnosticsRead } from '@quantor/api-client';

import { mepLayerCounts, type IMepCountSource } from '@/lib/cad/mep-layer-counts';
import {
  isMepLayerHidden,
  mepLayerTitle,
  presentMepLayers,
} from '@/lib/cad/mep-layers';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import type { IWorkspaceCadMep, IWorkspaceCadMepLayers, IWorkspaceCadSectionsLink } from './types';
import type { IWorkspaceCadRoutesData } from './useWorkspaceCadRoutes';

/**
 * Сборка данных трасс механики для правой панели: группа слоёв и вкладка «Трассы».
 * Чистые функции: состояние (маска скрытых слоёв, замечания, адрес) приходит снаружи.
 */

/** Слои трасс из превью route-задания; `null` - превью нет или трасс в нём нет. */
export const mepLayersOf = (
  previewLayers: readonly string[] | null,
  hiddenMask: number,
  setHidden: (names: readonly string[], hidden: boolean) => void,
  /** Превью трасс для чисел у слоёв приборов; нет - без чисел. */
  countSource: IMepCountSource | null = null,
): IWorkspaceCadMepLayers | null => {
  if (previewLayers === null) return null;
  const defs = presentMepLayers(previewLayers);
  if (defs.length === 0) return null;
  const names = defs.map((def) => def.name);
  return {
    names,
    titles: defs.map(mepLayerTitle),
    ...(countSource ? { counts: mepLayerCounts(countSource, names) } : {}),
    visible: new Set(
      names.map((name, index) => index).filter((index) => !isMepLayerHidden(hiddenMask, names[index] ?? '')),
    ),
    onToggle: (index) => {
      const name = names[index];
      if (name !== undefined) setHidden([name], !isMepLayerHidden(hiddenMask, name));
    },
    onSetHidden: (indices, hidden) =>
      setHidden(
        indices.flatMap((index) => (names[index] !== undefined ? [names[index] as string] : [])),
        hidden,
      ),
  };
};

interface IMepInput {
  readonly parent: ICadViewParams | null;
  readonly diagnostics: CadViewDiagnosticsRead;
  readonly routeSummary: CadJobSummaryRead | null;
  readonly routes: IWorkspaceCadRoutesData;
  readonly openRemarks: number | null;
  readonly view: number | null;
  readonly navigate: (changes: Record<string, string | null>) => void;
  /** Задание-родитель из адреса: к нему возвращает «К виду». */
  readonly parentJobId: string | null;
  /** Разрезы ревизии; `null` - ревизия не открыта. */
  readonly sections?: IWorkspaceCadSectionsLink | null;
}

/** Вкладка «Трассы»; `null` - параметры вида не получены. */
export const mepOf = ({
  parent,
  diagnostics,
  routeSummary,
  routes,
  openRemarks,
  view,
  navigate,
  parentJobId,
  sections = null,
}: IMepInput): IWorkspaceCadMep | null => {
  if (parent === null) return null;
  return {
    parent,
    approval: diagnostics.approval ?? null,
    revokedDecisions: diagnostics.revoked_decisions ?? [],
    routeJobs: diagnostics.route_jobs ?? [],
    route: routeSummary
      ? {
          summaryId: routeSummary.job_id,
          job: routes.job,
          params: routes.params,
          acceptance: routes.diagnostics?.acceptance ?? null,
          revokedDecisions: routes.diagnostics?.revoked_decisions ?? [],
          error: routes.error,
        }
      : null,
    openRemarks,
    onSelectRoute: (jobId) =>
      navigate({ job: jobId ?? parentJobId, view: view !== null ? String(view) : null }),
    sections,
  };
};
