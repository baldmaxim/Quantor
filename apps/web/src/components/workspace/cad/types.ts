import type { CadViewDiagnosticsRead } from '@quantor/api-client';

import type { ICadRemarks, IRemarkDraft } from '@/components/cad/viewer/useCadRemarks';
import type { BboxPt, IPageSizePt, IRemarkBinding } from '@/lib/cad/remarks';
import type { CadViewMode } from '@/lib/cad/view-mode';
import type { CameraState, Viewport } from '@/lib/viewer/camera';

/** Замечания вида: всё, что нужно разделу «Замечания» (тот же, что был на странице CAD). */
export interface IWorkspaceCadRemarks {
  readonly binding: IRemarkBinding;
  readonly store: ICadRemarks;
  readonly page: IPageSizePt | null;
  readonly marking: boolean;
  readonly onMarkingChange: (value: boolean) => void;
  readonly markDisabledReason: string | null;
  readonly draft: BboxPt | null;
  readonly onDraftSave: (draft: IRemarkDraft) => void;
  readonly onDraftCancel: () => void;
  readonly activeId: string | null;
  readonly onActivate: (id: string | null) => void;
  readonly onFocusCamera: (state: CameraState) => void;
  readonly viewport: () => Viewport;
}

/** Левая панель вкладки CAD: источник, листы и задания ревизии рабочей области. */
export interface IWorkspaceCadLeftProps {
  readonly projectId: string;
  readonly revisionId: string;
  /** Индекс страницы листа, открытого в рабочей области. */
  readonly activePage: number | null;
  readonly selectedJobId: string | null;
  readonly onOpenSheet: (pageIndex: number) => void;
  readonly onSelectJob: (jobId: string) => void;
  readonly onJobCreated: (jobId: string, pages: readonly number[]) => void;
  readonly onSourceSelect: (revisionId: string) => void;
}

/** Строка над холстом: заголовок вида, режим показа, масштаб камеры рабочей области. */
export interface IWorkspaceCadBarProps {
  readonly diagnostics: CadViewDiagnosticsRead;
  readonly views: readonly number[];
  readonly view: number | null;
  readonly onViewChange: (view: number) => void;
  readonly mode: CadViewMode;
  /** DXF можно показать на листе (кадр координат подтверждён, предпросмотр получен). */
  readonly dxfAvailable: boolean;
  /** Почему DXF нельзя показать; `null` - можно или ещё грузится. */
  readonly dxfReason: string | null;
  readonly onModeChange: (mode: CadViewMode) => void;
  readonly onZoomIn: () => void;
  readonly onZoomOut: () => void;
  readonly onFit: () => void;
  /** Предупреждения о показанной геометрии (упрощена, предпросмотр не принят). */
  readonly notices: readonly { readonly tone: 'note' | 'alert'; readonly text: string }[];
  readonly loading: boolean;
}

export interface IWorkspaceCadLayers {
  readonly layers: readonly string[];
  readonly visibleLayers: ReadonlySet<number>;
  readonly onToggleLayer: (index: number) => void;
  readonly pdfOpacity: number;
  readonly onPdfOpacityChange: (value: number) => void;
  readonly pdfOpacityActive: boolean;
  readonly cadShown: boolean;
  readonly previewAvailable: boolean;
  readonly pointCount: number | null;
  readonly cropAvailable: boolean;
  readonly cropVisible: boolean;
  readonly onCropChange: (visible: boolean) => void;
}

/** Вид листа с диагностикой: слои, замечания, масштаб и файлы. */
export interface IWorkspaceCadView {
  readonly diagnostics: CadViewDiagnosticsRead;
  readonly layers: IWorkspaceCadLayers;
  /** `null` - замечания пока недоступны. */
  readonly remarks: IWorkspaceCadRemarks | null;
}

/** Задание листа: то, что нужно разделу «Задание». */
export interface IWorkspaceCadJob {
  readonly projectId: string;
  readonly revisionId: string;
  readonly jobId: string;
  readonly page: number | null;
  readonly view: number | null;
  readonly onSelectView: (page: number, view: number) => void;
  readonly onJobCreated: (jobId: string) => void;
}

export type WorkspaceCadState =
  /** Лист не выбран. */
  | 'no-sheet'
  /** Список заданий ещё не получен. */
  | 'loading'
  /** Список заданий не получен. */
  | 'error'
  /** По листу заданий не было. */
  | 'none'
  /** У листа есть задание. */
  | 'ready';

export interface IWorkspaceCadSideProps {
  readonly state: WorkspaceCadState;
  /** Подпись листа для подсказок. */
  readonly sheetLabel: string | null;
  readonly loadError: string | null;
  readonly onRetry: () => void;
  readonly job: IWorkspaceCadJob | null;
  /** Диагностика вида ещё читается. */
  readonly viewLoading: boolean;
  /** Отказ чтения задания или диагностики. */
  readonly viewError: { readonly code: string; readonly text: string } | null;
  readonly view: IWorkspaceCadView | null;
}
