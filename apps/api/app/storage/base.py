"""Контракт объектного хранилища.

Бизнес-код обращается только к этому протоколу: локально за ним MinIO, в проде —
Yandex Object Storage или другое S3-совместимое хранилище (ADR-0002).

Правила, обязательные для любой реализации:

- загрузка и выгрузка потоковые, потребление памяти ограничено вне зависимости от размера файла;
- ключ объекта строится из UUID, имя файла в путь не попадает и хранится как метаданные;
- SHA-256 считается на лету во время приёма файла;
- удаление доступно только через явный вызов, случайной перезаписью объект не теряется.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Результат приёма файла в хранилище."""

    key: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ObjectStat:
    """Метаданные объекта без чтения содержимого."""

    key: str
    size: int
    content_type: str | None
    last_modified: datetime | None
    metadata: Mapping[str, str]


class ObjectNotFoundError(Exception):
    """Объекта с таким ключом в хранилище нет."""


class StorageUnavailableError(Exception):
    """Хранилище недоступно: сеть, креды или бакет."""


@runtime_checkable
class ObjectStorage(Protocol):
    """Минимальный контракт хранилища бинарных артефактов."""

    @property
    def bucket(self) -> str:
        """Бакет, в котором живут артефакты портала."""
        ...

    async def check_available(self) -> None:
        """Проверяет доступность бакета. Бросает StorageUnavailableError, если недоступен."""
        ...

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str,
        original_filename: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        """Принимает поток и кладёт его в хранилище, считая размер и SHA-256 по пути."""
        ...

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        original_filename: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        """Кладёт небольшой объект целиком — для JSON и Markdown из распознанного пакета."""
        ...

    def iter_stream(self, key: str, *, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        """Читает объект кусками. Бросает ObjectNotFoundError, если объекта нет."""
        ...

    async def stat(self, key: str) -> ObjectStat:
        """Метаданные объекта. Бросает ObjectNotFoundError, если объекта нет."""
        ...

    async def delete(self, key: str) -> None:
        """Удаляет объект. Вызывается только явно, из сервисного слоя."""
        ...

    async def presigned_get_url(
        self, key: str, *, expires_in: int, download_filename: str | None = None
    ) -> str:
        """Ссылка на скачивание напрямую из хранилища, минуя API."""
        ...
