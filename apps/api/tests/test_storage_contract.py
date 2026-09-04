"""Контракт объектного хранилища и построение ключей.

База данных и MinIO здесь не нужны: проверяется сам договор, которому обязаны следовать
все реализации.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from app.storage.base import ObjectNotFoundError, ObjectStorage
from app.storage.keys import artifact_key, display_filename, extension_of, revision_key
from tests.conftest import FakeObjectStorage

RUSSIAN_NAME = "01-03-00-01-12_ПД-00260560-АР.pdf"


def test_fake_storage_satisfies_protocol(fake_storage: FakeObjectStorage) -> None:
    assert isinstance(fake_storage, ObjectStorage)


class TestKeys:
    def test_key_does_not_contain_user_filename(self) -> None:
        revision_id = uuid.uuid4()

        key = revision_key(revision_id, RUSSIAN_NAME)

        assert str(revision_id) in key
        assert "ПД" not in key
        assert key.endswith(".pdf")

    def test_key_survives_filename_without_extension(self) -> None:
        key = revision_key(uuid.uuid4(), "чертёж без расширения")

        assert key.endswith("/source")

    def test_suspicious_extension_is_dropped(self) -> None:
        # Расширение попадает в ключ, поэтому в него нельзя пускать что попало.
        assert extension_of("файл.pdf/../../etc/passwd") == ""
        assert extension_of("архив.ZIP") == "zip"
        assert extension_of("без_точки") == ""

    def test_artifact_keys_are_unique_per_artifact(self) -> None:
        revision_id = uuid.uuid4()

        first = artifact_key(revision_id, uuid.uuid4(), "blocks.json")
        second = artifact_key(revision_id, uuid.uuid4(), "blocks.json")

        assert first != second
        assert first.startswith(f"revisions/{revision_id}/artifacts/")


class TestDisplayFilename:
    def test_keeps_cyrillic_and_spaces(self) -> None:
        assert display_filename("План 3 этажа.pdf") == "План 3 этажа.pdf"

    def test_strips_path_separators(self) -> None:
        assert display_filename("../../etc/passwd") == "passwd"
        assert display_filename(r"C:\Windows\система.pdf") == "система.pdf"

    def test_strips_control_characters(self) -> None:
        assert display_filename("отчёт\x00\x1f.pdf") == "отчёт.pdf"

    def test_never_returns_empty(self) -> None:
        assert display_filename("   ...   ") == "file"


class TestFakeStorageBehaviour:
    async def test_put_stream_computes_hash_and_size(self, fake_storage: FakeObjectStorage) -> None:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"first-"
            yield b"second"

        stored = await fake_storage.put_stream(
            "revisions/x/source.pdf",
            chunks(),
            content_type="application/pdf",
            original_filename=RUSSIAN_NAME,
        )

        assert stored.size == len(b"first-second")
        assert len(stored.sha256) == 64
        assert fake_storage.objects[stored.key] == b"first-second"

    async def test_original_filename_is_preserved_in_metadata(
        self, fake_storage: FakeObjectStorage
    ) -> None:
        await fake_storage.put_bytes(
            "revisions/x/source.pdf",
            b"data",
            content_type="application/pdf",
            original_filename=RUSSIAN_NAME,
        )

        stat = await fake_storage.stat("revisions/x/source.pdf")

        assert stat.metadata["original-filename"] == RUSSIAN_NAME

    async def test_missing_object_raises_not_found(self, fake_storage: FakeObjectStorage) -> None:
        with pytest.raises(ObjectNotFoundError):
            await fake_storage.stat("revisions/нет/source.pdf")

        with pytest.raises(ObjectNotFoundError):
            await fake_storage.presigned_get_url("revisions/нет/source.pdf", expires_in=60)
