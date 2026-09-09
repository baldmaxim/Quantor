"""Перечисления предметной области.

Хранятся как строки с CHECK-ограничением, а не как нативные типы PostgreSQL: добавить значение
в молодую схему приходится часто, и ALTER TYPE в миграциях этому только мешает.
"""

from __future__ import annotations

from enum import StrEnum


class WorkspaceStatus(StrEnum):
    """Состояние рабочего пространства.

    Приостановленное пространство остаётся в базе со всеми данными: удаление арендатора —
    отдельная операция с другими последствиями, и путать её с временным отключением нельзя.
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserKind(StrEnum):
    """Человек или машина.

    Различие не косметическое: у машинной личности нет сессии в браузере, к ней неприменима
    политика второго фактора, и в журнале аудита её действия читаются иначе.
    """

    HUMAN = "human"
    SERVICE = "service"


class Role(StrEnum):
    """Роль — именованный набор разрешений, а не проверяемая сущность.

    Бизнес-код спрашивает разрешение (`Permission`), а не имя роли: состав набора меняется
    в одном месте, а не по всем обработчикам. Соответствие описано в `app/auth/permissions.py`.

    `PLATFORM_ADMIN` и `SERVICE` относятся к платформе и живут на самой личности; остальные
    выдаются членством в конкретном рабочем пространстве.
    """

    PLATFORM_ADMIN = "platform_admin"
    WORKSPACE_ADMIN = "workspace_admin"
    ENGINEER = "engineer"
    REVIEWER = "reviewer"
    VIEWER = "viewer"
    SERVICE = "service"


# Роли платформенного уровня. Ограничение в базе не даёт положить их в членство: иначе
# администратором платформы стал бы любой, кто может добавить себе строку в своём же
# пространстве.
PLATFORM_ROLES: frozenset[Role] = frozenset({Role.PLATFORM_ADMIN, Role.SERVICE})

# Роли, выдаваемые членством. Дополнение к платформенным, а не отдельный список: новая роль
# попадает ровно в одну группу и забыть её нельзя.
WORKSPACE_ROLES: frozenset[Role] = frozenset(Role) - PLATFORM_ROLES


class OverrideScope(StrEnum):
    """Уровень, на котором переопределяется настройка или флаг.

    `PROJECT` объявлен, но ни одной настройке пока не разрешён: контракт готов к
    расширению, а выдавать несуществующий уровень за работающий нельзя. Тест следит,
    чтобы уровень не появился в определениях раньше, чем в коде, который его читает.
    """

    SYSTEM = "system"
    WORKSPACE = "workspace"
    PROJECT = "project"


class ValueSource(StrEnum):
    """Откуда взялось действующее значение настройки или флага.

    Показывается администратору вместе со значением: «включено» без ответа на вопрос
    «кем и где» — это половина сведений, по которой ничего не починить.
    """

    DEFAULT = "default"
    SYSTEM = "system"
    WORKSPACE = "workspace"
    DEPLOYMENT = "deployment"


class AuditResult(StrEnum):
    """Чем закончилось действие.

    Отказ записывается наравне с успехом: попытка сделать то, на что нет прав, —
    это ровно то событие, ради которого журнал и заводят.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class AuditAction(StrEnum):
    """Словарь действий журнала.

    В базе — обычная строка, а не CHECK: набор пополняется каждый этап, и миграция
    на каждое новое действие была бы трением без выигрыша. Соответствие значений этому
    перечислению проверяется тестом.
    """

    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    SESSION_REVOKED = "session_revoked"

    SETTING_OVERRIDE_SET = "setting_override_set"
    SETTING_OVERRIDE_DELETED = "setting_override_deleted"

    FEATURE_FLAG_OVERRIDE_SET = "feature_flag_override_set"
    FEATURE_FLAG_OVERRIDE_DELETED = "feature_flag_override_deleted"

    TENDERHUB_CONNECTION_TESTED = "tenderhub_connection_tested"
    TENDERHUB_PROJECT_REBOUND = "tenderhub_project_rebound"
    TENDERHUB_PROJECT_UNLINKED = "tenderhub_project_unlinked"

    JOB_RETRIED = "job_retried"
    JOB_CANCELLED = "job_cancelled"

    PERMISSION_DENIED = "permission_denied"


class ProjectStatus(StrEnum):
    """Жизненный цикл проекта. Ход импорта сюда не пишется — он живёт в Job и ревизиях."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ProjectSource(StrEnum):
    """Откуда взялся проект.

    Нужен, чтобы отличить заведённый руками проект от подтянутого из внешней системы:
    у второго есть чужой идентификатор, и повторно создавать его нельзя.
    """

    MANUAL = "manual"
    TENDERHUB = "tenderhub"


class DocumentKind(StrEnum):
    """Природа документа. BIM-форматы принимаются на хранение, но не разбираются."""

    PDF = "pdf"
    RECOGNIZED_PACKAGE = "recognized_package"
    REVIT = "revit"
    NAVISWORKS = "navisworks"
    IFC = "ifc"
    OTHER = "other"


class ProcessingStatus(StrEnum):
    """Состояние обработки конкретной ревизии.

    Единственное изменяемое поле ревизии: описывает не файл, а ход работы над ним.
    """

    PENDING = "pending"
    UNPROCESSED = "unprocessed"
    PROCESSOR_UNAVAILABLE = "processor_unavailable"
    IMPORTING = "importing"
    READY = "ready"
    FAILED = "failed"


class ArtifactKind(StrEnum):
    """Роль файла внутри распознанного пакета."""

    BLOCKS_JSON = "blocks_json"
    RESULTS_MD = "results_md"
    RESULTS_HTML = "results_html"
    PACKAGE_ZIP = "package_zip"
    OTHER = "other"


class RegionShape(StrEnum):
    RECTANGLE = "rectangle"
    POLYGON = "polygon"


class GeometryType(StrEnum):
    """Что именно измеряют."""

    COUNT = "count"
    LINE = "line"
    POLYLINE = "polyline"
    POLYGON = "polygon"


class MeasurementSource(StrEnum):
    """Кто создал геометрию. Влияет на порядок проверки, а не на саму величину."""

    MANUAL = "manual"
    AI = "ai"
    IMPORTED = "imported"


class ScaleSource(StrEnum):
    """Откуда взялся масштаб чертежа.

    На Stage 2A публичный API создаёт только `manual`. Остальные объявлены как контракт,
    но записать их через эндпоинт нельзя: иначе ручную калибровку можно было бы выдать
    за автоматически подтверждённую (ADR-0018).
    """

    MANUAL = "manual"
    DETECTED_DIMENSION = "detected_dimension"
    IMPORTED = "imported"


class ScaleScopeKind(StrEnum):
    """На что распространяется калибровка.

    Лист с планом 1:100 и узлом 1:20 — обычное дело, поэтому `region` объявлен сразу.
    На Stage 2A создаётся только `sheet`, но схема локальный масштаб не запрещает:
    модель, исходящая из одного масштаба на лист, не пережила бы первый же такой чертёж.
    """

    SHEET = "sheet"
    REGION = "region"


class LengthUnit(StrEnum):
    """Единица, в которой человек вводит известный размер.

    Внутренний канон — миллиметр: именно в нём проставлены размеры на строительных
    чертежах. Введённое значение сохраняется вместе с единицей — как доказательство
    того, что именно набрал человек.
    """

    MM = "mm"
    CM = "cm"
    M = "m"

    @property
    def to_mm(self) -> int:
        return {LengthUnit.MM: 1, LengthUnit.CM: 10, LengthUnit.M: 1000}[self]


class VerificationState(StrEnum):
    """Состояние проверки человеком."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    DISPUTED = "disputed"


class JobType(StrEnum):
    """Типы заданий.

    Реальны legacy_import и pdf_geometry_extract. Остальные объявлены как контракт и
    не исполняются.
    """

    LEGACY_IMPORT = "legacy_import"
    # Каноническая геометрия страниц PDF (ADR-0016). Ставится и после обычной загрузки PDF,
    # и после импорта пакета: это не распознавание, а чтение размеров страницы.
    PDF_GEOMETRY_EXTRACT = "pdf_geometry_extract"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class JobScope(StrEnum):
    """Кому принадлежит задание.

    Это словарь контракта, а не колонка: область выводится из пары `workspace_id`/`project_id`
    у `Job`. Отдельная колонка была бы производной от той же пары и однажды разошлась бы с ней.

    `system` — обслуживание установки. Такое задание не видно ни одному рабочему пространству
    и доступно только через административный контур.
    """

    SYSTEM = "system"
    WORKSPACE = "workspace"
    PROJECT = "project"


class GeometryStatus(StrEnum):
    """Состояние извлечения канонической геометрии страниц ревизии.

    Относится ко всей ревизии, а не к отдельной странице: если число страниц в PDF не
    совпало с числом листов, доверять нельзя ни одной. Частично извлечённой геометрии не
    бывает (ADR-0016).

    Отдельно от `ProcessingStatus`: тот описывает импорт распознанного пакета и у обычного
    PDF навсегда остаётся `unprocessed`. Одно поле на два независимых процесса означало бы,
    что успех одного стирает отказ другого.
    """

    # Ревизия не PDF: извлекать нечего, и это не отказ.
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    EXTRACTING = "extracting"
    READY = "ready"
    FAILED = "failed"


# Пространство координат распознанного пакета. Канон описан в ADR-0008.
COORDINATE_SPACE_NORMALIZED_TOP_LEFT = "normalized_page_top_left"

# Пространство канонической геометрии страницы PDF (ADR-0016).
#
# Точка PDF (1/72 дюйма), начало в левом верхнем углу, поворот страницы **уже учтён**
# в отображаемых размерах. Поэтому перевод из нормализованных координат — умножение,
# без повторного поворота.
COORDINATE_SPACE_PDF_DISPLAY_POINTS_TOP_LEFT = "pdf_display_points_top_left"
