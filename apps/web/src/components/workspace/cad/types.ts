import type {
  CadDecisionRead,
  CadJobRead,
  CadRouteJobRead,
  CadViewDiagnosticsRead,
} from '@quantor/api-client';

import type { ICadRemarks, IRemarkDraft } from '@/components/cad/viewer/useCadRemarks';
import type { BboxPt, IPageSizePt, IRemarkBinding } from '@/lib/cad/remarks';
import type { ICadViewParams } from '@/lib/cad/view-queries';
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

/** Левая панель вкладки CAD: листы и задания ревизии рабочей области. */
export interface IWorkspaceCadLeftProps {
  readonly projectId: string;
  readonly revisionId: string;
  /** Индекс страницы листа, открытого в рабочей области. */
  readonly activePage: number | null;
  readonly selectedJobId: string | null;
  readonly onOpenSheet: (pageIndex: number) => void;
  readonly onSelectJob: (jobId: string) => void;
}

/** Строка над холстом: заголовок вида, переключатель видов, «Вписать» для камеры рабочей области. */
export interface IWorkspaceCadBarProps {
  readonly diagnostics: CadViewDiagnosticsRead;
  readonly views: readonly number[];
  readonly view: number | null;
  readonly onViewChange: (view: number) => void;
  readonly onFit: () => void;
  /** Предупреждения о показанной геометрии (упрощена, предпросмотр не принят). */
  readonly notices: readonly { readonly tone: 'note' | 'alert'; readonly text: string }[];
  readonly loading: boolean;
}

/** Группа «Трассы механики» панели «Слои»: слои route-задания, которые есть в превью. */
export interface IWorkspaceCadMepLayers {
  /** Имена слоёв DXF трасс, в порядке показа. */
  readonly names: readonly string[];
  /** Подписи пунктов списка, по одной на имя. */
  readonly titles: readonly string[];
  /** Индексы показанных слоёв. */
  readonly visible: ReadonlySet<number>;
  readonly onToggle: (index: number) => void;
  /** Скрыть или показать несколько слоёв разом (переключатель группы). */
  readonly onSetHidden: (indices: readonly number[], hidden: boolean) => void;
}

export interface IWorkspaceCadLayers {
  /** Трассы механики выбранного route-задания; `null` - их на листе нет. */
  readonly mep?: IWorkspaceCadMepLayers | null;
  readonly layers: readonly string[];
  readonly visibleLayers: ReadonlySet<number>;
  readonly onToggleLayer: (index: number) => void;
  /** Скрыть или показать несколько слоёв разом (переключатель группы). */
  readonly onSetLayersHidden: (indices: readonly number[], hidden: boolean) => void;
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

/** Выбранное route-задание: то, что нужно блоку «Принять трассы». */
export interface IWorkspaceCadMepRoute {
  readonly summaryId: string;
  /** Полное задание; `null` - ещё читается. */
  readonly job: CadJobRead | null;
  /** Параметры чтения вида трасс (задание, попытка-результат, лист, вид); `null` - результата нет. */
  readonly params: ICadViewParams | null;
  /** Принятие трасс; `null` - не приняты. */
  readonly acceptance: CadDecisionRead | null;
  /** Отказ чтения задания, вида или превью. */
  readonly error: string | null;
}

/** Вкладка «Трассы»: одобрение вида, построение, принятие, скачивание. */
export interface IWorkspaceCadMep {
  /** Родитель: задание преобразования, попытка с результатом, лист и вид. */
  readonly parent: ICadViewParams;
  readonly approval: CadDecisionRead | null;
  /** Route-задания этого вида, новые сверху. */
  readonly routeJobs: readonly CadRouteJobRead[];
  readonly route: IWorkspaceCadMepRoute | null;
  /** Открытые замечания показанного вида (родителя или трасс); `null` - ещё не прочитаны. */
  readonly openRemarks: number | null;
  /** Открыть трассы (задание) или вернуться к виду (`null`). */
  readonly onSelectRoute: (jobId: string | null) => void;
}

/** Вид листа с диагностикой: слои, замечания, масштаб и файлы. */
export interface IWorkspaceCadView {
  readonly diagnostics: CadViewDiagnosticsRead;
  readonly layers: IWorkspaceCadLayers;
  /** `null` - параметры вида не получены (трассы недоступны). */
  readonly mep?: IWorkspaceCadMep | null;
  /** `null` - замечания пока недоступны. */
  readonly remarks: IWorkspaceCadRemarks | null;
}

/** Задание листа: то, что нужно разделам «Задание» и «Файлы». */
export interface IWorkspaceCadJob {
  readonly projectId: string;
  readonly revisionId: string;
  readonly jobId: string;
  /** Полное задание; `null` - ещё читается. */
  readonly detail: CadJobRead | null;
  /** Последнее задание листа закончилось отказом: лист можно преобразовать заново. */
  readonly failed: boolean;
  readonly page: number | null;
  readonly view: number | null;
  readonly onSelectView: (page: number, view: number) => void;
}

/** Запуск преобразования открытого листа в CAD (одна страница). */
export interface IWorkspaceCadConvert {
  readonly projectId: string;
  readonly revisionId: string;
  readonly sheetId: string;
  /** Индекс страницы PDF открытого листа. */
  readonly pageIndex: number;
  /** Ссылка на лист в рабочей области для калибровки. */
  readonly calibrateHref: string;
  /** Задание создано: рабочая область открывает его. */
  readonly onJobCreated: (jobId: string, pages: readonly number[]) => void;
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
  /** `null` - лист или ревизия не выбраны. */
  readonly convert: IWorkspaceCadConvert | null;
  /** Диагностика вида ещё читается. */
  readonly viewLoading: boolean;
  /** Отказ чтения задания или диагностики. */
  readonly viewError: { readonly code: string; readonly text: string } | null;
  readonly view: IWorkspaceCadView | null;
}
