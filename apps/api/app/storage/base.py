"""Контракт объектного хранилища.

Бизнес-код обращается только к этому протоколу: локально за ним MinIO, в проде —
Yandex Object Storage или другое S3-совместимое хранилище (см. docs/adr/0002).

Stage 1 / промт 02 объявляет лишь проверку доступности. Потоковая загрузка, presigned URL,
stat и удаление добавляются в промте 03 — вместе с первыми потребителями.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStorage(Protocol):
    """Минимальный контракт хранилища бинарных артефактов."""

    @property
    def bucket(self) -> str:
        """Бакет, в котором живут артефакты портала."""
        ...

    async def check_available(self) -> None:
        """Проверяет доступность бакета. Бросает исключение, если хранилище недоступно."""
        ...
