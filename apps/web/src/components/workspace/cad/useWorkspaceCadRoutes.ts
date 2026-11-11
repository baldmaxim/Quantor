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
import { cadViewErrorText, useCadPreview, useCadView, type ICadViewParams } from '@/lib/cad/view-queries';
import { IDLE_VIEW_PARAMS, workspaceViewParams } from '@/lib/cad/workspace-cad';

interface IInput {
  projectId: string;
  revisionId: string | null;
  /** Запросы разрешены: флаг включён и вкладка открывалась. */
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
  const readable = params !== null;

  const diagnosticsQuery = useCadView(params ?? IDLE_VIEW_PARAMS, readable, job?.status);
  const diagnostics = readable ? (diagnosticsQuery.data ?? null) : null;
  const previewQuery = useCadPreview(
    params ?? IDLE_VIEW_PARAMS,
    readable && diagnostics?.preview_available === true,
  );
  const preview = readable && diagnostics?.preview_available === true ? (previewQuery.data ?? null) : null;

  const error =
    routeId === null
      ? null
      : jobQuery.isError
        ? cadErrorText(jobQuery.error)
        : readable && diagnosticsQuery.isError
          ? cadViewErrorText(diagnosticsQuery.error).text
          : readable && previewQuery.isError
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
