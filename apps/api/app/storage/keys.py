"""Построение ключей объектов.

Имя файла в ключ не попадает: пользовательские имена содержат кириллицу, пробелы, точки и
скобки, а иногда и то, что нельзя класть в путь. Ключ строится из UUID, а имя хранится
метаданными объекта и колонкой в базе (ADR-0002).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Final

# Расширение оставляем в ключе: оно помогает при разборе бакета руками и не несёт риска.
_EXTENSION_RE: Final = re.compile(r"^[a-z0-9]{1,12}$")
_MAX_METADATA_FILENAME = 200


def extension_of(filename: str) -> str:
    """Безопасное расширение файла в нижнем регистре или пустая строка."""
    _, _, tail = filename.rpartition(".")
    candidate = tail.lower()
    return candidate if candidate and _EXTENSION_RE.match(candidate) else ""


def revision_key(revision_id: uuid.UUID, filename: str) -> str:
    """Ключ исходного файла ревизии."""
    extension = extension_of(filename)
    suffix = f".{extension}" if extension else ""
    return f"revisions/{revision_id}/source{suffix}"


def artifact_key(revision_id: uuid.UUID, artifact_id: uuid.UUID, filename: str) -> str:
    """Ключ артефакта распознавания внутри ревизии."""
    extension = extension_of(filename)
    suffix = f".{extension}" if extension else ""
    return f"revisions/{revision_id}/artifacts/{artifact_id}{suffix}"


def upload_key(upload_id: uuid.UUID, filename: str) -> str:
    """Ключ временно принятого файла до того, как решено, какой ревизией он станет."""
    extension = extension_of(filename)
    suffix = f".{extension}" if extension else ""
    return f"uploads/{upload_id}{suffix}"


def display_filename(filename: str) -> str:
    """Имя для показа и для заголовка скачивания.

    Убирает управляющие символы и разделители пути, но сохраняет кириллицу и пробелы:
    пользователь должен получить файл под тем же именем, под которым его загрузил.
    """
    normalized = unicodedata.normalize("NFC", filename).strip()
    normalized = normalized.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    cleaned = "".join(ch for ch in normalized if unicodedata.category(ch)[0] != "C")
    cleaned = cleaned.strip(" .")
    return cleaned[:_MAX_METADATA_FILENAME] or "file"
