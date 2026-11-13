import type {
  CadConstructionProps,
  CadConstructionRead,
  CadConstructionsRead,
  CadDecisionRead,
  CadFinishTemplateRead,
  CadJobRead,
  CadRouteJobRead,
  CadSheetFloorTitle,
  CadSheetLevelsWrite,
  CadViewDiagnosticsRead,
  CadVorCoverageRead,
  CadVorDocumentRead,
  CadZoneRead,
  JobStatus,
  SectionsRead,
} from '@quantor/api-client';

import type { IFinishAssignOutcome } from '@/components/cad/finishes/CadZoneFinishBar';
import type { ICadZoneLayers } from '@/components/cad/viewer/CadZoneLayers';
import type { ICadRemarks, IRemarkDraft } from '@/components/cad/viewer/useCadRemarks';
import type { IConstructionIndex } from '@/lib/cad/constructions';
import type { CadExtraCategory } from '@/lib/cad/layer-categories';
import type { ICadLayerCounts } from '@/lib/cad/layer-counts';
import type { BboxPt, IPageSizePt, IRemarkBinding } from '@/lib/cad/remarks';
import type { RoomType } from '@/lib/cad/room-types';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import type { IVorSource } from '@/lib/cad/vor-queries';
import type { ParkingType, ZoneKind } from '@/lib/cad/zones';
import type { Camera, CameraState, Viewport } from '@/lib/viewer/camera';

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

/** Назначение шаблона отделки зонам из списка зон (ADR-0042). */
export interface IWorkspaceCadZoneFinish {
  readonly templates: readonly CadFinishTemplateRead[];
  readonly assigning: boolean;
  /** Отказ последнего назначения. */
  readonly error: string | null;
  /** Назначить шаблон зонам; `null` снимает явное назначение. `null` в ответе - отказ. */
  readonly onAssign: (
    zoneIds: readonly string[],
    templateId: string | null,
  ) => Promise<IFinishAssignOutcome | null>;
}

/** Раздел «Отделка»: к какому листу относится ведомость (шаблоны - на весь проект). */
export interface IWorkspaceCadFinishes {
  readonly projectId: string;
  readonly revisionId: string | null;
  readonly pageIndex: number | null;
  /** Флаг `cad.export` включён и вкладка CAD открывалась: без этого запросов нет. */
  readonly load: boolean;
}

/** Автоматическая разметка зон листа: то же задание, что кнопка в окне «Обработка листа». */
export interface IWorkspaceCadAutoZones {
  readonly onStart: () => void;
  /** Постановка идёт или задание зон листа в очереди либо выполняется. */
  readonly starting: boolean;
  /** Отказ последнего запуска. */
  readonly error: string | null;
}

/** Раздел «Зоны»: помещения квартир, МОП и двери открытого листа. */
export interface IWorkspaceCadZones {
  readonly zones: readonly CadZoneRead[];
  readonly loading: boolean;
  readonly loadError: string | null;
  readonly onReload: () => void;
  /** Вид зоны, которую рисуют. */
  readonly kind: ZoneKind;
  readonly onKindChange: (kind: ZoneKind) => void;
  readonly apartmentNo: string;
  readonly onApartmentNoChange: (value: string) => void;
  readonly roomMark: string;
  readonly onRoomMarkChange: (value: string) => void;
  /** Высота проёма двери, мм: текст поля. */
  readonly doorHeight: string;
  readonly onDoorHeightChange: (value: string) => void;
  /** Тип машино-места, которое рисуют. */
  readonly parkingType: ParkingType;
  readonly onParkingTypeChange: (type: ParkingType) => void;
  /** Сменить тип у готового машино-места. */
  readonly onSetParkingType: (id: string, type: ParkingType) => void;
  /** Сменить тип помещения у зоны (МОП или квартира); нет - тип в списке не правится. */
  readonly onSetRoomType?: (id: string, type: RoomType | null) => void;
  /** Выбор зон и назначение шаблона отделки; `null` или нет - выбора нет. */
  readonly finish?: IWorkspaceCadZoneFinish | null;
  /** Режим рисования включён: поверх холста лежит слой захвата. */
  readonly drawing: boolean;
  /** Почему рисовать нельзя (не заполнено поле, страница не загружена); `null` - можно. */
  readonly drawDisabledReason: string | null;
  readonly onStartDrawing: () => void;
  readonly onStopDrawing: () => void;
  readonly activeId: string | null;
  readonly onActivate: (id: string | null) => void;
  /** Запись или удаление идёт. */
  readonly saving: boolean;
  /** Отказ последней операции. */
  readonly error: string | null;
  readonly onRename: (id: string, name: string) => void;
  readonly onDelete: (id: string) => void;
  /** Включён режим правки контура или разреза зоны-помещения; `null` - выключен. */
  readonly shapeEdit: { readonly id: string; readonly mode: 'edit' | 'split' } | null;
  /** Почему править контур нельзя (страница не загружена, идёт отметка замечания); `null` - можно. */
  readonly shapeEditDisabledReason: string | null;
  readonly onStartEdit: (id: string) => void;
  readonly onStartSplit: (id: string) => void;
  /** Автоматическая разметка; `null` или нет - кнопки нет (нет вида с DXF). */
  readonly autoZones?: IWorkspaceCadAutoZones | null;
}

/** ВОР Заказчика в разделе «Конструкции»: только объект сверки, на расчёт не влияет (ADR-0038 п. 5). */
export interface IWorkspaceCadVor {
  readonly projectId: string;
  /** Текущий документ ВОР проекта; `null` - не загружен. */
  readonly document: CadVorDocumentRead | null;
  /** Сверка листа; `null` - ещё не прочитана. */
  readonly coverage: CadVorCoverageRead | null;
  readonly loading: boolean;
  /** Идёт импорт ВОР из документа проекта. */
  readonly importing: boolean;
  readonly deleting: boolean;
  /** Книги .xlsx из документов проекта: из них выбирается ВОР. */
  readonly sources: readonly IVorSource[];
  readonly sourcesLoading: boolean;
  /** Отказ последней операции (импорт, удаление, чтение). */
  readonly error: string | null;
  /** Взять ВОР из ревизии документа проекта; прежний ВОР заменяется вместе со связями. */
  readonly onImport: (revisionId: string) => void;
  readonly onDelete: () => void;
  /** Подсвечивать на холсте конструкции «не в ВОР». */
  readonly showNotInVor: boolean;
  readonly onShowNotInVorChange: (visible: boolean) => void;
}

/** Раздел «Конструкции»: свод кладки и монолита листа (ADR-0038). */
export interface IWorkspaceCadConstructions {
  /** `loading` - читается; `not-ready` - результата расчёта нет; `error` - отказ чтения. */
  readonly status: 'loading' | 'ready' | 'not-ready' | 'error';
  readonly data: CadConstructionsRead | null;
  /** Что сказать, когда результата нет (ещё считается, ошибка, не запускалось). */
  readonly notReadyText: string | null;
  readonly loadError: string | null;
  readonly onReload: () => void;
  /** Расчёт идёт (задание в очереди или выполняется). */
  readonly calculating: boolean;
  /** Отказ последнего действия (запуск расчёта, высоты). */
  readonly actionError: string | null;
  /** Самый свежий пересчёт упал, показан прежний результат: текст причины. */
  readonly recomputeFailure?: string | null;
  readonly onCompute: () => void;
  readonly levelsSaving: boolean;
  readonly onSaveLevels: (levels: CadSheetLevelsWrite) => void;
  /** Ключ подсвеченной строки свода; `null` - ничего. */
  readonly activeGroup: string | null;
  /** Подсветить конструкции строки на холсте; повтор по той же строке снимает подсветку. */
  readonly onSelectGroup: (key: string, ids: readonly string[]) => void;
  /** Сверка с ВОР Заказчика; нет - блок не показывается. */
  readonly vor?: IWorkspaceCadVor | null;
}

/** Карточка выбранной конструкции у курсора. */
export interface IWorkspaceCadConstructionPopover {
  readonly construction: CadConstructionRead;
  /** Дверей, стоящих в этой конструкции. */
  readonly doors: number;
  /** Конструкций того же вида и номинала на листе, включая выбранную. */
  readonly groupCount: number;
  /** Точка клика, экранные координаты. */
  readonly anchor: { readonly x: number; readonly y: number };
  readonly saving: boolean;
  readonly error: string | null;
  readonly onClose: () => void;
  readonly onSave: (props: CadConstructionProps) => void;
  readonly onBulk: (patch: CadConstructionProps) => void;
  readonly onAccept: (accepted: boolean) => void;
}

/** Выбор конструкции щелчком по холсту и её карточка. */
export interface IWorkspaceCadConstructionPicker {
  readonly camera: Camera;
  /** Размер листа у отрисовщика (pt при масштабе 1). */
  readonly page: { readonly width: number; readonly height: number };
  readonly index: IConstructionIndex;
  /** Щелчок: конструкция под курсором или `null` (пустое место) и точка клика. */
  readonly onPick: (id: string | null, anchor: { x: number; y: number }) => void;
  /** Карточку закрыть (панорама, зум, щелчок вне, Esc); выделение остаётся. */
  readonly onDismiss: () => void;
  readonly popover: IWorkspaceCadConstructionPopover | null;
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
  /** Нужна ли панели широкая колонка: хотя бы в одной строке листа есть бейдж. */
  readonly onWideChange?: (wide: boolean) => void;
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
  /** Переключатель «План | 3D» (ADR-0039); нет - переключателя нет. */
  readonly floor3d?: {
    readonly mode: 'plan' | '3d';
    readonly onModeChange: (mode: 'plan' | '3d') => void;
  } | null;
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
  /** Число рядом с пунктом по индексу `names`; `null` или нет массива - без числа. */
  readonly counts?: readonly (number | null)[];
}

export interface IWorkspaceCadLayers {
  /** Трассы механики выбранного route-задания; `null` - их на листе нет. */
  readonly mep?: IWorkspaceCadMepLayers | null;
  readonly layers: readonly string[];
  readonly visibleLayers: ReadonlySet<number>;
  readonly onToggleLayer: (index: number) => void;
  /** Скрыть или показать несколько слоёв разом (переключатель группы). */
  readonly onSetLayersHidden: (indices: readonly number[], hidden: boolean) => void;
  /** Открыт режим «3D»: слои без категории конструкций доступны только в плане. */
  readonly mode3d?: boolean;
  /** Строки без слоя DXF («Монолит», «Плита»): видимость в плане и в 3D. */
  readonly categories?: {
    readonly monolithVertical: boolean;
    readonly monolithColumn: boolean;
    readonly slab: boolean;
    readonly onChange: (category: CadExtraCategory, visible: boolean) => void;
  } | null;
  /** Числа справа у строк и групп; нет - без чисел. */
  readonly counts?: ICadLayerCounts | null;
  readonly pdfOpacity: number;
  readonly onPdfOpacityChange: (value: number) => void;
  readonly pdfOpacityActive: boolean;
  readonly cadShown: boolean;
  readonly previewAvailable: boolean;
  readonly pointCount: number | null;
  readonly cropAvailable: boolean;
  readonly cropVisible: boolean;
  readonly onCropChange: (visible: boolean) => void;
  /** Слой «Конструкции»; `null` или нет - переключателя нет (конструкции не считались). */
  readonly constructions?: {
    readonly visible: boolean;
    readonly onVisibleChange: (visible: boolean) => void;
  } | null;
  /** Блок «Зоны» (цвет, скрытие по типам, подписи); `null` или нет - на листе зон нет. */
  readonly zones?: ICadZoneLayers | null;
  /** Разметка разрезов на листе (вкл/выкл); `null` или нет - переключателя нет (разрезов нет). */
  readonly sections?: {
    readonly visible: boolean;
    readonly onVisibleChange: (visible: boolean) => void;
  } | null;
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
  /** Отозванные принятия этого вида, старые сверху. */
  readonly revokedDecisions: readonly CadDecisionRead[];
  /** Отказ чтения задания, вида или превью. */
  readonly error: string | null;
}

/** Вкладка «Трассы»: одобрение вида, построение, принятие, скачивание. */
export interface IWorkspaceCadMep {
  /** Родитель: задание преобразования, попытка с результатом, лист и вид. */
  readonly parent: ICadViewParams;
  readonly approval: CadDecisionRead | null;
  /** Отозванные одобрения этого вида, старые сверху. */
  readonly revokedDecisions: readonly CadDecisionRead[];
  /** Route-задания этого вида, новые сверху. */
  readonly routeJobs: readonly CadRouteJobRead[];
  readonly route: IWorkspaceCadMepRoute | null;
  /** Открытые замечания показанного вида (родителя или трасс); `null` - ещё не прочитаны. */
  readonly openRemarks: number | null;
  /** Открыть трассы (задание) или вернуться к виду (`null`). */
  readonly onSelectRoute: (jobId: string | null) => void;
  /** Разрезы ревизии для блока «Высота из разрезов»; `null` или нет - блока нет. */
  readonly sections?: IWorkspaceCadSectionsLink | null;
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
  /** Включает инструмент «Масштаб» на открытом листе в текущем окне. */
  readonly onCalibrate: () => void;
  /** Задание создано: рабочая область открывает его. */
  readonly onJobCreated: (jobId: string, pages: readonly number[]) => void;
  /** Режим «Преобразовать заново» для листа, уже преобразованного в CAD. */
  readonly again?: boolean;
  /** Текущее задание преобразования листа: совпадение с ответом сервера - повтор не нужен. */
  readonly currentJobId?: string | null;
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

/** Обновление CAD листа: более новый прогон после показанного (идёт или упал). */
export interface IWorkspaceCadUpdate {
  readonly status: JobStatus;
  /** Когда создан показанный (прежний) прогон; `null` - неизвестно. */
  readonly shownAt: string | null;
  /** Понятная причина отказа обновления; `null` - не указана. */
  readonly errorText: string | null;
}

export interface IWorkspaceCadSideProps {
  readonly state: WorkspaceCadState;
  /** Подпись листа для подсказок. */
  readonly sheetLabel: string | null;
  /** Заголовок плана листа (корпус, секция, этаж): лист подписывается этажом, номер - второй. */
  readonly floorTitle?: CadSheetFloorTitle | null;
  readonly loadError: string | null;
  readonly onRetry: () => void;
  readonly job: IWorkspaceCadJob | null;
  /** Обновление CAD листа поверх показанного прогона; `null` или нет - обновления нет. */
  readonly update?: IWorkspaceCadUpdate | null;
  /** `null` - лист или ревизия не выбраны. */
  readonly convert: IWorkspaceCadConvert | null;
  /** Диагностика вида ещё читается. */
  readonly viewLoading: boolean;
  /** Отказ чтения задания или диагностики. */
  readonly viewError: { readonly code: string; readonly text: string } | null;
  readonly view: IWorkspaceCadView | null;
  /** Раздел «Зоны»; `null` или нет - раздела нет. */
  readonly zones?: IWorkspaceCadZones | null;
  /** Раздел «Конструкции»; `null` или нет - раздела нет. */
  readonly constructions?: IWorkspaceCadConstructions | null;
  /** Раздел «Отделка» (нужен и раздел «Зоны»: выбор зон идёт через него); `null` или нет - раздела нет. */
  readonly finishes?: IWorkspaceCadFinishes | null;
  /** Раздел «Разрезы»; `null` или нет - раздела нет. */
  readonly sections?: IWorkspaceCadSections | null;
}

/** Раздел «Разрезы»: распознавание разрезов ревизии, кандидаты уровней и их принятие. */
export interface IWorkspaceCadSections {
  /** `loading` - читается; `error` - отказ чтения; `ready` - данные есть (возможно, пустые). */
  readonly status: 'loading' | 'ready' | 'error';
  readonly data: SectionsRead | null;
  readonly loadError: string | null;
  readonly onReload: () => void;
  /** Индекс страницы открытого листа; `null` - лист не выбран. */
  readonly pageIndex: number | null;
  /** Открытый лист - страница-разрез (есть в `data.pages`): только на ней есть вкладка «Разрезы». */
  readonly isSectionPage: boolean;
  /** Постановка задания идёт. */
  readonly starting: boolean;
  readonly onStart: () => void;
  /** Решение по уровням отправлено и не завершено. */
  readonly deciding: boolean;
  readonly onDecide: (levelIds: readonly string[], decision: 'accept' | 'reject' | 'reset') => void;
  /** Отказ последнего действия (постановка, решение). */
  readonly actionError: string | null;
  /** Выбранный уровень (выделен на листе); `null` - нет. */
  readonly activeLevelId: string | null;
  readonly onSelectLevel: (id: string | null) => void;
  /** Разметка разрезов рисуется на листе. */
  readonly markupVisible: boolean;
  readonly onMarkupVisibleChange: (visible: boolean) => void;
  /** Открыть страницу-разрез в рабочей области. */
  readonly onOpenPage: (pageIndex: number) => void;
}

/** Срез разрезов для запуска трасс: сводка, запуск распознавания и переход на страницу-разрез. */
export type IWorkspaceCadSectionsLink = Pick<
  IWorkspaceCadSections,
  'status' | 'data' | 'starting' | 'onStart' | 'onOpenPage' | 'actionError'
>;
