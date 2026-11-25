"""Пакетный импорт тендерной документации: перечень, привязка загрузки, состояния, права, MCP.

Синтетика: ZIP legacy-v1 собираются здесь же (PDF и blocks.json у позиций разные). Исполнитель
заданий вызывается вручную, как в `test_legacy_import.py`.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.v1.deps import get_optional_tenderhub_client
from app.core.config import Settings, get_settings
from app.core.workspace import DEV_WORKSPACE_ID
from app.db.session import get_session
from app.domain import DocumentKind, JobStatus, JobType, ProjectSource, Role
from app.errors import ErrorCode
from app.integrations.tenderhub import TenderHubClient
from app.models import (
    Document,
    Job,
    Project,
    RecognitionArtifact,
    Region,
    TenderImport,
    TenderImportItem,
    Workspace,
)
from app.services import job_runner, oauth
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from tests.conftest import FakeObjectStorage, _build_api, make_context
from tests.test_legacy_archive import BASE_NAME, PDF_BYTES, blocks_payload
from tests.test_local_auth import _approved_user
from tests.test_mcp import MCP, _call, _rpc, _settings, _token

START = "/api/v1/tender-imports"
CREATE_FORBIDDEN = ErrorCode.TENDER_IMPORT_CREATE_FORBIDDEN.value
OCR_CONFLICT = ErrorCode.TENDER_IMPORT_OCR_CONFLICT.value


# ------------------------------------------------------------------------------- пакеты


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Pack:
    """ZIP распознавалки и то, что о нём заявляет перечень."""

    key: str
    filename: str
    pdf: bytes
    blocks: str
    stamp: int = 0

    @property
    def data(self) -> bytes:
        buffer = io.BytesIO()
        moment = (2026, 11, 1 + self.stamp, 12, 0, 0)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in (
                (f"{BASE_NAME}.pdf", self.pdf),
                (f"{BASE_NAME}_blocks.json", self.blocks.encode("utf-8")),
                (f"{BASE_NAME}_results.md", b"### BLOCK #1 [TEXT]: blk_text_1\n\n"),
            ):
                archive.writestr(zipfile.ZipInfo(name, date_time=moment), payload)
        return buffer.getvalue()

    def rebuilt(self) -> Pack:
        """Тот же комплект, но ZIP собран заново: другие временные метки, другой хеш."""
        return Pack(self.key, self.filename, self.pdf, self.blocks, stamp=self.stamp + 1)

    def item(self, **override: Any) -> dict[str, Any]:
        data = self.data
        body: dict[str, Any] = {
            "key": self.key,
            "filename": self.filename,
            "size": len(data),
            "sha256": _sha(data),
            "pdf_sha256": _sha(self.pdf),
            "blocks_sha256": _sha(self.blocks.encode("utf-8")),
        }
        body.update(override)
        return body


def make_pack(key: str, *, variant: str = "", blocks: str | None = None) -> Pack:
    text = blocks if blocks is not None else json.dumps(blocks_payload(), ensure_ascii=False)
    return Pack(key, f"{key}.zip", PDF_BYTES + variant.encode(), text)


def other_blocks() -> str:
    """Другое распознавание тех же страниц: иной набор областей."""
    payload = blocks_payload()
    payload["blocks"] = payload["blocks"][:1]
    return json.dumps(payload, ensure_ascii=False)


async def _project(api: AsyncClient, name: str = "Объект импорта") -> str:
    response = await api.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _start(api: AsyncClient, project_id: str, packs: list[Pack]) -> httpx.Response:
    return await api.post(
        START, json={"project_id": project_id, "items": [pack.item() for pack in packs]}
    )


async def _send(
    api: AsyncClient, project_id: str, import_id: str, pack: Pack, *, data: bytes | None = None
) -> httpx.Response:
    return await api.post(
        f"/api/v1/projects/{project_id}/uploads",
        files={"file": (pack.filename, data if data is not None else pack.data, "application/zip")},
        data={"tender_import_id": import_id, "tender_import_item": pack.key},
    )


async def _run_jobs(session: AsyncSession, storage: FakeObjectStorage) -> None:
    """Выполняет все поставленные задания импорта пакетов."""
    queued = (
        (
            await session.execute(
                select(Job).where(
                    Job.job_type == JobType.LEGACY_IMPORT, Job.status == JobStatus.QUEUED
                )
            )
        )
        .scalars()
        .all()
    )
    for job in queued:
        await job_runner.execute_legacy_import(
            session, job, storage=storage, settings=get_settings()
        )
        await session.commit()


def _states(body: dict[str, Any]) -> dict[str, str]:
    return {item["key"]: item["state"] for item in body["items"]}


async def _status(api: AsyncClient, import_id: str) -> dict[str, Any]:
    response = await api.get(f"{START}/{import_id}")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


# ------------------------------------------------------------------------------- основной путь


async def test_two_packs_to_existing_project(
    api: AsyncClient, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    packs = [make_pack("a", variant="A"), make_pack("b", variant="B")]

    started = await _start(api, project_id, packs)
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["created"] is True and body["matched_by"] == "project_id"
    assert body["summary"] == {
        "total": 2,
        "pending": 2,
        "received": 0,
        "imported": 0,
        "failed": 0,
        "conflict": 0,
    }
    assert body["to_upload"] == ["a", "b"] and body["complete"] is False
    assert body["project_url"].endswith(f"/projects/{project_id}")
    assert body["upload"] == {
        "method": "POST",
        "path": f"/api/v1/projects/{project_id}/uploads",
        "file_field": "file",
        "fields": {"tender_import_id": body["import_id"]},
        "item_field": "tender_import_item",
    }

    for pack in packs:
        sent = await _send(api, project_id, body["import_id"], pack)
        assert sent.status_code == 201, sent.text
    received = await _status(api, body["import_id"])
    assert _states(received) == {"a": "received", "b": "received"}
    assert received["to_upload"] == [] and received["complete"] is False

    await _run_jobs(db_session, fake_storage)

    done = await _status(api, body["import_id"])
    assert _states(done) == {"a": "imported", "b": "imported"}
    assert done["complete"] is True and done["created"] is False
    for item in done["items"]:
        assert item["pdf_revision_id"] and item["document_id"] and item["job_status"] == "succeeded"
        assert item["received_at"] is not None


async def test_repeat_start_keeps_accepted_and_refreshes_pending(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    project_id = await _project(api)
    a, b = make_pack("a", variant="A"), make_pack("b", variant="B")
    first = (await _start(api, project_id, [a, b])).json()
    assert (await _send(api, project_id, first["import_id"], a)).status_code == 201

    # ZIP пересобраны: хеши и размеры другие, комплект (PDF и blocks.json) тот же.
    a2, b2 = a.rebuilt(), b.rebuilt()
    assert a2.item()["sha256"] != a.item()["sha256"]
    again = await _start(api, project_id, [a2, b2])

    assert again.status_code == 200, again.text
    body = again.json()
    assert body["import_id"] == first["import_id"] and body["created"] is False
    by_key = {item["key"]: item for item in body["items"]}
    assert by_key["a"]["state"] == "received" and by_key["a"]["sha256"] == a.item()["sha256"]
    assert by_key["b"]["state"] == "pending" and by_key["b"]["sha256"] == b2.item()["sha256"]
    assert body["to_upload"] == ["b"]
    assert (await _send(api, project_id, body["import_id"], b2)).status_code == 201
    assert (await db_session.scalar(select(func.count()).select_from(TenderImport))) == 1


async def test_item_order_and_content_key_do_not_depend_on_order(api: AsyncClient) -> None:
    project_id = await _project(api)
    a, b = make_pack("a", variant="A"), make_pack("b", variant="B")
    first = (await _start(api, project_id, [a, b])).json()
    second = await _start(api, project_id, [b, a])
    assert second.status_code == 200 and second.json()["import_id"] == first["import_id"]


async def test_start_validation_happens_before_anything(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    project_id = await _project(api)
    pack = make_pack("a")
    cases: list[dict[str, Any]] = [
        {"project_id": project_id, "items": []},
        {"items": [pack.item()]},
        {"project_id": project_id, "tenderhub_id": "t-1", "items": [pack.item()]},
        {"project_id": project_id, "items": [pack.item(), pack.item()]},
        {"project_id": project_id, "items": [pack.item(filename="a.pdf")]},
        {"project_id": project_id, "items": [pack.item(filename="dir/a.zip")]},
        {"project_id": project_id, "items": [pack.item(sha256="abc")]},
        {"project_id": project_id, "items": [pack.item(size=0)]},
        {"project_id": project_id, "items": [pack.item(size=2**50)]},
    ]
    for body in cases:
        response = await api.post(START, json=body)
        assert response.status_code == 422, (body, response.text)
    assert (await db_session.scalar(select(func.count()).select_from(TenderImport))) == 0


async def test_unknown_project_is_404(api: AsyncClient) -> None:
    response = await api.post(
        START, json={"project_id": str(uuid.uuid4()), "items": [make_pack("a").item()]}
    )
    assert response.status_code == 404


# ------------------------------------------------------------------------------- параллельность


@asynccontextmanager
async def _parallel_api(
    db_engine: AsyncEngine, db_session: AsyncSession, storage: FakeObjectStorage
) -> AsyncIterator[AsyncClient]:
    """Клиент, у которого каждый запрос идёт в своей сессии: так видны настоящие блокировки."""
    app, client = _build_api(db_session, storage, context=make_context())
    factory = async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)

    async def per_request() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = per_request
    try:
        async with client as active:
            yield active
    finally:
        app.dependency_overrides.clear()


async def test_parallel_start_gives_one_import(
    db_engine: AsyncEngine, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    async with _parallel_api(db_engine, db_session, fake_storage) as api:
        project_id = await _project(api)
        packs = [make_pack("a", variant="A"), make_pack("b", variant="B")]
        first, second = await asyncio.gather(
            _start(api, project_id, packs), _start(api, project_id, packs)
        )

    assert sorted([first.status_code, second.status_code]) == [200, 201]
    assert first.json()["import_id"] == second.json()["import_id"]
    assert (await db_session.scalar(select(func.count()).select_from(TenderImport))) == 1
    assert (await db_session.scalar(select(func.count()).select_from(TenderImportItem))) == 2


async def test_lost_response_and_parallel_upload_make_one_revision(
    db_engine: AsyncEngine, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    async with _parallel_api(db_engine, db_session, fake_storage) as api:
        project_id = await _project(api)
        a, b = make_pack("a", variant="A"), make_pack("b", variant="B")
        body = (await _start(api, project_id, [a, b])).json()

        # Две одновременные загрузки одной позиции.
        one, two = await asyncio.gather(
            _send(api, project_id, body["import_id"], a),
            _send(api, project_id, body["import_id"], a),
        )
        assert sorted([one.status_code, two.status_code]) == [200, 201], (one.text, two.text)
        assert one.json()["revision"]["id"] == two.json()["revision"]["id"]
        assert [one.json()["is_duplicate"], two.json()["is_duplicate"]].count(True) == 1

        # Потерянный ответ: клиент шлёт ту же позицию ещё раз - даже пересобранным ZIP.
        again = await _send(api, project_id, body["import_id"], a.rebuilt())
        assert again.status_code == 200
        assert again.json()["is_duplicate"] is True
        assert again.json()["revision"]["id"] == one.json()["revision"]["id"]
        assert again.json()["job"]["id"] == one.json()["job"]["id"]

    packages = await db_session.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.document_kind == DocumentKind.RECOGNIZED_PACKAGE)
    )
    assert packages == 1
    assert (await db_session.scalar(select(func.count()).select_from(Job))) == 1


# ------------------------------------------------------------------------------- проверка передачи


async def test_hash_or_size_mismatch_is_refused_and_object_removed(
    api: AsyncClient, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    pack = make_pack("a", variant="A")
    body = (await _start(api, project_id, [pack])).json()

    flipped = bytearray(pack.data)
    flipped[10] ^= 0x01
    broken = bytes(flipped)
    assert len(broken) == len(pack.data) and broken != pack.data
    wrong_hash = await _send(api, project_id, body["import_id"], pack, data=broken)
    assert wrong_hash.status_code == 422
    assert wrong_hash.json()["detail"]["code"] == ErrorCode.TENDER_IMPORT_HASH_MISMATCH.value

    shorter = await _send(api, project_id, body["import_id"], pack, data=pack.data + b"\x00")
    assert shorter.status_code == 422
    assert shorter.json()["detail"]["code"] == ErrorCode.TENDER_IMPORT_HASH_MISMATCH.value

    assert fake_storage.objects == {}
    assert _states(await _status(api, body["import_id"])) == {"a": "pending"}
    assert (await db_session.scalar(select(func.count()).select_from(Document))) == 0

    # После отказа позицию можно принять правильным файлом.
    assert (await _send(api, project_id, body["import_id"], pack)).status_code == 201


async def test_binding_rules(api: AsyncClient) -> None:
    project_id = await _project(api)
    pack = make_pack("a", variant="A")
    body = (await _start(api, project_id, [pack])).json()
    import_id = body["import_id"]
    url = f"/api/v1/projects/{project_id}/uploads"
    files = {"file": (pack.filename, pack.data, "application/zip")}

    only_id = await api.post(url, files=files, data={"tender_import_id": import_id})
    only_item = await api.post(url, files=files, data={"tender_import_item": "a"})
    assert only_id.status_code == 422 and only_item.status_code == 422

    with_document = await api.post(
        url,
        files=files,
        data={
            "tender_import_id": import_id,
            "tender_import_item": "a",
            "document_id": str(uuid.uuid4()),
        },
    )
    assert with_document.status_code == 404 or with_document.status_code == 422

    not_zip = await api.post(
        url,
        files={"file": ("a.pdf", PDF_BYTES, "application/pdf")},
        data={"tender_import_id": import_id, "tender_import_item": "a"},
    )
    assert not_zip.status_code == 422

    no_item = await api.post(
        url, files=files, data={"tender_import_id": import_id, "tender_import_item": "нет"}
    )
    assert no_item.status_code == 404
    assert no_item.json()["detail"]["code"] == ErrorCode.TENDER_IMPORT_ITEM_NOT_FOUND.value


async def test_plain_uploads_work_as_before(
    api: AsyncClient, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    url = f"/api/v1/projects/{project_id}/uploads"
    zipped = await api.post(url, files={"file": ("p.zip", make_pack("a").data, "application/zip")})
    assert zipped.status_code == 201 and zipped.json()["is_duplicate"] is False
    assert zipped.json()["job"]["status"] == "queued"
    pdf = await api.post(url, files={"file": ("p.pdf", PDF_BYTES + b"x", "application/pdf")})
    assert pdf.status_code == 201
    repeat = await api.post(url, files={"file": ("p.zip", make_pack("a").data, "application/zip")})
    assert repeat.status_code == 201 and repeat.json()["is_duplicate"] is True


# ------------------------------------------------------------------------------- сбой и конфликты


async def test_broken_blocks_fail_only_their_item(
    api: AsyncClient, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    good = make_pack("good", variant="G")
    bad = make_pack("bad", variant="B", blocks="{это не json")
    body = (await _start(api, project_id, [good, bad])).json()
    for pack in (good, bad):
        assert (await _send(api, project_id, body["import_id"], pack)).status_code == 201

    await _run_jobs(db_session, fake_storage)

    done = await _status(api, body["import_id"])
    assert _states(done) == {"good": "imported", "bad": "failed"}
    failed = next(item for item in done["items"] if item["key"] == "bad")
    assert failed["error_code"] and failed["job_status"] == "failed"
    assert done["complete"] is True and done["summary"]["failed"] == 1
    # Отказ по содержимому: повтор с тем же blocks.json бессмыслен, в to_upload его нет.
    assert done["to_upload"] == []


async def _import_plain(
    api: AsyncClient,
    db_session: AsyncSession,
    storage: FakeObjectStorage,
    project_id: str,
    pack: Pack,
) -> None:
    sent = await api.post(
        f"/api/v1/projects/{project_id}/uploads",
        files={"file": (pack.filename, pack.data, "application/zip")},
    )
    assert sent.status_code == 201
    await _run_jobs(db_session, storage)


async def test_ocr_conflict_on_start_and_same_blocks_is_imported(
    api: AsyncClient, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    first = make_pack("first", variant="P")
    await _import_plain(api, db_session, fake_storage, project_id, first)
    regions_before = await db_session.scalar(select(func.count()).select_from(Region))

    # Тот же PDF и те же blocks - досылать не нужно; те же PDF, но другое распознавание - конфликт.
    same = make_pack("same", variant="P")
    different = make_pack("different", variant="P", blocks=other_blocks())
    started = await _start(api, project_id, [same, different])
    body = started.json()
    assert _states(body) == {"same": "imported", "different": "conflict"}
    assert body["to_upload"] == [] and body["complete"] is True
    conflict = next(item for item in body["items"] if item["key"] == "different")
    assert conflict["error_code"] == OCR_CONFLICT and conflict["pdf_revision_id"]
    assert conflict["job_id"] is None

    # Позицию в конфликте догружать нельзя.
    refused = await _send(api, project_id, body["import_id"], different)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == ErrorCode.TENDER_IMPORT_ITEM_DONE.value
    assert (await db_session.scalar(select(func.count()).select_from(Region))) == regions_before


async def test_ocr_conflict_after_the_job(
    api: AsyncClient, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    mine = make_pack("mine", variant="P", blocks=other_blocks())
    body = (await _start(api, project_id, [mine])).json()
    assert _states(body) == {"mine": "pending"}
    assert (await _send(api, project_id, body["import_id"], mine)).status_code == 201

    # Пока задание ждёт очереди, тот же PDF распознан другим пакетом и импортирован раньше.
    other = make_pack("other", variant="P")
    sent = await api.post(
        f"/api/v1/projects/{project_id}/uploads",
        files={"file": ("other.zip", other.data, "application/zip")},
    )
    other_job = await db_session.get(Job, uuid.UUID(sent.json()["job"]["id"]))
    assert other_job is not None
    await job_runner.execute_legacy_import(
        db_session, other_job, storage=fake_storage, settings=get_settings()
    )
    await db_session.commit()
    regions_before = await db_session.scalar(select(func.count()).select_from(Region))

    await _run_jobs(db_session, fake_storage)

    done = await _status(api, body["import_id"])
    assert _states(done) == {"mine": "conflict"}
    item = done["items"][0]
    assert item["error_code"] == OCR_CONFLICT and item["job_status"] == "succeeded"
    assert (await db_session.scalar(select(func.count()).select_from(Region))) == regions_before
    artifacts = (await db_session.execute(select(RecognitionArtifact.sha256))).scalars().all()
    assert _sha(other_blocks().encode("utf-8")) not in artifacts


async def test_pdf_mismatch_marks_item_failed(
    api: AsyncClient, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    real = make_pack("a", variant="REAL")
    claimed = make_pack("a", variant="CLAIMED")
    # Клиент заявил хеш чужого PDF, но ZIP отдаёт верный свой хеш: передача проходит.
    declared = claimed.item(sha256=real.item()["sha256"], size=real.item()["size"])
    body = (await api.post(START, json={"project_id": project_id, "items": [declared]})).json()
    assert (
        await _send(api, project_id, body["import_id"], claimed, data=real.data)
    ).status_code == 201
    await _run_jobs(db_session, fake_storage)

    done = await _status(api, body["import_id"])
    assert _states(done) == {"a": "failed"}
    assert done["items"][0]["error_code"] == ErrorCode.TENDER_IMPORT_PDF_MISMATCH.value


async def _item_job(db_session: AsyncSession, body: dict[str, Any], key: str) -> Job:
    """Задание импорта позиции по ответу статуса."""
    job_id = next(item["job_id"] for item in body["items"] if item["key"] == key)
    job = await db_session.get(Job, uuid.UUID(job_id))
    assert job is not None
    await db_session.refresh(job)
    return job


async def _packages_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.document_kind == DocumentKind.RECOGNIZED_PACKAGE)
        )
        or 0
    )


async def test_retryable_failure_is_resent_with_same_bytes_and_requeued(
    api: AsyncClient, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    pack = make_pack("a", variant="A")
    body = (await _start(api, project_id, [pack])).json()
    import_id = body["import_id"]
    first = await _send(api, project_id, import_id, pack)
    assert first.status_code == 201, first.text
    revision_id = first.json()["revision"]["id"]

    # Задание упало повторяемым отказом (хранилище недоступно).
    code = ErrorCode.STORAGE_UNAVAILABLE.value
    assert code in jobs_service.RETRYABLE_ERROR_CODES
    job = await _item_job(db_session, await _status(api, import_id), "a")
    await jobs_service.start(db_session, job=job)
    await jobs_service.fail(db_session, job=job, error_code=code, error_message="сбой")
    await db_session.commit()
    assert jobs_service.is_retryable(job)

    failed = await _status(api, import_id)
    assert _states(failed) == {"a": "failed"}
    assert failed["items"][0]["error_code"] == code
    assert failed["to_upload"] == ["a"] and failed["complete"] is True

    # Те же байты: дубль по хешу, упавшее задание возвращается в очередь.
    again = await _send(api, project_id, import_id, pack)
    assert again.status_code == 200, again.text
    assert again.json()["is_duplicate"] is True
    assert again.json()["revision"]["id"] == revision_id
    assert again.json()["job"]["id"] == str(job.id)
    assert again.json()["job"]["status"] == "queued"
    await db_session.refresh(job)
    assert job.status is JobStatus.QUEUED and job.error_code is None
    requeued = await _status(api, import_id)
    assert _states(requeued) == {"a": "received"}
    assert requeued["to_upload"] == []

    await _run_jobs(db_session, fake_storage)

    done = await _status(api, import_id)
    assert _states(done) == {"a": "imported"} and done["to_upload"] == []
    assert done["items"][0]["package_revision_id"] == revision_id
    assert await _packages_count(db_session) == 1
    imports = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.job_type == JobType.LEGACY_IMPORT)
    )
    assert imports == 1


async def test_cancelled_job_is_resent_with_rebuilt_zip_as_new_package(
    api: AsyncClient, db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    project_id = await _project(api)
    pack = make_pack("a", variant="A")
    body = (await _start(api, project_id, [pack])).json()
    import_id = body["import_id"]
    first = await _send(api, project_id, import_id, pack)
    assert first.status_code == 201, first.text
    old_revision_id = first.json()["revision"]["id"]

    job = await _item_job(db_session, await _status(api, import_id), "a")
    await jobs_service.cancel(db_session, job=job)
    await db_session.commit()

    cancelled = await _status(api, import_id)
    assert _states(cancelled) == {"a": "failed"}
    assert cancelled["items"][0]["job_status"] == "cancelled"
    assert cancelled["to_upload"] == ["a"]

    # Тот же комплект, ZIP собран заново (другие метки времени): повторный start тем же
    # перечнем обновляет хеш и размер позиции в том же импорте.
    rebuilt = pack.rebuilt()
    assert rebuilt.data != pack.data
    restarted = await _start(api, project_id, [rebuilt])
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["import_id"] == import_id and restarted.json()["created"] is False
    refreshed = restarted.json()["items"][0]
    assert refreshed["sha256"] == rebuilt.item()["sha256"]
    assert refreshed["size"] == rebuilt.item()["size"]
    assert restarted.json()["to_upload"] == ["a"]

    sent = await _send(api, project_id, import_id, rebuilt)
    assert sent.status_code == 201, sent.text
    assert sent.json()["is_duplicate"] is False
    assert sent.json()["revision"]["id"] != old_revision_id
    assert sent.json()["job"]["id"] != str(job.id)

    await _run_jobs(db_session, fake_storage)

    done = await _status(api, import_id)
    assert _states(done) == {"a": "imported"} and done["to_upload"] == []
    assert done["items"][0]["package_revision_id"] == sent.json()["revision"]["id"]
    # Ожидаемо два документа-пакета: отменённый прежний и новый.
    assert await _packages_count(db_session) == 2


# ------------------------------------------------------------------------------- изоляция


async def test_isolation_between_workspaces_and_projects(
    api: AsyncClient, db_session: AsyncSession, second_workspace: Workspace
) -> None:
    foreign_project = await projects_service.create_project(
        db_session, workspace_id=second_workspace.id, name="Чужой"
    )
    pack = make_pack("a")
    foreign = TenderImport(
        workspace_id=second_workspace.id,
        project_id=foreign_project.id,
        matched_by="project_id",
        content_key="0" * 64,
    )
    db_session.add(foreign)
    await db_session.flush()
    db_session.add(
        TenderImportItem(
            import_id=foreign.id,
            item_key="a",
            filename=pack.filename,
            size=10,
            sha256="1" * 64,
            pdf_sha256="2" * 64,
            blocks_sha256="3" * 64,
        )
    )
    await db_session.commit()

    missing = await api.get(f"{START}/{foreign.id}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == ErrorCode.TENDER_IMPORT_NOT_FOUND.value

    mine = await _project(api, "Свой")
    other_mine = await _project(api, "Свой второй")
    upload = await _send(api, mine, str(foreign.id), pack)
    assert upload.status_code == 404

    body = (await _start(api, mine, [pack])).json()
    wrong_path = await _send(api, other_mine, body["import_id"], pack)
    assert wrong_path.status_code == 404
    assert wrong_path.json()["detail"]["code"] == ErrorCode.TENDER_IMPORT_NOT_FOUND.value


# ------------------------------------------------------------------------------- права и TenderHUB

TENDER: dict[str, Any] = {
    "id": "tender-0001",
    "tender_number": "ТН-0042",
    "title": "ЖК «Северный»",
    "version": 1,
}


def _hub(calls: list[str], tenders: dict[str, dict[str, Any]] | None = None) -> TenderHubClient:
    known = tenders or {str(TENDER["id"]): TENDER}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        tender = known.get(request.url.path.split("/")[-2])
        if tender is None:
            return httpx.Response(404, json={"code": "not found"})
        return httpx.Response(200, json={"data": tender})

    return TenderHubClient(
        Settings.model_validate({"tenderhub_api_token": "thk_test"}),
        transport=httpx.MockTransport(handler),
    )


@asynccontextmanager
async def _token_client(
    db_session: AsyncSession,
    storage: FakeObjectStorage,
    token: str,
    *,
    hub: TenderHubClient | None = None,
) -> AsyncIterator[AsyncClient]:
    app, client = _build_api(db_session, storage, context=None, settings=_settings())

    async def override_hub() -> AsyncIterator[TenderHubClient | None]:
        yield hub

    app.dependency_overrides[get_optional_tenderhub_client] = override_hub
    client.headers["Authorization"] = f"Bearer {token}"
    try:
        async with client as active:
            yield active
    finally:
        app.dependency_overrides.clear()


async def _tenders_count(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(Project)) or 0)


def _by_tender(pack: Pack, tender_id: str = "tender-0001") -> dict[str, Any]:
    return {"tenderhub_id": tender_id, "items": [pack.item()]}


async def test_upload_token_works_on_existing_project_but_cannot_create(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    project = await projects_service.create_project(
        db_session, workspace_id=DEV_WORKSPACE_ID, name="Готовый объект"
    )
    await db_session.commit()
    token = await _token(build_api, ["upload"])
    calls: list[str] = []
    pack = make_pack("a")
    async with _token_client(db_session, fake_storage, token, hub=_hub(calls)) as client:
        ok = await client.post(START, json={"project_id": str(project.id), "items": [pack.item()]})
        assert ok.status_code == 201, ok.text

        denied = await client.post(START, json=_by_tender(pack))
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == CREATE_FORBIDDEN
    assert await _tenders_count(db_session) == 1


async def test_upload_token_cannot_start_by_unknown_id_even_if_tender_number_exists(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    # Объект с тем же номером тендера, но другим external_id.
    await projects_service.create_project(
        db_session,
        workspace_id=DEV_WORKSPACE_ID,
        name="Прежняя версия",
        source=ProjectSource.TENDERHUB,
        external_id="tender-0000",
        external_ref=str(TENDER["tender_number"]),
    )
    await db_session.commit()
    token = await _token(build_api, ["upload"])
    calls: list[str] = []
    async with _token_client(db_session, fake_storage, token, hub=_hub(calls)) as client:
        denied = await client.post(START, json=_by_tender(make_pack("a")))
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == CREATE_FORBIDDEN
    assert calls == []
    assert await _tenders_count(db_session) == 1
    assert (await db_session.scalar(select(func.count()).select_from(TenderImport))) == 0


async def test_tender_import_scope_creates_project_and_reuses_it(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    token = await _token(build_api, ["upload", "tender_import"])
    calls: list[str] = []
    other_version = {**TENDER, "id": "tender-0002", "version": 2}
    hub = _hub(calls, {"tender-0001": TENDER, "tender-0002": other_version})
    pack = make_pack("a")
    async with _token_client(db_session, fake_storage, token, hub=hub) as client:
        first = await client.post(START, json=_by_tender(pack))
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["matched_by"] == "created" and body["tenderhub_id"] == "tender-0001"
        assert body["project_name"] == "ТН-0042 · ЖК «Северный»"

        # Тот же тендер: объект найден по id, TenderHUB не нужен; тот же комплект - тот же импорт.
        calls.clear()
        second = await client.post(START, json=_by_tender(pack))
        assert second.status_code == 200
        assert second.json()["import_id"] == body["import_id"]
        assert second.json()["matched_by"] == "created"
        assert calls == []

        # Другая версия того же номера: тот же объект, но новый комплект.
        other = make_pack("b", variant="B")
        third = await client.post(START, json=_by_tender(other, "tender-0002"))
        assert third.status_code == 201, third.text
        assert third.json()["project_id"] == body["project_id"]
        assert third.json()["matched_by"] == "tender_number"
        assert await _tenders_count(db_session) == 1

        # Загрузка по ссылке из ответа идёт тем же токеном.
        sent = await client.post(
            body["upload"]["path"],
            files={"file": (pack.filename, pack.data, "application/zip")},
            data={**body["upload"]["fields"], "tender_import_item": "a"},
        )
        assert sent.status_code == 201, sent.text


async def test_unknown_tender_and_disabled_integration(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    token = await _token(build_api, ["upload", "tender_import"])
    pack = make_pack("a")
    async with _token_client(db_session, fake_storage, token, hub=_hub([])) as client:
        unknown = await client.post(START, json=_by_tender(pack, "нет-такого"))
        assert unknown.status_code == 404
        assert unknown.json()["detail"]["code"] == ErrorCode.TENDERHUB_TENDER_NOT_FOUND.value
    async with _token_client(db_session, fake_storage, token, hub=None) as client:
        off = await client.post(START, json=_by_tender(pack))
        assert off.status_code == 503
        assert off.json()["detail"]["code"] == ErrorCode.TENDERHUB_DISABLED.value
    assert await _tenders_count(db_session) == 0


async def test_empty_items_do_not_call_tenderhub(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    token = await _token(build_api, ["upload", "tender_import"])
    calls: list[str] = []
    async with _token_client(db_session, fake_storage, token, hub=_hub(calls)) as client:
        response = await client.post(START, json={"tenderhub_id": "tender-0001", "items": []})
        assert response.status_code == 422
    assert calls == [] and await _tenders_count(db_session) == 0


async def test_viewer_owner_cannot_create_with_tender_import_scope(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    await _approved_user(db_session, role=Role.VIEWER)
    token = await _token(build_api, ["upload", "tender_import"])
    calls: list[str] = []
    async with _token_client(db_session, fake_storage, token, hub=_hub(calls)) as client:
        response = await client.post(START, json=_by_tender(make_pack("a")))
        assert response.status_code == 403
    assert calls == [] and await _tenders_count(db_session) == 0


async def test_read_token_cannot_start_but_can_read_status(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    api: AsyncClient,
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    project_id = await _project(api)
    body = (await _start(api, project_id, [make_pack("a")])).json()
    token = await _token(build_api, ["read"])
    async with _token_client(db_session, fake_storage, token) as client:
        denied = await client.post(
            START, json={"project_id": project_id, "items": [make_pack("a").item()]}
        )
        assert denied.status_code == 403
        status = await client.get(f"{START}/{body['import_id']}")
        assert status.status_code == 200


def test_oauth_cannot_grant_tender_import() -> None:
    assert "tender_import" not in oauth.OAUTH_SCOPES


# ------------------------------------------------------------------------------- MCP


async def test_mcp_tools_match_http_contract(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    await _approved_user(db_session, role=Role.ENGINEER)
    project = await projects_service.create_project(
        db_session, workspace_id=DEV_WORKSPACE_ID, name="Объект MCP"
    )
    await db_session.commit()
    token = await _token(build_api, ["upload"])
    pack = make_pack("a")
    async with _token_client(db_session, fake_storage, token) as client:
        listed = (await client.post(MCP, json=_rpc("tools/list"))).json()["result"]["tools"]
        names = {tool["name"] for tool in listed}
        assert {"start_tender_import", "tender_import_status"} <= names
        start = next(tool for tool in listed if tool["name"] == "start_tender_import")
        assert start["annotations"]["readOnlyHint"] is False
        assert start["inputSchema"]["required"] == ["items"]

        both = await _call(
            client,
            "start_tender_import",
            {"project": "Объект MCP", "tenderhub_id": "t", "items": [pack.item()]},
        )
        assert both["isError"] is True

        started = await _call(
            client, "start_tender_import", {"project": "Объект MCP", "items": [pack.item()]}
        )
        assert started["isError"] is False, started
        data = started["structuredContent"]
        assert data["project_id"] == str(project.id) and data["created"] is True
        assert "ждут загрузки 1" in started["content"][0]["text"]

        status = await _call(client, "tender_import_status", {"import_id": data["import_id"]})
        assert status["isError"] is False
        http = (await client.get(f"{START}/{data['import_id']}")).json()
        assert status["structuredContent"] == http
        assert {**data, "created": False} == http

        bad = await _call(client, "tender_import_status", {"import_id": "не-uuid"})
        assert bad["isError"] is True
