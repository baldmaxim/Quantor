'use client';

import type {
  CadJobRead,
  CadJobSummaryRead,
  CadPreviewRead,
  CadViewDiagnosticsRead,
} from '@quantor/api-client';
import { useMemo } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import { frameOf, type ICadFrame } from '@/lib/cad/frame';
import { useCadJob, useCadJobs } from '@/lib/cad/queries';
import { jobResultKind, latestSheetJobs, type SheetResultKind } from '@/lib/cad/sheet-results';
import {
  cadViewErrorText,
  useCadPreview,
  useCadView,
  type ICadViewParams,
} from '@/lib/cad/view-queries';
import {
  IDLE_VIEW_PARAMS,
  matchingPreview,
  overlayAvailability,
  pickWorkspaceView,
  workspaceViewParams,
  type IOverlayAvailability,
} from '@/lib/cad/workspace-cad';
import { jobCoversPage } from '@/lib/cad/workspace-url';

interface IInput {
  projectId: string;
  revisionId: string | null;
  /** Запросы разрешены: флаг включён и вкладка открывалась. */
  load: boolean;
  /** Индекс страницы листа в рабочей области. */
  pageIndex: number | null;
  /** Задание и вид из адреса. */
  jobParam: string | null;
  viewParam: number | null;
}

export interface IWorkspaceCadJobData {
  readonly jobsPending: boolean;
  readonly jobsError: string | null;
  readonly refetchJobs: () => void;
  /** Задания ревизии, новые сверху. */
  readonly jobs: readonly CadJobSummaryRead[];
  /** Показанное задание: из адреса, если оно закрывает лист, иначе последнее по листу. */
  readonly jobId: string | null;
  readonly kind: SheetResultKind | null;
  readonly job: CadJobRead | null;
  readonly views: readonly number[];
  readonly view: number | null;
  readonly params: ICadViewParams | null;
  readonly diagnostics: CadViewDiagnosticsRead | null;
  readonly diagnosticsError: { readonly code: string; readonly text: string } | null;
  readonly diagnosticsPending: boolean;
  readonly preview: CadPreviewRead | null;
  readonly previewPending: boolean;
  readonly previewError: string | null;
  readonly frame: ICadFrame | null;
  readonly availability: IOverlayAvailability | null;
}

/**
 * Задание, вид, диагностика и предпросмотр DXF для листа рабочей области.
 *
 * Выбор живёт в адресе (`job`, `view`): явное задание берётся, только если оно закрывает лист, а
 * без него - последнее задание листа и его первый вид. Так устаревший адрес после перехода на
 * другой лист не показывает чужой результат.
 */
export const useWorkspaceCadJob = ({
  projectId,
  revisionId,
  load,
  pageIndex,
  jobParam,
  viewParam,
}: IInput): IWorkspaceCadJobData => {
  const loadRevision = load ? revisionId : null;
  const jobs = useCadJobs(projectId, loadRevision);
  const items = useMemo(() => jobs.data?.items ?? [], [jobs.data]);
  const results = useMemo(() => latestSheetJobs(items), [items]);

  const latest = pageIndex !== null ? (results.get(pageIndex) ?? null) : null;
  const explicit =
    jobParam !== null && pageIndex !== null
      ? (items.find((item) => item.job_id === jobParam && jobCoversPage(item, pageIndex)) ?? null)
      : null;
  const summary = explicit ?? items.find((item) => item.job_id === latest?.jobId) ?? null;
  const jobId = summary?.job_id ?? null;
  const kind = summary ? jobResultKind(summary) : null;

  const jobQuery = useCadJob(projectId, loadRevision, jobId);
  const job = jobQuery.data?.job_id === jobId ? (jobQuery.data ?? null) : null;

  const pick = useMemo(
    () =>
      job && pageIndex !== null
        ? pickWorkspaceView(job, pageIndex, explicit !== null ? viewParam : null)
        : null,
    [job, pageIndex, explicit, viewParam],
  );
  const view = pick?.view ?? null;

  const params = useMemo<ICadViewParams | null>(
    () =>
      job && pageIndex !== null && revisionId !== null
        ? workspaceViewParams(projectId, revisionId, job, pageIndex, view)
        : null,
    [job, pageIndex, revisionId, projectId, view],
  );

  const diagnosticsQuery = useCadView(params ?? IDLE_VIEW_PARAMS, params !== null);
  const diagnostics = params !== null ? (diagnosticsQuery.data ?? null) : null;
  const previewQuery = useCadPreview(
    params ?? IDLE_VIEW_PARAMS,
    params !== null && diagnostics?.preview_available === true,
  );
  const preview = diagnostics ? matchingPreview(diagnostics, previewQuery.data) : null;
  const frameConfirmed = diagnostics?.frame.confirmed === true;
  const frame = useMemo(
    () => (preview && frameConfirmed ? frameOf(preview.frame) : null),
    [preview, frameConfirmed],
  );

  const diagnosticsError = diagnosticsQuery.isError
    ? cadViewErrorText(diagnosticsQuery.error)
    : jobQuery.isError
      ? { code: 'CAD_JOB', text: cadErrorText(jobQuery.error) }
      : null;

  return {
    jobsPending: jobs.isPending,
    jobsError: jobs.isError ? cadErrorText(jobs.error) : null,
    refetchJobs: () => void jobs.refetch(),
    jobs: items,
    jobId,
    kind,
    job,
    views: pick?.views ?? [],
    view,
    params,
    diagnostics,
    diagnosticsError,
    diagnosticsPending: params !== null && diagnostics === null && diagnosticsError === null,
    preview,
    previewPending: previewQuery.isPending,
    previewError: previewQuery.isError
      ? cadViewErrorText(previewQuery.error).text
      : previewQuery.data !== undefined && preview === null
        ? 'Предпросмотр не относится к DXF этой попытки.'
        : null,
    frame,
    availability: diagnostics ? overlayAvailability(diagnostics, preview, frame) : null,
  };
};
