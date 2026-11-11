'use client';

import type { CadSheetFloorTitle, SheetRead } from '@quantor/api-client';
import { useEffect, useMemo, useState } from 'react';

import type { ViewportSheet } from '@/components/viewer/DrawingViewport';
import { createCadPainter } from '@/lib/cad/cad-painter';
import { FLOOR3D_MODE_KEY } from '@/lib/cad/floor3d-queries';
import { cropToNormalized, overlayPaths } from '@/lib/cad/frame';
import { readCadPaintColors } from '@/lib/cad/paint-colors';
import { isRouteJob } from '@/lib/cad/mep-jobs';
import { useMepLayerVisibility } from '@/lib/cad/mep-layers';
import { mergeRoutePaint } from '@/lib/cad/mep-routes';
import type { BboxPt, IRemarkBinding } from '@/lib/cad/remarks';
import { composePainters, createRemarksPainter } from '@/lib/cad/remarks-painter';
import { useStoredBoolean } from '@/lib/cad/useStoredBoolean';
import { useStoredNumber } from '@/lib/cad/useStoredNumber';
import { createConstructionsPainter } from '@/lib/cad/constructions-painter';
import { createZonesPainter } from '@/lib/cad/zones-painter';
import { formatNumber } from '@/lib/cad/view-format';
import {
  DEFAULT_PDF_OPACITY,
  PDF_OPACITY_KEY,
  cadRender,
  clampPdfOpacity,
  resolveCadMode,
  type CadViewMode,
} from '@/lib/cad/view-mode';
import { matchingPreview, overlayPaintData, remarkBindingOf } from '@/lib/cad/workspace-cad';
import { pageForJob, sheetPosition } from '@/lib/cad/workspace-url';
import { useTheme } from '@/lib/theme';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import type { Camera, Viewport } from '@/lib/viewer/camera';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';
import { useWorkspaceStore } from '@/store/workspace';

import type { ICadFloor3dLink } from './floor3d/CadFloor3dView';
import { tabFromQuery } from './left-tab';
import { mepLayersOf, mepOf } from './mep-side';
import type {
  IWorkspaceCadBarProps,
  IWorkspaceCadConstructionPicker,
  IWorkspaceCadLayers,
  IWorkspaceCadLeftProps,
  IWorkspaceCadSideProps,
  WorkspaceCadState,
} from './types';
import { layerVisibilityKey, useCadLayerVisibility } from './useCadLayerVisibility';
import { useWorkspaceCadConstructions } from './useWorkspaceCadConstructions';
import { useWorkspaceCadJob } from './useWorkspaceCadJob';
import { useWorkspaceCadRemarks } from './useWorkspaceCadRemarks';
import { useWorkspaceCadRoutes } from './useWorkspaceCadRoutes';
import { useWorkspaceCadZones, type IWorkspaceCadZonesState } from './useWorkspaceCadZones';

interface IUseWorkspaceCadInput {
  projectId: string;
  revisionId: string | null;
  /** Листы ревизии в порядке рабочей области: позиция листа в адресе - номер с 1. */
  sheets: readonly Pick<SheetRead, 'page_index'>[];
  sheet: Pick<SheetRead, 'id' | 'page_index' | 'page_label'> | null;
  /** Заголовок плана открытого листа из конвейера CAD; нет - лист подписан номером. */
  floorTitle?: CadSheetFloorTitle | null;
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
  /** Данные слоя рисования зоны; `null` - режим рисования выключен. */
  zoneCapture: IWorkspaceCadZonesState['capture'];
  /** Правка контура и разрез зоны; `null` - режим выключен. */
  zoneEdit: IWorkspaceCadZonesState['edit'];
  zoneSplit: IWorkspaceCadZonesState['split'];
  /** Выбор конструкции щелчком и её карточка; `null` - выбор выключен. */
  constructionPicker: IWorkspaceCadConstructionPicker | null;
  /** Вид «3D» открыт поверх холста (ADR-0039): параметры листа и вида; `null` - режим «План». */
  floor3d: { readonly params: ICadViewParams; readonly link: ICadFloor3dLink } | null;
  /** Режим «3D» включён, но лист или вид ещё грузится: оверлей держится, план не мелькает. */
  floor3dPending: { readonly onExit: () => void } | null;
}

/**
 * CAD текущего листа в рабочей области: задание и вид листа, DXF на камере рабочей области,
 * замечания, левая и правая панели вкладки. Один хук связывает вкладку и единственный холст.
 *
 * Задания, вид и предпросмотр DXF читаются при включённом `cad.export` сразу, в том числе в режиме
 * «Листы»; зоны и конструкции - только после первого открытия CAD. DXF остаётся и на других
 * вкладках (режим в хранилище рабочей области), а рамки замечаний рисуются, пока CAD открыт. Панорама и зум идут мимо состояния React: камера передаётся
 * холсту как есть (ADR-0004), непрозрачность PDF ставится CSS на стопку страницы.
 */
export const useWorkspaceCad = ({
  projectId,
  revisionId,
  sheets,
  sheet,
  floorTitle = null,
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
  const [view3d, setView3d] = useStoredBoolean(FLOOR3D_MODE_KEY, false);

  // `?tab=cad` открывает вкладку один раз на значение адреса. Вкладку закрывает флаг в странице,
  // поэтому выбор можно сохранить и до прихода меты.
  useEffect(() => {
    const tab = tabFromQuery(tabParam);
    if (tab) setLeftTab(tab);
  }, [tabParam, setLeftTab]);

  // Зоны и конструкции грузятся после первого открытия CAD и дальше не выключаются.
  const [opened, setOpened] = useState(false);
  if (enabled && active && !opened) setOpened(true);

  // Задания, вид и предпросмотр DXF читаются сразу при включённом `cad.export`: наложение видно и в
  // режиме «Листы», не дожидаясь захода в CAD. Остальное (зоны, конструкции) - после открытия.
  const loadOverlay = enabled && revisionId !== null;
  const pageIndex = sheet?.page_index ?? null;
  const data = useWorkspaceCadJob({
    projectId,
    revisionId,
    load: loadOverlay,
    pageIndex,
    jobParam,
    viewParam,
  });
  const { diagnostics, preview, frame, params, availability } = data;

  // Трассы механики: выбранное (явно или автоматически) route-задание рисуется поверх DXF вида его родителя.
  const routes = useWorkspaceCadRoutes({
    projectId,
    revisionId,
    load: loadOverlay,
    pageIndex,
    route: data.routeSummary ?? data.autoRoute,
  });
  const mepVisibility = useMepLayerVisibility();
  const routePreview = useMemo(
    () =>
      routes.diagnostics ? matchingPreview(routes.diagnostics, routes.preview ?? undefined) : null,
    [routes.diagnostics, routes.preview],
  );

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
  const [cropVisible, setCropVisible] = useState(false);
  if (seenScope !== scope) {
    setSeenScope(scope);
    setCropVisible(false);
  }

  // Слои - один источник правды для плана и 3D: по именам, не сбрасываются при смене режима и вида.
  const layerNames = useMemo(() => preview?.layers ?? [], [preview]);
  const visibility = useCadLayerVisibility(
    params ? layerVisibilityKey(params.jobId, params.pageIndex) : null,
    layerNames,
  );
  const { hiddenLayers } = visibility;
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

  // Нормализация путей - дорогая часть, а зависит только от превью, кадра и листа: переключение
  // слоя или маски трасс её не повторяет и не сбрасывает кеш путей рисовальщика.
  const dxfPaths = useMemo(
    () => (preview && frame && pageSize ? overlayPaths(preview.paths, frame, pageSize) : undefined),
    [preview, frame, pageSize],
  );
  const routePaths = useMemo(
    () =>
      routePreview && frame && pageSize
        ? overlayPaths(routePreview.paths, frame, pageSize)
        : undefined,
    [routePreview, frame, pageSize],
  );

  // --- замечания ---
  // Замечания принадлежат показанному заданию: вид родителя или, когда выбраны трассы, их задание.
  const routeSelected = data.routeSummary !== null;
  const binding = useMemo<IRemarkBinding | null>(
    () =>
      routeSelected
        ? remarkBindingOf(routes.params, routes.diagnostics)
        : remarkBindingOf(params, diagnostics),
    [routeSelected, routes.params, routes.diagnostics, params, diagnostics],
  );
  const remarks = useWorkspaceCadRemarks({ binding, pageSize, camera, viewportSize, active });

  // Открытые замечания показанного вида; пока список не прочитан - `null`, и решения заблокированы.
  const remarkStore = remarks.remarks?.store ?? null;
  const openRemarks =
    remarkStore !== null && !remarkStore.loading && remarkStore.loadError === null
      ? remarkStore.remarks.filter((item) => item.status === 'open').length
      : null;

  // --- зоны листа: помещения и двери ---
  const zonesState = useWorkspaceCadZones({
    projectId,
    revisionId,
    pageIndex,
    pageSize,
    camera,
    preview,
    frame,
    load: enabled && opened && revisionId !== null,
    active,
    remarksCapturing: remarks.capturing,
  });

  // --- конструкции листа: кладка и монолит с величинами (ADR-0038) ---
  const constructionsState = useWorkspaceCadConstructions({
    params,
    frame,
    pageSize,
    camera,
    load: enabled && opened && revisionId !== null,
    active,
    blocked:
      remarks.capturing ||
      zonesState.capture !== null ||
      zonesState.edit !== null ||
      zonesState.split !== null,
    hiddenCategories: visibility.hiddenCategories,
  });
  // Выбрана конструкция - подложка DXF приглушается, чтобы чужие линии не читались как выделение.
  const dimmed = constructionsState.selection.selectedIds.size > 0;

  const paintData = useMemo(() => {
    const base = overlayPaintData(preview, frame, pageSize, colors.ink, colors.layers, {
      dxfVisible: render.dxfVisible,
      hiddenLayers,
      crop,
      paths: dxfPaths,
      dimmed,
    });
    const route =
      render.dxfVisible && routePreview
        ? {
            preview: routePreview,
            colors: colors.mep,
            hiddenMask: mepVisibility.mask,
            paths: routePaths,
          }
        : null;
    return mergeRoutePaint(base, layerNames.length, route, frame, pageSize, colors.ink);
  }, [
    preview,
    frame,
    pageSize,
    colors.ink,
    colors.layers,
    colors.mep,
    render.dxfVisible,
    hiddenLayers,
    dimmed,
    crop,
    routePreview,
    mepVisibility.mask,
    layerNames,
    dxfPaths,
    routePaths,
  ]);
  const cadPainter = useMemo(() => (paintData ? createCadPainter(paintData) : null), [paintData]);
  const constructionsPainter = useMemo(
    () =>
      constructionsState.paintData
        ? createConstructionsPainter(constructionsState.paintData, { clear: cadPainter === null })
        : null,
    [constructionsState.paintData, cadPainter],
  );

  const zonesPainter = useMemo(
    () =>
      zonesState.paintData
        ? createZonesPainter(zonesState.paintData, {
            clear: cadPainter === null && constructionsPainter === null,
          })
        : null,
    [zonesState.paintData, cadPainter, constructionsPainter],
  );

  const painter = useMemo<LayerPainter | null>(
    () =>
      composePainters(
        cadPainter,
        constructionsPainter,
        zonesPainter,
        remarks.marks.length > 0
          ? createRemarksPainter(
              { marks: remarks.marks, colors: colors.remarks, activeId: remarks.activeId },
              {
                clear:
                  cadPainter === null && constructionsPainter === null && zonesPainter === null,
              },
            )
          : null,
      ),
    [
      cadPainter,
      constructionsPainter,
      zonesPainter,
      remarks.marks,
      remarks.activeId,
      colors.remarks,
    ],
  );

  // --- переходы: всё в адрес рабочей области ---
  // Лист вне списка адресуется по индексу страницы (позиция обычно ему равна), а не теряется молча.
  const positionOf = (target: number): number => sheetPosition(sheets, target) ?? target + 1;
  const goToSheet = (target: number, changes: Record<string, string | null>) => {
    navigate({ page: String(positionOf(target)), region: null, ...changes });
  };

  // Задание выбрано (из списка или только что создано): рабочая область встаёт на его лист.
  const openJob = (
    jobId: string,
    pages: readonly number[] | null,
    jobView: number | null = null,
  ) => {
    const target = pageForJob({ requested_pages: pages ? [...pages] : null }, pageIndex);
    const changes = { job: jobId, view: jobView !== null ? String(jobView) : null };
    if (target !== null && target !== pageIndex) goToSheet(target, changes);
    else navigate(changes);
  };

  const left: IWorkspaceCadLeftProps | null =
    revisionId !== null
      ? {
          projectId,
          revisionId,
          activePage: pageIndex,
          selectedJobId: data.routeSummary?.job_id ?? data.jobId,
          onOpenSheet: (target) => goToSheet(target, { job: null, view: null }),
          onSelectJob: (jobId) => {
            const item = data.jobs.find((entry) => entry.job_id === jobId);
            // Трассы открываются на своём виде: вид задан самим заданием.
            openJob(
              jobId,
              item?.requested_pages ?? null,
              item && isRouteJob(item) ? item.view : null,
            );
          },
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
          floor3d: {
            mode: view3d ? '3d' : 'plan',
            onModeChange: (next) => setView3d(next === '3d'),
          },
        }
      : null;

  // --- правая панель ---
  let state: WorkspaceCadState;
  if (pageIndex === null || revisionId === null) state = 'no-sheet';
  else if (data.jobsPending) state = 'loading';
  else if (data.jobsError !== null) state = 'error';
  else state = data.jobId === null ? 'none' : 'ready';

  const layers: IWorkspaceCadLayers = {
    mep: mepLayersOf(
      render.dxfVisible && routePreview ? routePreview.layers : null,
      mepVisibility.mask,
      mepVisibility.setHidden,
    ),
    layers: layerNames,
    visibleLayers,
    onToggleLayer: visibility.toggleLayer,
    onSetLayersHidden: visibility.setLayersHidden,
    mode3d: view3d,
    categories: visibility.categories,
    pdfOpacity: sliderOpacity,
    onPdfOpacityChange: (value) => setSliderOpacity(clampPdfOpacity(value)),
    pdfOpacityActive: mode === 'overlay',
    cadShown: mode === 'overlay' && preview !== null,
    previewAvailable: diagnostics?.preview_available === true,
    pointCount: preview ? preview.point_count : null,
    cropAvailable,
    cropVisible,
    onCropChange: setCropVisible,
    constructions: constructionsState.layers,
    zones: zonesState.layers,
  };

  const side: IWorkspaceCadSideProps = {
    state,
    sheetLabel: sheet ? (sheet.page_label ?? String(sheet.page_index + 1)) : null,
    floorTitle,
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
            onCalibrate: () => useWorkspaceStore.getState().setTool('scale'),
            onJobCreated: (jobId, pages) => openJob(jobId, pages),
          }
        : null,
    viewLoading:
      state === 'ready' &&
      data.diagnosticsError === null &&
      (data.job === null || data.diagnosticsPending),
    viewError: state === 'ready' ? data.diagnosticsError : null,
    view: diagnostics
      ? {
          diagnostics,
          layers,
          mep: mepOf({
            parent: params,
            diagnostics,
            routeSummary: data.routeSummary,
            routes,
            openRemarks,
            view: data.view,
            navigate,
            parentJobId: data.jobId,
          }),
          remarks: remarks.remarks,
        }
      : null,
    zones: zonesState.zones,
    constructions: constructionsState.side,
    finishes: {
      projectId,
      revisionId,
      pageIndex,
      load: enabled && opened && revisionId !== null,
    },
  };

  const link = { ...constructionsState.selection, hiddenCategories: visibility.hiddenCategories };
  const floor3d = bar !== null && view3d && params !== null ? { params, link } : null;

  return {
    opened,
    painter,
    pageOpacity: render.pdfOpacity,
    capture:
      remarks.capturing && pageSize ? { camera, page: pageSize, onDrawn: remarks.onDrawn } : null,
    left,
    bar,
    side,
    zoneCapture: zonesState.capture,
    zoneEdit: zonesState.edit,
    zoneSplit: zonesState.split,
    constructionPicker: constructionsState.picker,
    floor3d,
    floor3dPending:
      active && view3d && floor3d === null && (state === 'loading' || state === 'ready')
        ? { onExit: () => setView3d(false) }
        : null,
  };
};
