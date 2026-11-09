'use client';

import type { CadViewDiagnosticsRead } from '@quantor/api-client';
import { useCallback, useMemo, useRef, useState, type FC } from 'react';

import { ErrorState, Skeleton, type ISegmentedOption } from '@/components/ui';
import { DrawingViewport } from '@/components/viewer/DrawingViewport';
import { createCadPainter } from '@/lib/cad/cad-painter';
import { bboxPtToNormalized, type BboxPt, type IRemarkBinding } from '@/lib/cad/remarks';
import {
  composePainters,
  createRemarksPainter,
  type IRemarkColors,
  type IRemarkMark,
} from '@/lib/cad/remarks-painter';
import {
  cropToNormalized,
  frameOf,
  overlayPaths,
  standaloneSheet,
  type INormalizedPath,
} from '@/lib/cad/frame';
import { cadViewErrorText, useCadPreview, type ICadViewParams } from '@/lib/cad/view-queries';
import { formatInt, formatNumber } from '@/lib/cad/view-format';
import { errorMessage } from '@/lib/errors';
import { useTheme } from '@/lib/theme';
import { Camera, type CameraState } from '@/lib/viewer/camera';
import type { RenderBackend } from '@/lib/viewer/backend';
import type { LayerPainter } from '@/lib/viewer/viewport-layer';
import type { OverlayRegion } from '@/lib/viewer/overlay';

import { CadRemarkCapture } from './CadRemarkCapture';
import { CadRemarksPanel } from './CadRemarksPanel';
import { CadViewerControls, type CadViewerMode } from './CadViewerControls';
import { useCadPdfPage } from './useCadPdfPage';
import { useCadRemarks, type IRemarkDraft } from './useCadRemarks';
import { usePinchZoom } from './usePinchZoom';

interface ICadViewerPaneProps {
  params: ICadViewParams;
  diagnostics: CadViewDiagnosticsRead;
}

// Общие пустые значения: новый объект на каждый рендер пересоздавал бы слои холста.
const NO_REGIONS: readonly OverlayRegion[] = [];
const NO_HIDDEN: ReadonlySet<string> = new Set<string>();
const NO_LAYERS: ReadonlySet<number> = new Set<number>();
const noop = (): void => undefined;

const DEFAULT_OPACITY = 0.85;
/** Идентификатор несохранённого участка на листе. */
const DRAFT_ID = '__draft__';

/** Цвета слоя - из токенов темы: лист чертежа светлый в обеих темах, чернила не зависят от неё. */
const readColors = () => {
  if (typeof window === 'undefined') {
    return {
      ink: 'CanvasText',
      paper: 'Canvas',
      crop: 'CanvasText',
      remarks: { open: 'CanvasText', resolved: 'CanvasText', onOpen: 'Canvas', paper: 'Canvas' },
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    ink: token('--sheet-ink', 'CanvasText'),
    paper: token('--canvas', 'Canvas'),
    crop: token('--region-stamp', 'CanvasText'),
    // Отметки лежат на светлом листе в обеих темах, поэтому берутся токены чернил листа, а не
    // тематические --danger/--success: те в тёмной теме светлеют и на бумаге не видны.
    // Проверенное отличается от открытого ещё и пунктиром с галочкой.
    remarks: {
      open: token('--sheet-ink-danger', 'CanvasText'),
      resolved: token('--region-image', 'CanvasText'),
      onOpen: token('--region-tag-text', 'Canvas'),
      paper: token('--canvas', 'Canvas'),
    } satisfies IRemarkColors,
  };
};

const NOTICE =
  'rounded-[var(--radius-sm)] border border-warning-soft bg-warning-soft px-[var(--s-5)] py-[var(--s-3)] text-xs [overflow-wrap:anywhere]';

/**
 * PDF страницы и CAD-геометрия вида.
 *
 * Наложение допускается только при подтверждённом кадре координат; без него CAD показывается
 * отдельно, а сравнивать его с PDF интерфейс не даёт. Панорама и зум - через камеру просмотрщика,
 * мимо состояния React (ADR-0004).
 */
export const CadViewerPane: FC<ICadViewerPaneProps> = ({ params, diagnostics }) => {
  const { revisionId, pageIndex } = params;
  const theme = useTheme();
  const colors = useMemo(() => {
    void theme;
    return readColors();
  }, [theme]);

  const [pdfCamera] = useState(() => new Camera());
  const [cadCamera] = useState(() => new Camera());
  const hostRef = useRef<HTMLDivElement>(null);

  const [picked, setPicked] = useState<CadViewerMode | null>(null);
  const [hiddenLayers, setHiddenLayers] = useState<ReadonlySet<number>>(NO_LAYERS);
  const [opacity, setOpacity] = useState(DEFAULT_OPACITY);
  const [cropVisible, setCropVisible] = useState(false);
  // Отказ отрисовки привязан к отрисовщику и странице, на которых случился: после переключения
  // режима или нового открытия документа он не показывается, а успешная отрисовка его снимает.
  const [renderFailure, setRenderFailure] = useState<{
    readonly code: string;
    readonly backend: RenderBackend | null;
    readonly pageIndex: number | null;
  } | null>(null);
  const [marking, setMarking] = useState(false);
  const [draft, setDraft] = useState<BboxPt | null>(null);
  const [activeRemark, setActiveRemark] = useState<string | null>(null);

  const previewQuery = useCadPreview(params, diagnostics.preview_available);
  // Предпросмотр обязан описывать тот же DXF, что назван в диагностике.
  const preview =
    previewQuery.data && previewQuery.data.dxf_sha256 === diagnostics.dxf?.sha256
      ? previewQuery.data
      : null;
  const previewMismatch = previewQuery.data !== undefined && preview === null;
  const frame = useMemo(
    () => (preview && diagnostics.frame.confirmed ? frameOf(preview.frame) : null),
    [preview, diagnostics.frame.confirmed],
  );

  const cadEnabled = diagnostics.preview_available;
  const overlayEnabled =
    cadEnabled && diagnostics.frame.confirmed && (preview === null || frame !== null);
  const defaultMode: CadViewerMode = overlayEnabled ? 'overlay' : cadEnabled ? 'cad' : 'pdf';
  const allowed = (mode: CadViewerMode): boolean =>
    mode === 'pdf' || (mode === 'cad' ? cadEnabled : overlayEnabled);
  const mode: CadViewerMode = picked !== null && allowed(picked) ? picked : defaultMode;

  const binding = useMemo<IRemarkBinding>(
    () => ({
      projectId: params.projectId,
      revisionId,
      jobId: params.jobId,
      attempt: params.attempt,
      pageIndex,
      legacyPdfPage: diagnostics.legacy_pdf_page,
      view: params.view,
      dxfSha256: diagnostics.dxf?.sha256 ?? null,
    }),
    [params, revisionId, pageIndex, diagnostics.legacy_pdf_page, diagnostics.dxf?.sha256],
  );
  const store = useCadRemarks(binding);

  const pdf = useCadPdfPage(revisionId, pageIndex);
  const standalone = useMemo(
    () => (mode === 'cad' && preview ? standaloneSheet(preview.paths, preview.bbox) : null),
    [mode, preview],
  );
  const standaloneView = useMemo(
    () =>
      standalone ? { pageIndex: 0, width: standalone.width, height: standalone.height } : null,
    [standalone],
  );

  const overlay = useMemo<INormalizedPath[] | null>(
    () =>
      mode === 'overlay' && preview && frame && pdf.sheet
        ? overlayPaths(preview.paths, frame, pdf.sheet)
        : null,
    [mode, preview, frame, pdf.sheet],
  );

  const cropRect = useMemo(
    () =>
      mode !== 'cad' && pdf.sheet
        ? cropToNormalized(diagnostics.scale?.context_crop_pt, pdf.sheet)
        : null,
    [mode, pdf.sheet, diagnostics.scale?.context_crop_pt],
  );
  const cropAvailable = (diagnostics.scale?.context_crop_pt?.length ?? 0) === 4 && mode !== 'cad';

  const layerNames = useMemo(() => preview?.layers ?? [], [preview]);
  const visibleLayers = useMemo<ReadonlySet<number>>(
    () => new Set(layerNames.map((_, index) => index).filter((index) => !hiddenLayers.has(index))),
    [layerNames, hiddenLayers],
  );

  const cadPainter = useMemo<LayerPainter | null>(() => {
    const crop = cropVisible && cropRect ? { rect: cropRect, color: colors.crop } : null;
    const paths = mode === 'cad' ? (standalone?.paths ?? null) : overlay;
    if (!paths && !crop) return null;
    return createCadPainter({
      paths: paths ?? [],
      visibleLayers,
      opacity,
      ink: colors.ink,
      paper: mode === 'cad' ? colors.paper : null,
      crop,
    });
  }, [mode, standalone, overlay, cropVisible, cropRect, visibleLayers, opacity, colors]);

  // Замечания и черновик участка - на листе PDF (режимы PDF и наложение), в чистом CAD их нет.
  const sheet = pdf.sheet;
  const marks = useMemo<IRemarkMark[]>(() => {
    if (mode === 'cad' || !sheet) return [];
    const list: IRemarkMark[] = store.remarks.map((remark, index) => ({
      id: remark.id,
      number: index + 1,
      status: remark.status,
      rect: bboxPtToNormalized(remark.bbox_pt, sheet),
    }));
    if (draft) {
      list.push({
        id: DRAFT_ID,
        number: store.remarks.length + 1,
        status: 'open',
        rect: bboxPtToNormalized(draft, sheet),
      });
    }
    return list;
  }, [mode, sheet, store.remarks, draft]);

  const painter = useMemo<LayerPainter | null>(
    () =>
      composePainters(
        cadPainter,
        marks.length > 0
          ? createRemarksPainter(
              { marks, colors: colors.remarks, activeId: draft ? DRAFT_ID : activeRemark },
              { clear: cadPainter === null },
            )
          : null,
      ),
    [cadPainter, marks, colors.remarks, activeRemark, draft],
  );

  const activeCamera = mode === 'cad' ? cadCamera : pdfCamera;
  const activeSheet = mode === 'cad' ? standaloneView : pdf.sheet;
  usePinchZoom(hostRef, activeCamera);

  const hostSize = useCallback(() => {
    const element = hostRef.current;
    return { width: element?.clientWidth ?? 0, height: element?.clientHeight ?? 0 };
  }, []);

  const toggleLayer = useCallback((index: number) => {
    setHiddenLayers((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }, []);

  const options: readonly ISegmentedOption<CadViewerMode>[] = [
    { value: 'pdf', label: 'PDF' },
    {
      value: 'cad',
      label: 'CAD',
      disabled: !cadEnabled,
      hint: cadEnabled ? undefined : 'Предпросмотра DXF нет',
    },
    {
      value: 'overlay',
      label: 'Наложение',
      disabled: !overlayEnabled,
      hint: overlayEnabled ? undefined : 'Кадр координат не подтверждён',
    },
  ];

  const previewError = previewQuery.isError ? cadViewErrorText(previewQuery.error) : null;
  const shownFailure =
    mode !== 'cad' &&
    renderFailure !== null &&
    renderFailure.backend === pdf.backend &&
    renderFailure.pageIndex === (pdf.sheet?.pageIndex ?? null)
      ? renderFailure
      : null;
  const pdfError = pdf.outOfRange
    ? { code: 'PDF_PAGE_MISSING', text: `В PDF ревизии нет страницы ${pageIndex + 1}.` }
    : pdf.errorCode
      ? {
          code: pdf.errorCode,
          text: errorMessage(pdf.errorCode, 'Не удалось открыть PDF ревизии.'),
        }
      : null;

  const markDisabledReason =
    mode === 'cad'
      ? diagnostics.frame.confirmed
        ? 'В режиме CAD замечания не рисуются: они привязаны к координатам PDF. Переключитесь на «PDF» или «Наложение».'
        : 'В режиме CAD отметка недоступна: кадр координат не подтверждён, а замечания привязаны к координатам PDF. Переключитесь на «PDF».'
      : pdfError
        ? 'Отметка недоступна: страница PDF не показана.'
        : pdf.sheet === null
          ? 'Отметка станет доступна, когда загрузится страница PDF.'
          : null;
  const markingOn = marking && markDisabledReason === null;

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
  const focusRemark = (state: CameraState) => pdfCamera.set(state);

  return (
    <section className="flex min-w-0 flex-col gap-[var(--s-5)]" aria-label="Просмотр вида">
      <CadViewerControls
        mode={mode}
        options={options}
        onModeChange={setPicked}
        onZoomIn={() => activeCamera.zoomIn(hostSize())}
        onZoomOut={() => activeCamera.zoomOut(hostSize())}
        onFit={() => activeSheet && activeCamera.fitPage(activeSheet, hostSize())}
        layers={layerNames}
        visibleLayers={visibleLayers}
        onToggleLayer={toggleLayer}
        opacity={opacity}
        onOpacityChange={setOpacity}
        cadShown={mode !== 'pdf' && preview !== null}
        cropAvailable={cropAvailable}
        cropVisible={cropVisible}
        onCropChange={setCropVisible}
      />

      {cadEnabled && !diagnostics.frame.confirmed && (
        <p className={NOTICE} role="note">
          Сравнение с PDF недоступно: кадр координат не подтверждён.
          {diagnostics.frame.reason ? ` ${diagnostics.frame.reason}` : ''}
        </p>
      )}
      {!cadEnabled && (
        <p className="text-xs text-muted" role="note">
          Предпросмотра DXF нет: показан только PDF страницы, диагностика - ниже.
        </p>
      )}
      {preview?.truncated && (
        <p className={NOTICE} role="note">
          Показана упрощённая геометрия (flatten_mm {formatNumber(preview.flatten_mm, 3)}). Для
          точных размеров используйте DXF.
        </p>
      )}
      {preview && (
        <p className="text-xs text-muted">
          Точек в предпросмотре: <span className="tabular">{formatInt(preview.point_count)}</span>
        </p>
      )}
      {previewMismatch && (
        <ErrorState
          title="Предпросмотр не относится к DXF этой попытки"
          code="CAD_PREVIEW_SHA_MISMATCH"
        />
      )}
      {previewError && (
        <ErrorState
          title="Предпросмотр CAD не загружен"
          code={previewError.code}
          description={previewError.text}
          onRetry={() => void previewQuery.refetch()}
        />
      )}
      {shownFailure && (
        <p className={NOTICE} role="alert">
          Не удалось отрисовать страницу PDF ({shownFailure.code}).
        </p>
      )}

      <div
        ref={hostRef}
        className="relative h-[min(60dvh,640px)] min-h-[280px] w-full touch-none overflow-hidden rounded-[var(--radius-md)] border border-border"
      >
        {mode === 'cad' ? (
          previewQuery.isPending ? (
            <Skeleton className="absolute inset-0" />
          ) : standaloneView ? (
            <DrawingViewport
              key="cad"
              backend={null}
              sheet={standaloneView}
              regions={NO_REGIONS}
              hiddenTypes={NO_HIDDEN}
              overlayVisible={false}
              selectedId={null}
              onSelect={noop}
              camera={cadCamera}
              tool="pan"
              extraPainter={painter}
            />
          ) : (
            <p className="p-[var(--s-6)] text-sm text-muted">В предпросмотре нет геометрии.</p>
          )
        ) : pdfError ? (
          <div className="p-[var(--s-4)]">
            <ErrorState
              title="PDF страницы не показан"
              code={pdfError.code}
              description={pdfError.text}
            />
          </div>
        ) : (
          <>
            <DrawingViewport
              key="pdf"
              backend={pdf.backend}
              sheet={pdf.sheet}
              regions={NO_REGIONS}
              hiddenTypes={NO_HIDDEN}
              overlayVisible={false}
              selectedId={null}
              onSelect={noop}
              camera={pdfCamera}
              tool="pan"
              extraPainter={painter}
              onError={(code) =>
                setRenderFailure({
                  code,
                  backend: pdf.backend,
                  pageIndex: pdf.sheet?.pageIndex ?? null,
                })
              }
              onRendered={() => setRenderFailure(null)}
            />
            {markingOn && pdf.sheet && (
              <CadRemarkCapture camera={pdfCamera} page={pdf.sheet} onDrawn={handleDrawn} />
            )}
            {(pdf.loading || (mode === 'overlay' && previewQuery.isPending)) && (
              <div
                role="status"
                className="pointer-events-none absolute right-[var(--s-4)] bottom-[var(--s-4)] rounded-[var(--radius-sm)] bg-surface px-[var(--s-4)] py-[var(--s-2)] text-micro text-muted"
              >
                {pdf.loading ? 'Загрузка PDF…' : 'Загрузка геометрии CAD…'}
              </div>
            )}
          </>
        )}
      </div>

      <CadRemarksPanel
        binding={binding}
        store={store}
        page={pdf.sheet}
        marking={markingOn}
        onMarkingChange={setMarking}
        markDisabledReason={markDisabledReason}
        draft={draft}
        onDraftSave={(value) => void saveDraft(value)}
        onDraftCancel={() => setDraft(null)}
        activeId={activeRemark}
        onActivate={setActiveRemark}
        onFocusCamera={mode === 'cad' ? null : focusRemark}
        viewport={hostSize}
      />
    </section>
  );
};
