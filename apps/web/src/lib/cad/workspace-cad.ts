import type {
  CadJobRead,
  CadJobSummaryRead,
  CadPreviewRead,
  CadViewDiagnosticsRead,
} from '@quantor/api-client';

import type { NormalizedRect } from '@/lib/viewer/coordinates';

import type { ICadPaintData } from './cad-painter';
import { overlayPaths, type ICadFrame, type INormalizedPath, type IPageSize } from './frame';
import { assignLayerColors } from './layer-colors';
import { bboxPtToNormalized, type BboxPt, type IRemark, type IRemarkBinding } from './remarks';
import type { IRemarkMark } from './remarks-painter';
import { READABLE_RESULTS } from './selection';
import type { ICadViewParams } from './view-queries';

/**
 * Чистые правила CAD во вкладке рабочей области: какой вид показать, можно ли наложение,
 * как собрать данные слоя и замечания. Без DOM и React, чтобы ошибки «DXF не лёг
 * на чертёж» ловились тестами, а не глазами.
 */

/** Непрозрачность DXF в рабочей области: геометрия всегда непрозрачная, гаснет только подложка PDF. */
export const WORKSPACE_CAD_OPACITY = 1;

/** Пустой набор путей: общий объект, чтобы кеш путей рисовальщика не плодил записи. */
const NO_PATHS: readonly INormalizedPath[] = [];

/** Идентификатор несохранённого участка на листе. */
export const WORKSPACE_DRAFT_ID = '__draft__';

/** Результат задания можно читать: попытка-результат есть и итог выпущен. */
export const isReadableJob = (job: Pick<CadJobRead, 'result_attempt' | 'result_status'>): boolean =>
  job.result_attempt !== null &&
  job.result_status !== null &&
  READABLE_RESULTS.has(job.result_status);

export interface IWorkspaceViewPick {
  /** Виды листа в задании по возрастанию. */
  readonly views: readonly number[];
  /** Показанный вид: выбранный, если он есть у листа, иначе первый; `null` - видов нет. */
  readonly view: number | null;
}

export const pickWorkspaceView = (
  job: Pick<CadJobRead, 'pages'>,
  pageIndex: number,
  chosen: number | null,
): IWorkspaceViewPick => {
  const views = (job.pages.find((item) => item.index === pageIndex)?.views ?? [])
    .map((entry) => entry.view)
    .sort((a, b) => a - b);
  const view = chosen !== null && views.includes(chosen) ? chosen : (views[0] ?? null);
  return { views, view };
};

/** Параметры запросов вида; `null` - читать нечего (задание не готово или у листа нет вида). */
export const workspaceViewParams = (
  projectId: string,
  revisionId: string,
  job: Pick<CadJobRead, 'job_id' | 'result_attempt' | 'result_status'>,
  pageIndex: number,
  view: number | null,
): ICadViewParams | null =>
  view !== null && job.result_attempt !== null && isReadableJob(job)
    ? { projectId, revisionId, jobId: job.job_id, attempt: job.result_attempt, pageIndex, view }
    : null;

/**
 * Параметры чтения вида по сводке задания (без полного задания): только для завершённого
 * задания с читаемым итогом. Попытка - текущая попытка задания (у завершённого она же результат),
 * вид - выбранный или первый. Ответ другой попытки или вида запрос отбрасывает сам (см. `sameView`),
 * когда полное задание придёт, параметры берутся уже из него.
 */
export const summaryViewParams = (
  projectId: string,
  revisionId: string,
  summary: Pick<CadJobSummaryRead, 'job_id' | 'status' | 'attempt' | 'result_status'>,
  pageIndex: number,
  chosenView: number | null,
): ICadViewParams | null =>
  summary.status === 'succeeded' &&
  summary.attempt >= 1 &&
  summary.result_status !== null &&
  READABLE_RESULTS.has(summary.result_status)
    ? {
        projectId,
        revisionId,
        jobId: summary.job_id,
        attempt: summary.attempt,
        pageIndex,
        view: chosenView ?? 1,
      }
    : null;

/** Параметры «ничего не читать»: пустые идентификаторы под выключенными запросами. */
export const IDLE_VIEW_PARAMS: ICadViewParams = {
  projectId: '',
  revisionId: '',
  jobId: '',
  attempt: 0,
  pageIndex: 0,
  view: 0,
};

/** Предпросмотр обязан описывать тот же DXF, что назван в диагностике. */
export const matchingPreview = (
  diagnostics: Pick<CadViewDiagnosticsRead, 'dxf'>,
  preview: CadPreviewRead | undefined,
): CadPreviewRead | null =>
  preview && preview.dxf_sha256 === diagnostics.dxf?.sha256 ? preview : null;

export interface IOverlayAvailability {
  readonly available: boolean;
  /** Почему наложения нет; `null` - доступно. */
  readonly reason: string | null;
}

/**
 * Наложение допускается только при подтверждённом кадре: так же решает панель вида на странице
 * CAD. Пока предпросмотр не пришёл, наложение считается доступным; пришёл, но кадр не
 * собирается - нет.
 */
export const overlayAvailability = (
  diagnostics: Pick<CadViewDiagnosticsRead, 'preview_available' | 'frame'>,
  preview: CadPreviewRead | null,
  frame: ICadFrame | null,
): IOverlayAvailability => {
  if (!diagnostics.preview_available) {
    return { available: false, reason: 'Предпросмотра DXF нет: у вида только диагностика.' };
  }
  if (!diagnostics.frame.confirmed || (preview !== null && frame === null)) {
    return { available: false, reason: 'Кадр координат не подтверждён: DXF не накладывается.' };
  }
  return { available: true, reason: null };
};

export interface IOverlayPaintOptions {
  /** Геометрия DXF рисуется; `false` - остаётся только область проверки масштаба. */
  readonly dxfVisible?: boolean;
  /** Индексы слоёв DXF, скрытых человеком. */
  readonly hiddenLayers?: ReadonlySet<number>;
  /** Область проверки масштаба на листе. */
  readonly crop?: { readonly rect: NormalizedRect; readonly color: string } | null;
  /**
   * Уже нормализованные пути `preview` (по `preview`, кадру и размеру листа). Переключение слоя
   * не меняет ни одного из них, поэтому вызывающий считает пути отдельно и один раз.
   */
  readonly paths?: readonly INormalizedPath[];
}

/**
 * Данные слоя DXF на листе; `null` - рисовать нечего. Поворот страницы не применяется (ADR-0008).
 * Область проверки масштаба рисуется и без геометрии: она относится к PDF.
 */
export const overlayPaintData = (
  preview: CadPreviewRead | null,
  frame: ICadFrame | null,
  page: IPageSize | null,
  ink: string,
  layerPalette: readonly string[] = [],
  options: IOverlayPaintOptions = {},
): ICadPaintData | null => {
  const { dxfVisible = true, hiddenLayers, crop = null, paths } = options;
  if (!page) return null;
  const geometry = dxfVisible && preview !== null && frame !== null ? { preview, frame } : null;
  if (geometry === null && crop === null) return null;
  const layers = preview?.layers ?? [];
  return {
    paths: geometry
      ? (paths ?? overlayPaths(geometry.preview.paths, geometry.frame, page))
      : NO_PATHS,
    visibleLayers: new Set(
      layers.map((_, index) => index).filter((index) => !hiddenLayers?.has(index)),
    ),
    opacity: WORKSPACE_CAD_OPACITY,
    layerColors: assignLayerColors(layerPalette, layers.length),
    ink,
    paper: null,
    crop,
  };
};

/** Отметки замечаний и черновика на листе (доли листа). */
export const workspaceMarks = (
  remarks: readonly Pick<IRemark, 'id' | 'status' | 'bbox_pt'>[],
  draft: BboxPt | null,
  page: IPageSize | null,
): IRemarkMark[] => {
  if (!page) return [];
  const list: IRemarkMark[] = remarks.map((remark, index) => ({
    id: remark.id,
    number: index + 1,
    status: remark.status,
    rect: bboxPtToNormalized(remark.bbox_pt, page),
  }));
  if (draft) {
    list.push({
      id: WORKSPACE_DRAFT_ID,
      number: remarks.length + 1,
      status: 'open',
      rect: bboxPtToNormalized(draft, page),
    });
  }
  return list;
};

/** Привязка замечаний к виду по параметрам чтения и диагностике; `null` - вид ещё не получен. */
export const remarkBindingOf = (
  params: ICadViewParams | null,
  diagnostics: Pick<CadViewDiagnosticsRead, 'legacy_pdf_page' | 'dxf'> | null,
): IRemarkBinding | null =>
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
    : null;

/** Привязка «ничего не читать»: пустые идентификаторы под выключенными запросами замечаний. */
export const IDLE_REMARK_BINDING: IRemarkBinding = {
  projectId: '',
  revisionId: '',
  jobId: '',
  attempt: 0,
  pageIndex: 0,
  legacyPdfPage: 0,
  view: 0,
  dxfSha256: null,
};
