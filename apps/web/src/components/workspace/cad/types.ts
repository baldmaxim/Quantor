import type { CadViewDiagnosticsRead } from '@quantor/api-client';

import type { ICadRemarks, IRemarkDraft } from '@/components/cad/viewer/useCadRemarks';
import type { BboxPt, IPageSizePt, IRemarkBinding } from '@/lib/cad/remarks';
import type { CameraState, Viewport } from '@/lib/viewer/camera';

/** Замечания вида: всё, что нужно разделу «Замечания» (тот же, что на странице CAD). */
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

/** Лист распознан: вид, диагностика, наложение и замечания. */
export interface IWorkspaceCadRecognized {
  /** Итог задания (`result_status`) для бейджа; `null` - задание ещё читается. */
  readonly resultStatus: string | null;
  /** Задание или диагностика вида ещё читаются. */
  readonly loading: boolean;
  /** Отказ чтения задания или диагностики. */
  readonly error: { readonly code: string; readonly text: string } | null;
  readonly diagnostics: CadViewDiagnosticsRead | null;
  readonly views: readonly number[];
  readonly view: number | null;
  readonly onViewChange: (view: number) => void;
  readonly overlay: boolean;
  readonly overlayAvailable: boolean;
  readonly overlayReason: string | null;
  readonly overlayLoading: boolean;
  readonly overlayError: string | null;
  readonly onOverlayChange: (value: boolean) => void;
  /** `null` - замечания пока недоступны (диагностика не получена). */
  readonly remarks: IWorkspaceCadRemarks | null;
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
  | 'running'
  | 'failed'
  | 'recognized';

export interface IWorkspaceCadPanelProps {
  readonly state: WorkspaceCadState;
  /** Подпись листа для подсказок. */
  readonly sheetLabel: string | null;
  /** Куда ведёт ссылка на страницу CAD в текущем состоянии. */
  readonly cadHref: string;
  readonly loadError: string | null;
  readonly onRetry: () => void;
  readonly recognized: IWorkspaceCadRecognized | null;
}
