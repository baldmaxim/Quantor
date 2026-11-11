'use client';

import type {
  CadJobRead,
  CadJobSummaryRead,
  CadPreviewRead,
  CadViewDiagnosticsRead,
} from '@quantor/api-client';
import { useMemo } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import { useCadJob } from '@/lib/cad/queries';
import {
  cadViewErrorText,
  isQuietPreviewError,
  useCadPreview,
  useCadView,
  type ICadViewParams,
} from '@/lib/cad/view-queries';
import { IDLE_VIEW_PARAMS, summaryViewParams, workspaceViewParams } from '@/lib/cad/workspace-cad';

interface IInput {
  projectId: string;
  revisionId: string | null;
  /** Запросы разрешены: флаг `cad.export` включён и ревизия открыта. */
  load: boolean;
  pageIndex: number | null;
  /** Route-задание (выбранное явно или автоматически); `null` - трасс нет и ничего не читается. */
  route: CadJobSummaryRead | null;
}

export interface IWorkspaceCadRoutesData {
  /** Полное route-задание (отметки, попытка, ход); `null` - ещё читается или не выбрано. */
  readonly job: CadJobRead | null;
  /** Параметры чтения вида трасс; `null` - результата ещё нет (идёт, отказ). */
  readonly params: ICadViewParams | null;
  readonly diagnostics: CadViewDiagnosticsRead | null;
  readonly preview: CadPreviewRead | null;
  /** Текст отказа чтения задания, вида или превью. */
  readonly error: string | null;
}

/**
 * Данные выбранного route-задания: само задание, диагностика и превью вида трасс.
 * Кадр координат трасс - кадр родителя (тот же DXF в мм), его берёт вызывающий.
 */
export const useWorkspaceCadRoutes = ({
  projectId,
  revisionId,
  load,
  pageIndex,
  route,
}: IInput): IWorkspaceCadRoutesData => {
  const routeId = route?.job_id ?? null;
  const loadRevision = load && routeId !== null ? revisionId : null;

  const jobQuery = useCadJob(projectId, loadRevision, routeId);
  const job = routeId !== null && jobQuery.data?.job_id === routeId ? jobQuery.data : null;

  const params = useMemo<ICadViewParams | null>(
    () =>
      job && route && pageIndex !== null && revisionId !== null
        ? workspaceViewParams(projectId, revisionId, job, pageIndex, route.view)
        : null,
    [job, route, pageIndex, revisionId, projectId],
  );
  // Диагностика и предпросмотр трасс идут параллельно с чтением полного задания: у завершённого
  // route-задания вид и страница известны из сводки. Ответ другой попытки отбрасывается сам.
  const earlyParams = useMemo<ICadViewParams | null>(
    () =>
      load &&
      job === null &&
      route &&
      pageIndex !== null &&
      revisionId !== null &&
      route.view !== null
        ? summaryViewParams(projectId, revisionId, route, pageIndex, route.view)
        : null,
    [load, job, route, pageIndex, revisionId, projectId],
  );
  const readParams = params ?? earlyParams;
  const readable = params !== null;

  const diagnosticsQuery = useCadView(
    readParams ?? IDLE_VIEW_PARAMS,
    readParams !== null,
    job?.status ?? route?.status,
  );
  const diagnostics = readParams !== null ? (diagnosticsQuery.data ?? null) : null;
  const previewQuery = useCadPreview(
    readParams ?? IDLE_VIEW_PARAMS,
    readParams !== null && diagnostics?.preview_available !== false,
  );
  const preview = diagnostics?.preview_available === true ? (previewQuery.data ?? null) : null;

  const previewPromised = diagnostics?.preview_available === true;
  const error =
    routeId === null
      ? null
      : jobQuery.isError
        ? cadErrorText(jobQuery.error)
        : readable && diagnosticsQuery.isError
          ? cadViewErrorText(diagnosticsQuery.error).text
          : readable &&
              previewQuery.isError &&
              !isQuietPreviewError(previewQuery.error, previewPromised)
            ? cadViewErrorText(previewQuery.error).text
            : null;

  return {
    job,
    params,
    diagnostics,
    preview,
    error,
  };
};
