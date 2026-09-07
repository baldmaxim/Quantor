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


class JobType(StrEnum):
    """Типы заданий.

    Реален только legacy_import. Остальные объявлены в промте 08 как контракт и в Stage 1
    не исполняются.
    """

    LEGACY_IMPORT = "legacy_import"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


# Пространство координат распознанного пакета. Канон описан в ADR-0008.
COORDINATE_SPACE_NORMALIZED_TOP_LEFT = "normalized_page_top_left"
