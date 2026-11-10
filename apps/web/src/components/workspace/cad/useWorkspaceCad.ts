'use client';

import type { SheetRead } from '@quantor/api-client';
import { useEffect, useMemo, useState } from 'react';

import { useCadRemarks, type IRemarkDraft } from '@/components/cad/viewer/useCadRemarks';
import type { ViewportSheet } from '@/components/viewer/DrawingViewport';
import { createCadPainter } from '@/lib/cad/cad-painter';
import { frameOf } from '@/lib/cad/frame';
import { readCadPaintColors } from '@/lib/cad/paint-colors';
import { useCadJob, useCadJobs } from '@/lib/cad/queries';
import type { BboxPt, IRemarkBinding } from '@/lib/cad/remarks';
import { composePainters, createRemarksPainter } from '@/lib/cad/remarks-painter';
import { latestSheetJobs } from '@/lib/cad/sheet-results';
import { cadErrorText } from '@/lib/cad/errors';
import {
  cadViewErrorText,
  useCadPreview,
  useCadView,
  type ICadViewParams,
} from '@/lib/cad/view-queries';
import {
  IDLE_REMARK_BINDING,
  IDLE_VIEW_PARAMS,
  WORKSPACE_DRAFT_ID,
  cadPageHref,
  matchingPreview,
  overlayAvailability,
  overlayPaintData,
  pickWorkspaceView,
  workspaceMarks,
  workspaceViewParams,
} from '@/lib/cad/workspace-cad';
import { useTheme } from '@/lib/theme';
import type { Camera, Viewport } from '@/lib/viewer/camera';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';
import { useWorkspaceStore } from '@/store/workspace';

import { tabFromQuery } from './left-tab';
import type { IWorkspaceCadPanelProps, IWorkspaceCadRemarks, WorkspaceCadState } from './types';

interface IUseWorkspaceCadInput {
  projectId: string;
  revisionId: string | null;
  sheet: Pick<SheetRead, 'page_index' | 'page_label'> | null;
  /** Размер листа у отрисовщика (pt при масштабе 1); `null` - ещё не известен. */
  page: ViewportSheet | null;
  camera: Camera;
  viewportSize: () => Viewport;
  /** Флаг `cad.export` включён. Без него ни одного запроса CAD не уходит. */
  enabled: boolean;
  /** Открыта вкладка CAD. */
  active: boolean;
  /** Значение `?tab=` из адреса. */
  tabParam: string | null;
}

export interface IWorkspaceCad {
  /** Слой DXF и рамок замечаний для `<DrawingViewport extraPainter>`. */
  painter: LayerPainter | null;
  /** Данные слоя захвата рамки; `null` - режим отметки выключен. */
  capture: {
    camera: Camera;
    page: { width: number; height: number };
    onDrawn: (bbox: BboxPt) => void;
  } | null;
  panel: IWorkspaceCadPanelProps;
}

/**
 * CAD текущего листа в рабочей области: последнее задание по листу, вид, наложение DXF и
 * замечания. Один хук связывает вкладку и холст, чтобы страница получила лишь painter,
 * слой захвата и пропсы панели.
 *
 * Запросы идут только при включённом `cad.export` и только после первого открытия вкладки:
 * наложение при этом остаётся и на других вкладках (переключатель в хранилище рабочей области),
 * а рамки замечаний рисуются, пока вкладка открыта. Панорама и зум по-прежнему идут мимо
 * состояния React: камера передаётся холсту как есть (ADR-0004).
 */
export const useWorkspaceCad = ({
  projectId,
  revisionId,
  sheet,
  page,
  camera,
  viewportSize,
  enabled,
  active,
  tabParam,
}: IUseWorkspaceCadInput): IWorkspaceCad => {
  const theme = useTheme();
  const colors = useMemo(() => {
    void theme;
    return readCadPaintColors();
  }, [theme]);

  const setLeftTab = useWorkspaceStore((state) => state.setLeftTab);
  const overlayOn = useWorkspaceStore((state) => state.cadOverlay);
  const setOverlayOn = useWorkspaceStore((state) => state.setCadOverlay);

  // `?tab=cad` открывает вкладку один раз на значение адреса. Вкладку закрывает флаг в странице,
  // поэтому выбор можно сохранить и до прихода меты.
  useEffect(() => {
    const tab = tabFromQuery(tabParam);
    if (tab) setLeftTab(tab);
  }, [tabParam, setLeftTab]);

  // Данные грузятся после первого открытия вкладки и дальше не выключаются: так наложение
  // держится на других вкладках, а тому, кто CAD не открывал, запросы не уходят.
  const [opened, setOpened] = useState(false);
  if (enabled && active && !opened) setOpened(true);
  const load = enabled && opened && revisionId !== null;
  const loadRevision = load ? revisionId : null;

  const pageIndex = sheet?.page_index ?? null;
  const jobs = useCadJobs(projectId, loadRevision);
  const results = useMemo(() => latestSheetJobs(jobs.data?.items ?? []), [jobs.data]);
  const result = pageIndex !== null ? (results.get(pageIndex) ?? null) : null;
  const recognizedJobId = result?.kind === 'recognized' ? result.jobId : null;
  const jobQuery = useCadJob(projectId, loadRevision, recognizedJobId);
  const job = jobQuery.data ?? null;

  const [chosen, setChosen] = useState<{ readonly key: string; readonly view: number } | null>(
    null,
  );
  const chosenKey = `${recognizedJobId}:${pageIndex}`;
  const chosenView = chosen !== null && chosen.key === chosenKey ? chosen.view : null;
  const pick = useMemo(
    () => (job && pageIndex !== null ? pickWorkspaceView(job, pageIndex, chosenView) : null),
    [job, pageIndex, chosenView],
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
  const availability = diagnostics ? overlayAvailability(diagnostics, preview, frame) : null;
  const overlayAvailable = availability?.available === true;

  const pageSize = useMemo(
    () => (page ? { width: page.width, height: page.height } : null),
    [page],
  );
  const paintData = useMemo(
    () =>
      overlayOn && overlayAvailable
        ? overlayPaintData(preview, frame, pageSize, colors.ink, colors.layers)
        : null,
    [overlayOn, overlayAvailable, preview, frame, pageSize, colors.ink, colors.layers],
  );
  const cadPainter = useMemo(() => (paintData ? createCadPainter(paintData) : null), [paintData]);

  // --- замечания ---
  const binding = useMemo<IRemarkBinding | null>(
    () =>
      params && diagnostics
        ? {
            projectId: params.projectId,
            revisionId: params.revisionId,
            jobId: params.jobId,
            attempt: params.attempt,
            pageIndex: params.pageIndex,
            legacyPdfPage: diagnostics.legacy_pdf_page,
            view: params.view,
            dxfSha256: diagnostics.dxf?.sha256 ?? null,
          }
        : null,
    [params, diagnostics],
  );
  const store = useCadRemarks(binding ?? IDLE_REMARK_BINDING, binding !== null);

  const [marking, setMarking] = useState(false);
  const [draft, setDraft] = useState<BboxPt | null>(null);
  const [activeRemark, setActiveRemark] = useState<string | null>(null);

  // Участок и выбор принадлежат виду: на другом листе или виде они означали бы другое место.
  // Закрытая вкладка тоже гасит режим отметки, чтобы он не включился сам при возвращении.
  const scope = binding ? `${binding.jobId}:${binding.pageIndex}:${binding.view}` : null;
  const [seenScope, setSeenScope] = useState(scope);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setMarking(false);
    setDraft(null);
    setActiveRemark(null);
  }
  if (!active && marking) setMarking(false);

  const markDisabledReason =
    page === null ? 'Отметка станет доступна, когда загрузится страница PDF.' : null;
  const markingOn = marking && active && markDisabledReason === null;

  // Esc отменяет режим отметки, пока он включён.
  useEffect(() => {
    if (!markingOn) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMarking(false);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [markingOn]);

  const marks = useMemo(
    () => (active ? workspaceMarks(store.remarks, draft, pageSize) : []),
    [active, store.remarks, draft, pageSize],
  );
  const painter = useMemo<LayerPainter | null>(
    () =>
      composePainters(
        cadPainter,
        marks.length > 0
          ? createRemarksPainter(
              {
                marks,
                colors: colors.remarks,
                activeId: draft ? WORKSPACE_DRAFT_ID : activeRemark,
              },
              { clear: cadPainter === null },
            )
          : null,
      ),
    [cadPainter, marks, colors.remarks, draft, activeRemark],
  );

  // Участок нарисован: режим отметки гаснет, чтобы лист снова можно было двигать.
  const handleDrawn = (bbox: BboxPt) => {
    setDraft(bbox);
    setMarking(false);
  };
  // Черновик закрывается только после ответа сервера: при отказе участок и текст остаются.
  const saveDraft = async (value: IRemarkDraft) => {
    if (!draft) return;
    const created = await store.add(draft, value);
    if (!created) return;
    setActiveRemark(created.id);
    setDraft(null);
  };

  const remarks: IWorkspaceCadRemarks | null = binding
    ? {
        binding,
        store,
        page: pageSize,
        marking: markingOn,
        onMarkingChange: setMarking,
        markDisabledReason,
        draft,
        onDraftSave: (value) => void saveDraft(value),
        onDraftCancel: () => setDraft(null),
        activeId: activeRemark,
        onActivate: setActiveRemark,
        onFocusCamera: (state) => camera.set(state),
        viewport: viewportSize,
      }
    : null;

  // --- панель ---
  let state: WorkspaceCadState;
  if (pageIndex === null || revisionId === null) state = 'no-sheet';
  else if (jobs.isPending) state = 'loading';
  else if (jobs.isError) state = 'error';
  else state = result === null ? 'none' : result.kind;

  const cadHref = cadPageHref(
    projectId,
    revisionId ?? '',
    result === null
      ? null
      : {
          jobId: result.jobId,
          page: result.kind === 'recognized' ? pageIndex : null,
          view: result.kind === 'recognized' ? view : null,
        },
  );

  const diagnosticsError = diagnosticsQuery.isError
    ? cadViewErrorText(diagnosticsQuery.error)
    : jobQuery.isError
      ? { code: 'CAD_JOB', text: cadErrorText(jobQuery.error) }
      : null;

  const panel: IWorkspaceCadPanelProps = {
    state,
    sheetLabel: sheet ? (sheet.page_label ?? String(sheet.page_index + 1)) : null,
    cadHref,
    loadError: jobs.isError ? cadErrorText(jobs.error) : null,
    onRetry: () => void jobs.refetch(),
    recognized:
      state === 'recognized'
        ? {
            resultStatus: job?.result_status ?? null,
            loading:
              diagnosticsError === null &&
              (job === null || (view !== null && diagnostics === null)),
            error: diagnosticsError,
            diagnostics,
            views: pick?.views ?? [],
            view,
            onViewChange: (next) => setChosen({ key: chosenKey, view: next }),
            overlay: overlayOn,
            overlayAvailable,
            overlayReason: availability?.reason ?? null,
            overlayLoading:
              overlayAvailable && overlayOn && preview === null && previewQuery.isPending,
            overlayError: previewQuery.isError
              ? cadViewErrorText(previewQuery.error).text
              : previewQuery.data !== undefined && preview === null
                ? 'Предпросмотр не относится к DXF этой попытки.'
                : null,
            onOverlayChange: setOverlayOn,
            remarks,
          }
        : null,
  };

  return {
    painter,
    capture: markingOn && pageSize ? { camera, page: pageSize, onDrawn: handleDrawn } : null,
    panel,
  };
};
