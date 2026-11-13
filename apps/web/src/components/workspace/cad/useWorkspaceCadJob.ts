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
import { jobResultKind, sheetJobsForPage, type SheetResultKind } from '@/lib/cad/sheet-results';
import {
  cadViewErrorText,
  isQuietPreviewError,
  useCadPreview,
  useCadView,
  type ICadViewParams,
} from '@/lib/cad/view-queries';
import {
  IDLE_VIEW_PARAMS,
  matchingPreview,
  overlayAvailability,
  pickWorkspaceView,
  summaryViewParams,
  workspaceViewParams,
  type IOverlayAvailability,
} from '@/lib/cad/workspace-cad';
import { isRouteJob } from '@/lib/cad/mep-jobs';
import { pickAutoRoute } from '@/lib/cad/route-autoselect';
import { jobCoversPage } from '@/lib/cad/workspace-url';

interface IInput {
  projectId: string;
  revisionId: string | null;
  /** Запросы разрешены: флаг `cad.export` включён и ревизия открыта. */
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
  /** Задания ревизии, новые сверху (и преобразования, и трассы механики). */
  readonly jobs: readonly CadJobSummaryRead[];
  /** Выбранное route-задание (трассы механики) этого листа; `null` - показан сам вид. */
  readonly routeSummary: CadJobSummaryRead | null;
  /**
   * Route-задание, выбранное автоматически: самое новое успешное для показанного вида листа.
   * `null`, когда трассы выбраны явно (`routeSummary`) или для вида их нет.
   */
  readonly autoRoute: CadJobSummaryRead | null;
  /** Показанное задание: из адреса, если оно закрывает лист, иначе самое новое готовое по листу. */
  readonly jobId: string | null;
  /** Более новое задание листа после показанного (идёт или упало); `null` - нет или выбрано явно. */
  readonly updateJob: CadJobSummaryRead | null;
  /** Показанное задание листа (сводка); `null` - листа без задания. */
  readonly shownJob: CadJobSummaryRead | null;
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
 * без него - самое новое готовое задание листа (нет готового - самое новое) и его первый вид.
 * Так устаревший адрес после перехода на другой лист не показывает чужой результат.
 *
 * Route-задание (трассы механики) в «последнее задание листа» не входит. Если оно выбрано в адресе,
 * показан вид его родителя (DXF вида под трассами), а само задание отдаётся как `routeSummary`.
 * Без явного выбора трассы показанного вида подбираются сами (`autoRoute`).
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
  const converts = useMemo(() => items.filter((item) => !isRouteJob(item)), [items]);
  // Без явного задания: самое новое готовое задание листа (старый CAD не пропадает, пока идёт
  // или упало новое), без готового - самое новое; более новое неготовое отдаётся как обновление.
  const pageJobs = useMemo(
    () => (pageIndex !== null ? sheetJobsForPage(converts, pageIndex) : null),
    [converts, pageIndex],
  );
  const routeSummary =
    jobParam !== null && pageIndex !== null
      ? (items.find(
          (item) =>
            item.job_id === jobParam &&
            isRouteJob(item) &&
            item.page_index === pageIndex &&
            item.view !== null &&
            item.parent_job_id !== null,
        ) ?? null)
      : null;
  const explicit =
    routeSummary !== null
      ? (converts.find((item) => item.job_id === routeSummary.parent_job_id) ?? null)
      : jobParam !== null && pageIndex !== null
        ? (converts.find((item) => item.job_id === jobParam && jobCoversPage(item, pageIndex)) ??
          null)
        : null;
  const summary = explicit ?? pageJobs?.shown ?? null;
  const updateJob = explicit === null ? (pageJobs?.update ?? null) : null;
  const jobId = summary?.job_id ?? null;
  const kind = summary ? jobResultKind(summary) : null;

  const jobQuery = useCadJob(projectId, loadRevision, jobId);
  const job = jobQuery.data?.job_id === jobId ? (jobQuery.data ?? null) : null;

  const pick = useMemo(
    () =>
      job && pageIndex !== null
        ? pickWorkspaceView(
            job,
            pageIndex,
            routeSummary !== null ? routeSummary.view : explicit !== null ? viewParam : null,
          )
        : null,
    [job, pageIndex, explicit, viewParam, routeSummary],
  );
  const view = pick?.view ?? null;

  const params = useMemo<ICadViewParams | null>(
    () =>
      job && pageIndex !== null && revisionId !== null
        ? workspaceViewParams(projectId, revisionId, job, pageIndex, view)
        : null,
    [job, pageIndex, revisionId, projectId, view],
  );

  // Явный выбор (задание в адресе) приоритетнее; без него слои трасс берутся у новейшего успешного.
  const autoRoute = useMemo(
    () =>
      routeSummary === null ? pickAutoRoute(items, { parentJobId: jobId, pageIndex, view }) : null,
    [routeSummary, items, jobId, pageIndex, view],
  );

  // Завершённое задание читается сразу по сводке списка, не дожидаясь полного задания: вид,
  // диагностика и предпросмотр идут параллельно с ним. Пока полного задания нет, ответ
  // принимается только при совпадении попытки и вида (иначе запрос тихо отбрасывается).
  const earlyParams = useMemo<ICadViewParams | null>(
    () =>
      load && job === null && summary && pageIndex !== null && revisionId !== null
        ? summaryViewParams(
            projectId,
            revisionId,
            summary,
            pageIndex,
            routeSummary !== null ? routeSummary.view : explicit !== null ? viewParam : null,
          )
        : null,
    [load, job, summary, pageIndex, revisionId, projectId, routeSummary, explicit, viewParam],
  );
  const readParams = params ?? earlyParams;

  const diagnosticsQuery = useCadView(
    readParams ?? IDLE_VIEW_PARAMS,
    readParams !== null,
    job?.status ?? summary?.status,
  );
  const diagnostics = readParams !== null ? (diagnosticsQuery.data ?? null) : null;
  // Предпросмотр не ждёт диагностику: известный ответ «предпросмотра нет» его отключает, а
  // отсутствие (404) - не ошибка и не повторяется.
  const previewQuery = useCadPreview(
    readParams ?? IDLE_VIEW_PARAMS,
    readParams !== null && diagnostics?.preview_available !== false,
  );
  const preview = diagnostics ? matchingPreview(diagnostics, previewQuery.data) : null;
  const frameConfirmed = diagnostics?.frame.confirmed === true;
  const frame = useMemo(
    () => (preview && frameConfirmed ? frameOf(preview.frame) : null),
    [preview, frameConfirmed],
  );

  const diagnosticsError =
    diagnosticsQuery.isError && params !== null
      ? cadViewErrorText(diagnosticsQuery.error)
      : jobQuery.isError
        ? { code: 'CAD_JOB', text: cadErrorText(jobQuery.error) }
        : null;

  return {
    jobsPending: jobs.isPending,
    jobsError: jobs.isError ? cadErrorText(jobs.error) : null,
    refetchJobs: () => void jobs.refetch(),
    jobs: items,
    routeSummary,
    autoRoute,
    jobId,
    updateJob,
    shownJob: summary,
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
      ? isQuietPreviewError(previewQuery.error, diagnostics?.preview_available === true)
        ? null
        : cadViewErrorText(previewQuery.error).text
      : previewQuery.data !== undefined && preview === null
        ? 'Предпросмотр не относится к DXF этой попытки.'
        : null,
    frame,
    availability: diagnostics ? overlayAvailability(diagnostics, preview, frame) : null,
  };
};
