"""Перечисления предметной области.

Хранятся как строки с CHECK-ограничением, а не как нативные типы PostgreSQL: добавить значение
в молодую схему приходится часто, и ALTER TYPE в миграциях этому только мешает.
"""

from __future__ import annotations

from enum import StrEnum


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
