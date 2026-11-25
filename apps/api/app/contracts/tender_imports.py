"""Контракты пакетного импорта тендерной документации.

Клиент (дашборд, MCP-агент) присылает перечень ZIP-пакетов распознавалки с их хешами, портал
отвечает, что уже есть, а что надо догрузить обычным приёмом файлов
(`POST /projects/{id}/uploads` с полями `tender_import_id` и `tender_import_item`).
Файлы через этот контракт не передаются.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_ITEMS = 500
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ItemState = Literal["pending", "received", "imported", "failed", "conflict"]
MatchedBy = Literal["project_id", "tenderhub_id", "tender_number", "created"]


def _sha256(value: str) -> str:
    lowered = value.strip().lower()
    if not SHA256_RE.match(lowered):
        raise ValueError("нужна строка из 64 шестнадцатеричных знаков (SHA-256)")
    return lowered


class TenderImportItemIn(BaseModel):
    """Позиция перечня: один ZIP распознавалки (PDF + blocks.json) и его хеши."""

    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, Field(min_length=1, max_length=200, description="Ключ позиции в перечне")]
    filename: Annotated[str, Field(min_length=1, max_length=255, description="Имя .zip без пути")]
    size: Annotated[int, Field(ge=1, description="Размер ZIP, байт")]
    sha256: Annotated[str, Field(description="SHA-256 ZIP: проверка передачи")]
    pdf_sha256: Annotated[str, Field(description="SHA-256 PDF внутри ZIP")]
    blocks_sha256: Annotated[str, Field(description="SHA-256 blocks.json внутри ZIP")]

    @field_validator("sha256", "pdf_sha256", "blocks_sha256")
    @classmethod
    def _hash(cls, value: str) -> str:
        return _sha256(value)

    @field_validator("filename")
    @classmethod
    def _zip_name(cls, value: str) -> str:
        if "/" in value or "\\" in value:
            raise ValueError("имя файла без пути")
        if not value.lower().endswith(".zip"):
            raise ValueError("имя файла должно оканчиваться на .zip")
        return value


class TenderImportStart(BaseModel):
    """Запуск пакетного импорта: объект (по id или по тендеру TenderHUB) и перечень позиций."""

    model_config = ConfigDict(extra="forbid")

    tenderhub_id: Annotated[str | None, Field(default=None, min_length=1, max_length=64)] = None
    project_id: UUID | None = None
    items: Annotated[list[TenderImportItemIn], Field(min_length=1, max_length=MAX_ITEMS)]

    @model_validator(mode="after")
    def _one_target(self) -> Self:
        if (self.tenderhub_id is None) == (self.project_id is None):
            raise ValueError("укажите ровно одно из полей: tenderhub_id или project_id")
        keys = [item.key for item in self.items]
        if len(set(keys)) != len(keys):
            raise ValueError("ключи позиций в перечне должны быть уникальны")
        return self


class TenderImportSummary(BaseModel):
    total: int
    pending: int
    received: int
    imported: int
    failed: int
    conflict: int


class TenderImportUpload(BaseModel):
    """Как догружать файлы: обычный приём файлов с двумя дополнительными полями формы."""

    method: Literal["POST"]
    path: str
    file_field: str
    fields: dict[str, str]
    item_field: str


class TenderImportItemRead(BaseModel):
    key: str
    filename: str
    size: int
    sha256: str
    pdf_sha256: str
    blocks_sha256: str
    state: ItemState
    job_id: UUID | None
    job_status: str | None
    package_revision_id: UUID | None
    document_id: UUID | None
    pdf_revision_id: UUID | None
    error_code: str | None
    error_message: str | None
    received_at: datetime | None


class TenderImportRead(BaseModel):
    import_id: UUID
    project_id: UUID
    project_name: str
    project_url: str
    tenderhub_id: str | None
    matched_by: MatchedBy
    # True - импорт создан этим вызовом; False - найден существующий с тем же комплектом.
    created: bool
    # Нет позиций «ожидает загрузки» и «принято, импорт идёт».
    complete: bool
    summary: TenderImportSummary
    to_upload: list[str]
    upload: TenderImportUpload
    items: list[TenderImportItemRead]
