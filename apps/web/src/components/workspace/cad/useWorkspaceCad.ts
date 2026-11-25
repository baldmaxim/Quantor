'use client';

import type { CadSheetFloorTitle, SheetRead } from '@quantor/api-client';
import { useEffect, useMemo, useState } from 'react';

import type { ICadTenderPicker } from '@/components/cad/tender/CadTenderPicker';
import type { ViewportSheet } from '@/components/viewer/DrawingViewport';
import { createCadPainter } from '@/lib/cad/cad-painter';
import { cadCodeText } from '@/lib/cad/errors';
import { useCadEomPreview, withEomPreview } from '@/lib/cad/eom-queries';
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
import { createFacadesPainter } from '@/lib/cad/facades-painter';
import { createSectionsPainter } from '@/lib/cad/sections-painter';
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
import { useMepEngineEnabled } from '@/lib/tender/layers';
import { useTheme } from '@/lib/theme';
import { hiddenConstructionIdsOf, paintHiddenLayerIndices } from '@/lib/cad/layer-categories';
import { layerCountsOf } from '@/lib/cad/layer-counts';
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
import {
  layerVisibilityKey,
  legacyLayerVisibilityKey,
  useCadLayerVisibility,
} from './useCadLayerVisibility';
import { useWorkspaceCadConstructions } from './useWorkspaceCadConstructions';
import { useWorkspaceCadJob } from './useWorkspaceCadJob';
import { useWorkspaceCadRemarks } from './useWorkspaceCadRemarks';
import { useWorkspaceCadRoutes } from './useWorkspaceCadRoutes';
import { useWorkspaceCadFacades } from './useWorkspaceCadFacades';
import { useWorkspaceCadStyle, type IStyleCaptureData } from './useWorkspaceCadStyle';
import { useWorkspaceCadSections } from './useWorkspaceCadSections';
import { useWorkspaceCadTender } from './useWorkspaceCadTender';
import { useWorkspaceCadZones, type IWorkspaceCadZonesState } from './useWorkspaceCadZones';

interface IUseWorkspaceCadInput {
  projectId: string;
  revisionId: string | null;
  /** Документ (том) открытой ревизии: профиль оформления принадлежит ему; нет - раздела нет. */
  documentId?: string | null;
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
  /** Расчёт TENDER из адреса («Открыть на листе»): его слой включается при открытии вида. */
  tenderParam?: string | null;
  /** Режим из адреса: `3d` открывает 3D этажа, `plan` - план; приоритетнее сохранённого выбора. */
  modeParam?: string | null;
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
  /** Данные слоя образцов профиля оформления; `null` - режим выключен. */
  styleCapture: IStyleCaptureData | null;
  /** Правка контура и разрез зоны; `null` - режим выключен. */
  zoneEdit: IWorkspaceCadZonesState['edit'];
  zoneSplit: IWorkspaceCadZonesState['split'];
  /** Выбор конструкции щелчком и её карточка; `null` - выбор выключен. */
  constructionPicker: IWorkspaceCadConstructionPicker | null;
  /** Вид «3D» открыт поверх холста (ADR-0039): параметры листа и вида; `null` - режим «План». */
  floor3d: { readonly params: ICadViewParams; readonly link: ICadFloor3dLink } | null;
  /** Выбор объекта расчёта TENDER щелчком по плану и его плашка; `null` - слоя на виде нет. */
  tenderPicker: ICadTenderPicker | null;
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
  documentId = null,
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
  tenderParam = null,
  modeParam = null,
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

  // `?mode=3d|plan` (ссылка со страницы «Расчёты») приоритетнее сохранённого выбора; один раз на значение адреса.
  useEffect(() => {
    if (modeParam === '3d' || modeParam === 'plan') setView3d(modeParam === '3d');
  }, [modeParam, setView3d]);

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

  // Трассы механики: выбранное (явно или автоматически) route-задание рисуется поверх DXF вида его
  // родителя. Это же задание - источник итогов и 3D этажа: одни трассы во всех видах.
  const shownRoute = data.routeSummary ?? data.autoRoute;
  // Трассы ВИС движка закрыты флагом `cad.mep_engine` (ADR-0051): выключен - ни запросов, ни слоёв.
  const mepEngine = useMepEngineEnabled();
  const routes = useWorkspaceCadRoutes({
    projectId,
    revisionId,
    load: loadOverlay && mepEngine,
    pageIndex,
    route: shownRoute,
  });
  const mepVisibility = useMepLayerVisibility();
  // ЭОМ и СС листа (cad_eom): рисуются поверх DXF теми же слоями и маской, что трассы механики.
  const eomPreview = useCadEomPreview(
    {
      projectId,
      revisionId: revisionId ?? '',
      pageIndex: pageIndex ?? 0,
      view: params?.view ?? 0,
    },
    loadOverlay && mepEngine && revisionId !== null && pageIndex !== null && params !== null,
  );
  const routePreview = useMemo(
    () =>
      mepEngine
        ? withEomPreview(
            routes.diagnostics
              ? matchingPreview(routes.diagnostics, routes.preview ?? undefined)
              : null,
            eomPreview,
          )
        : null,
    [mepEngine, routes.diagnostics, routes.preview, eomPreview],
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
    params && revisionId !== null ? layerVisibilityKey(revisionId, params.pageIndex) : null,
    layerNames,
    params ? legacyLayerVisibilityKey(params.jobId, params.pageIndex) : null,
  );
  const { hiddenLayers } = visibility;
  // Расчёты TENDER (ADR-0051): слой поверх DXF, видимость - в том же хранилище, что слои листа.
  const tender = useWorkspaceCadTender({
    projectId,
    revisionId,
    pageIndex,
    view: params?.view ?? null,
    frame,
    pageSize,
    camera,
    visibility,
    shown: render.dxfVisible,
    tenderParam,
  });
  const visibleLayers = useMemo<ReadonlySet<number>>(
    () => new Set(layerNames.map((_, index) => index).filter((index) => !hiddenLayers.has(index))),
    [layerNames, hiddenLayers],
  );
  // В плане не рисуются ещё и служебные слои, а `02_МОНОЛИТ` - когда включена не обе монолитные строки.
  const paintHiddenLayers = useMemo(
    () => paintHiddenLayerIndices(layerNames, hiddenLayers, visibility.hiddenCategories),
    [layerNames, hiddenLayers, visibility.hiddenCategories],
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
  // Конструкции всегда относятся к виду листа, даже когда выбраны трассы.
  const wallsBinding = useMemo(() => remarkBindingOf(params, diagnostics), [params, diagnostics]);
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

  // --- профиль оформления тома по образцам (ADR-0049): щелчки по листу, предпросмотр, принятие ---
  const styleState = useWorkspaceCadStyle({
    projectId,
    documentId,
    revisionId,
    pageIndex,
    pageSize,
    camera,
    load: enabled && opened && revisionId !== null,
    active,
    blocked:
      remarks.capturing ||
      zonesState.capture !== null ||
      zonesState.edit !== null ||
      zonesState.split !== null,
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
      zonesState.split !== null ||
      styleState.capture !== null,
    hiddenCategories: visibility.hiddenCategories,
    hiddenLayerNames: visibility.hiddenLayerNames,
    remarkBinding: wallsBinding,
  });
  // Выбрана конструкция - подложка DXF приглушается, чтобы чужие линии не читались как выделение.
  const dimmed = constructionsState.selection.selectedIds.size > 0;

  // --- переходы: всё в адрес рабочей области ---
  // Лист вне списка адресуется по индексу страницы (позиция обычно ему равна), а не теряется молча.
  const positionOf = (target: number): number => sheetPosition(sheets, target) ?? target + 1;
  const goToSheet = (target: number, changes: Record<string, string | null>) => {
    navigate({ page: String(positionOf(target)), region: null, ...changes });
  };

  // --- разрезы АР: уровни, решения человека, разметка на листе ---
  const sectionsState = useWorkspaceCadSections({
    projectId,
    revisionId,
    pageIndex,
    load: enabled && opened && revisionId !== null,
    active,
    onOpenPage: (target) => goToSheet(target, { job: null, view: null }),
    camera,
    page,
    viewportSize,
  });

  // --- фасады ревизии (ADR-0048): виды, окна, решения человека, разметка на листе ---
  const facadesState = useWorkspaceCadFacades({
    projectId,
    revisionId,
    pageIndex,
    load: enabled && opened && revisionId !== null,
    active,
    onOpenPage: (target) => goToSheet(target, { job: null, view: null }),
  });

  const paintData = useMemo(() => {
    const base = overlayPaintData(preview, frame, pageSize, colors.ink, colors.layers, {
      dxfVisible: render.dxfVisible,
      hiddenLayers: paintHiddenLayers,
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
    paintHiddenLayers,
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

  const sectionsPainter = useMemo(
    () =>
      sectionsState.paintData
        ? createSectionsPainter(sectionsState.paintData, {
            clear:
              cadPainter === null &&
              constructionsPainter === null &&
              zonesPainter === null &&
              remarks.marks.length === 0,
          })
        : null,
    [sectionsState.paintData, cadPainter, constructionsPainter, zonesPainter, remarks.marks.length],
  );

  const facadesPainter = useMemo(
    () =>
      facadesState.paintData
        ? createFacadesPainter(facadesState.paintData, {
            clear:
              cadPainter === null &&
              constructionsPainter === null &&
              zonesPainter === null &&
              remarks.marks.length === 0 &&
              sectionsPainter === null,
          })
        : null,
    [
      facadesState.paintData,
      cadPainter,
      constructionsPainter,
      zonesPainter,
      sectionsPainter,
      remarks.marks.length,
    ],
  );

  const tenderPainter = useMemo(
    () =>
      tender.painter(
        cadPainter === null &&
          constructionsPainter === null &&
          zonesPainter === null &&
          remarks.marks.length === 0 &&
          sectionsPainter === null &&
          facadesPainter === null,
      ),
    [
      tender,
      cadPainter,
      constructionsPainter,
      zonesPainter,
      sectionsPainter,
      facadesPainter,
      remarks.marks.length,
    ],
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
        sectionsPainter,
        facadesPainter,
        tenderPainter,
      ),
    [
      cadPainter,
      constructionsPainter,
      zonesPainter,
      sectionsPainter,
      facadesPainter,
      tenderPainter,
      remarks.marks,
      remarks.activeId,
      colors.remarks,
    ],
  );

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
  // Разрез даёт только отметки и высоты этажей: контуры разреза - не план, 3D по нему не строится
  // (ADR-0050). Сервер отказывает в 3D такого листа тем же правилом.
  const sectionSheet = sectionsState.side?.isSectionPage ?? false;
  if (sectionSheet) {
    notices.push({
      tone: 'note',
      text: 'Лист — разрез: 3D не строится. Разрез даёт отметки и высоты этажей — вкладка «Разрезы».',
    });
  }

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
          floor3d: sectionSheet
            ? null
            : {
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

  const constructionsData = constructionsState.side?.data ?? null;
  const layerCounts = useMemo(() => layerCountsOf(constructionsData), [constructionsData]);
  const layers: IWorkspaceCadLayers = {
    mep: mepLayersOf(
      // 3D рисует трассы по той же маске: слои трасс переключаются и в 3D, даже при режиме «PDF».
      mepEngine && (render.dxfVisible || view3d) && routePreview ? routePreview.layers : null,
      mepVisibility.mask,
      mepVisibility.setHidden,
      routePreview,
    ),
    layers: layerNames,
    visibleLayers,
    onToggleLayer: visibility.toggleLayer,
    onSetLayersHidden: visibility.setLayersHidden,
    mode3d: view3d,
    categories: visibility.categories,
    counts: layerCounts,
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
    sections: sectionsState.layers,
    tender: tender.layers,
  };

  const side: IWorkspaceCadSideProps = {
    state,
    sheetLabel: sheet ? (sheet.page_label ?? String(sheet.page_index + 1)) : null,
    floorTitle,
    loadError: data.jobsError,
    onRetry: data.refetchJobs,
    update:
      data.updateJob !== null
        ? {
            status: data.updateJob.status,
            shownAt: data.shownJob?.created_at ?? null,
            errorText:
              data.updateJob.error_code !== null ? cadCodeText(data.updateJob.error_code) : null,
          }
        : null,
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
            sections: sectionsState.side,
            engineRoutes: mepEngine,
          }),
          remarks: remarks.remarks,
        }
      : null,
    zones: zonesState.zones,
    constructions: constructionsState.side,
    sections: sectionsState.side,
    facades: enabled ? facadesState.side : null,
    style: enabled ? styleState.side : null,
    finishes: {
      projectId,
      revisionId,
      pageIndex,
      load: enabled && opened && revisionId !== null,
    },
  };

  const constructionList = constructionsState.side?.data?.constructions;
  const hiddenConstructionIds = useMemo(
    () =>
      hiddenConstructionIdsOf(
        constructionList ?? [],
        visibility.hiddenCategories,
        visibility.hiddenLayerNames,
      ),
    [constructionList, visibility.hiddenCategories, visibility.hiddenLayerNames],
  );
  const link: ICadFloor3dLink = {
    ...constructionsState.selection,
    hiddenCategories: visibility.hiddenCategories,
    hiddenConstructionIds,
    hiddenLayerNames: visibility.hiddenLayerNames,
    routeJobId: shownRoute?.job_id ?? null,
  };
  const floor3d =
    bar !== null && view3d && !sectionSheet && params !== null ? { params, link } : null;

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
    styleCapture: enabled ? styleState.capture : null,
    zoneEdit: zonesState.edit,
    zoneSplit: zonesState.split,
    constructionPicker: constructionsState.picker,
    tenderPicker: tender.picker,
    floor3d,
    floor3dPending:
      active &&
      view3d &&
      !sectionSheet &&
      floor3d === null &&
      (state === 'loading' || state === 'ready')
        ? { onExit: () => setView3d(false) }
        : null,
  };
};
