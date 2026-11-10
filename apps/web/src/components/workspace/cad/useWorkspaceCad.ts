'use client';

import type { SheetRead } from '@quantor/api-client';
import { useEffect, useMemo, useState } from 'react';

import type { ViewportSheet } from '@/components/viewer/DrawingViewport';
import { createCadPainter } from '@/lib/cad/cad-painter';
import { cropToNormalized } from '@/lib/cad/frame';
import { readCadPaintColors } from '@/lib/cad/paint-colors';
import type { BboxPt, IRemarkBinding } from '@/lib/cad/remarks';
import { composePainters, createRemarksPainter } from '@/lib/cad/remarks-painter';
import { useStoredNumber } from '@/lib/cad/useStoredNumber';
import { formatNumber } from '@/lib/cad/view-format';
import {
  DEFAULT_PDF_OPACITY,
  PDF_OPACITY_KEY,
  cadRender,
  clampPdfOpacity,
  resolveCadMode,
  type CadViewMode,
} from '@/lib/cad/view-mode';
import { sheetWorkspaceHref } from '@/lib/cad/sheets';
import { overlayPaintData } from '@/lib/cad/workspace-cad';
import { pageForJob, sheetPosition } from '@/lib/cad/workspace-url';
import { useTheme } from '@/lib/theme';
import type { Camera, Viewport } from '@/lib/viewer/camera';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';
import { useWorkspaceStore } from '@/store/workspace';

import { tabFromQuery } from './left-tab';
import type {
  IWorkspaceCadBarProps,
  IWorkspaceCadLayers,
  IWorkspaceCadLeftProps,
  IWorkspaceCadSideProps,
  WorkspaceCadState,
} from './types';
import { useWorkspaceCadJob } from './useWorkspaceCadJob';
import { useWorkspaceCadRemarks } from './useWorkspaceCadRemarks';

interface IUseWorkspaceCadInput {
  projectId: string;
  revisionId: string | null;
  /** Листы ревизии в порядке рабочей области: позиция листа в адресе - номер с 1. */
  sheets: readonly Pick<SheetRead, 'page_index'>[];
  sheet: Pick<SheetRead, 'id' | 'page_index' | 'page_label'> | null;
  /** Размер листа у отрисовщика (pt при масштабе 1); `null` - ещё не известен. */
  page: ViewportSheet | null;
  camera: Camera;
  viewportSize: () => Viewport;
  /** Флаг `cad.export` включён. Без него ни одного запроса CAD не уходит. */
  enabled: boolean;
  /** Открыта вкладка CAD. */
  active: boolean;
  /** Значения из адреса рабочей области. */
  tabParam: string | null;
  jobParam: string | null;
  viewParam: number | null;
  /** Изменить адрес рабочей области: `null` убирает параметр. */
  navigate: (changes: Record<string, string | null>) => void;
}

export interface IWorkspaceCad {
  /** Вкладка открывалась: её левая панель смонтирована и дальше не размонтируется. */
  opened: boolean;
  /** Слой DXF и рамок замечаний для `<DrawingViewport extraPainter>`. */
  painter: LayerPainter | null;
  /** Непрозрачность подложки PDF для `<DrawingViewport pageOpacity>`. */
  pageOpacity: number;
  /** Данные слоя захвата рамки; `null` - режим отметки выключен. */
  capture: {
    camera: Camera;
    page: { width: number; height: number };
    onDrawn: (bbox: BboxPt) => void;
  } | null;
  /** Левая панель; `null` - ревизия не открыта. */
  left: IWorkspaceCadLeftProps | null;
  /** Строка над холстом; `null` - у листа нет диагностики вида. */
  bar: IWorkspaceCadBarProps | null;
  side: IWorkspaceCadSideProps;
}

const NO_LAYERS: ReadonlySet<number> = new Set<number>();

/**
 * CAD текущего листа в рабочей области: задание и вид листа, DXF на камере рабочей области,
 * замечания, левая и правая панели вкладки. Один хук связывает вкладку и единственный холст.
 *
 * Запросы идут только при включённом `cad.export` и только после первого открытия вкладки: DXF
 * при этом остаётся и на других вкладках (режим в хранилище рабочей области), а рамки замечаний
 * рисуются, пока вкладка открыта. Панорама и зум идут мимо состояния React: камера передаётся
 * холсту как есть (ADR-0004), непрозрачность PDF ставится CSS на стопку страницы.
 */
export const useWorkspaceCad = ({
  projectId,
  revisionId,
  sheets,
  sheet,
  page,
  camera,
  viewportSize,
  enabled,
  active,
  tabParam,
  jobParam,
  viewParam,
  navigate,
}: IUseWorkspaceCadInput): IWorkspaceCad => {
  const theme = useTheme();
  const colors = useMemo(() => {
    void theme;
    return readCadPaintColors();
  }, [theme]);

  const setLeftTab = useWorkspaceStore((state) => state.setLeftTab);
  const [sliderOpacity, setSliderOpacity] = useStoredNumber(PDF_OPACITY_KEY, DEFAULT_PDF_OPACITY);

  // `?tab=cad` открывает вкладку один раз на значение адреса. Вкладку закрывает флаг в странице,
  // поэтому выбор можно сохранить и до прихода меты.
  useEffect(() => {
    const tab = tabFromQuery(tabParam);
    if (tab) setLeftTab(tab);
  }, [tabParam, setLeftTab]);

  // Данные грузятся после первого открытия вкладки и дальше не выключаются: так DXF держится на
  // других вкладках, а тому, кто CAD не открывал, запросы не уходят.
  const [opened, setOpened] = useState(false);
  if (enabled && active && !opened) setOpened(true);

  const pageIndex = sheet?.page_index ?? null;
  const data = useWorkspaceCadJob({
    projectId,
    revisionId,
    load: enabled && opened && revisionId !== null,
    pageIndex,
    jobParam,
    viewParam,
  });
  const { diagnostics, preview, frame, params, availability } = data;

  // DXF накладывается на PDF, только когда его уже можно нарисовать; иначе виден один PDF.
  const geometryReady = availability?.available === true && preview !== null && frame !== null;
  const mode: CadViewMode = resolveCadMode(geometryReady);
  const render = cadRender(mode, sliderOpacity, active);

  const pageSize = useMemo(
    () => (page ? { width: page.width, height: page.height } : null),
    [page],
  );

  // --- слои DXF и область проверки масштаба: выбор принадлежит виду ---
  const scope = params ? `${params.jobId}:${params.pageIndex}:${params.view}` : null;
  const [seenScope, setSeenScope] = useState(scope);
  const [hiddenLayers, setHiddenLayers] = useState<ReadonlySet<number>>(NO_LAYERS);
  const [cropVisible, setCropVisible] = useState(false);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setHiddenLayers(NO_LAYERS);
    setCropVisible(false);
  }

  const layerNames = useMemo(() => preview?.layers ?? [], [preview]);
  const visibleLayers = useMemo<ReadonlySet<number>>(
    () => new Set(layerNames.map((_, index) => index).filter((index) => !hiddenLayers.has(index))),
    [layerNames, hiddenLayers],
  );
  const cropContext = diagnostics?.scale?.context_crop_pt;
  const cropRect = useMemo(
    () => (pageSize ? cropToNormalized(cropContext, pageSize) : null),
    [pageSize, cropContext],
  );
  const cropAvailable = cropRect !== null;
  const cropColor = colors.crop;
  const crop = useMemo(
    () =>
      active && cropRect !== null && cropAvailable && cropVisible
        ? { rect: cropRect, color: cropColor }
        : null,
    [active, cropAvailable, cropVisible, cropRect, cropColor],
  );

  const paintData = useMemo(
    () =>
      overlayPaintData(preview, frame, pageSize, colors.ink, colors.layers, {
        dxfVisible: render.dxfVisible,
        hiddenLayers,
        crop,
      }),
    [preview, frame, pageSize, colors.ink, colors.layers, render.dxfVisible, hiddenLayers, crop],
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
  const remarks = useWorkspaceCadRemarks({ binding, pageSize, camera, viewportSize, active });

  const painter = useMemo<LayerPainter | null>(
    () =>
      composePainters(
        cadPainter,
        remarks.marks.length > 0
          ? createRemarksPainter(
              { marks: remarks.marks, colors: colors.remarks, activeId: remarks.activeId },
              { clear: cadPainter === null },
            )
          : null,
      ),
    [cadPainter, remarks.marks, remarks.activeId, colors.remarks],
  );

  // --- переходы: всё в адрес рабочей области ---
  // Лист вне списка адресуется по индексу страницы (позиция обычно ему равна), а не теряется молча.
  const positionOf = (target: number): number => sheetPosition(sheets, target) ?? target + 1;
  const goToSheet = (target: number, changes: Record<string, string | null>) => {
    navigate({ page: String(positionOf(target)), region: null, ...changes });
  };

  // Задание выбрано (из списка или только что создано): рабочая область встаёт на его лист.
  const openJob = (jobId: string, pages: readonly number[] | null) => {
    const target = pageForJob({ requested_pages: pages ? [...pages] : null }, pageIndex);
    const changes = { job: jobId, view: null };
    if (target !== null && target !== pageIndex) goToSheet(target, changes);
    else navigate(changes);
  };

  const left: IWorkspaceCadLeftProps | null =
    revisionId !== null
      ? {
          projectId,
          revisionId,
          activePage: pageIndex,
          selectedJobId: data.jobId,
          onOpenSheet: (target) => goToSheet(target, { job: null, view: null }),
          onSelectJob: (jobId) =>
            openJob(jobId, data.jobs.find((item) => item.job_id === jobId)?.requested_pages ?? null),
        }
      : null;

  // --- строка над холстом ---
  const notices: { tone: 'note' | 'alert'; text: string }[] = [];
  if (diagnostics && availability?.reason) {
    const frameReason = diagnostics.preview_available ? diagnostics.frame.reason : null;
    notices.push({
      tone: 'note',
      text: frameReason ? `${availability.reason} ${frameReason}` : availability.reason,
    });
  }
  if (preview?.truncated) {
    notices.push({
      tone: 'note',
      text: `Показана упрощённая геометрия (flatten_mm ${formatNumber(preview.flatten_mm, 3)}). Для точных размеров используйте DXF.`,
    });
  }
  if (data.previewError) notices.push({ tone: 'alert', text: data.previewError });

  const bar: IWorkspaceCadBarProps | null =
    active && diagnostics
      ? {
          diagnostics,
          views: data.views,
          view: data.view,
          onViewChange: (next) => navigate({ job: data.jobId, view: String(next) }),
          onFit: () => page && camera.fitPage(page, viewportSize()),
          notices,
          loading: diagnostics.preview_available && preview === null && data.previewPending,
        }
      : null;

  // --- правая панель ---
  let state: WorkspaceCadState;
  if (pageIndex === null || revisionId === null) state = 'no-sheet';
  else if (data.jobsPending) state = 'loading';
  else if (data.jobsError !== null) state = 'error';
  else state = data.jobId === null ? 'none' : 'ready';

  const layers: IWorkspaceCadLayers = {
    layers: layerNames,
    visibleLayers,
    onToggleLayer: (index) =>
      setHiddenLayers((current) => {
        const next = new Set(current);
        if (next.has(index)) next.delete(index);
        else next.add(index);
        return next;
      }),
    onSetLayersHidden: (indices, hidden) =>
      setHiddenLayers((current) => {
        const next = new Set(current);
        indices.forEach((index) => {
          if (hidden) next.add(index);
          else next.delete(index);
        });
        return next;
      }),
    pdfOpacity: sliderOpacity,
    onPdfOpacityChange: (value) => setSliderOpacity(clampPdfOpacity(value)),
    pdfOpacityActive: mode === 'overlay',
    cadShown: mode === 'overlay' && preview !== null,
    previewAvailable: diagnostics?.preview_available === true,
    pointCount: preview ? preview.point_count : null,
    cropAvailable,
    cropVisible,
    onCropChange: setCropVisible,
  };

  const side: IWorkspaceCadSideProps = {
    state,
    sheetLabel: sheet ? (sheet.page_label ?? String(sheet.page_index + 1)) : null,
    loadError: data.jobsError,
    onRetry: data.refetchJobs,
    job:
      state === 'ready' && data.jobId !== null && revisionId !== null
        ? {
            projectId,
            revisionId,
            jobId: data.jobId,
            detail: data.job,
            failed: data.kind === 'failed',
            page: pageIndex,
            view: data.view,
            onSelectView: (target, next) => {
              goToSheet(target, { job: data.jobId, view: String(next) });
            },
          }
        : null,
    convert:
      sheet && revisionId !== null
        ? {
            projectId,
            revisionId,
            sheetId: sheet.id,
            pageIndex: sheet.page_index,
            calibrateHref: sheetWorkspaceHref(projectId, revisionId, positionOf(sheet.page_index) - 1),
            onJobCreated: (jobId, pages) => openJob(jobId, pages),
          }
        : null,
    viewLoading:
      state === 'ready' && data.diagnosticsError === null && (data.job === null || data.diagnosticsPending),
    viewError: state === 'ready' ? data.diagnosticsError : null,
    view: diagnostics ? { diagnostics, layers, remarks: remarks.remarks } : null,
  };

  return {
    opened,
    painter,
    pageOpacity: render.pdfOpacity,
    capture:
      remarks.capturing && pageSize
        ? { camera, page: pageSize, onDrawn: remarks.onDrawn }
        : null,
    left,
    bar,
    side,
  };
};
