"""Паспорт листа (ADR-0043, С1): задание разбора, upsert, API правки и подтверждения.

Только синтетика: текстовый слой страниц подменяется (подпроцесс разбора в этих тестах заменён
вызовом в процессе), настоящий pypdf работает на «битом» файле. Сам подпроцесс - в
`test_sheet_passport_process.py`.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.domain import DocumentKind, JobStatus, JobType, Role
from app.main import create_app
from app.models import Document, DocumentRevision, Job, SheetPassport, Workspace
from app.services import jobs as jobs_service
from app.services import sheet_passports as passports_service
from app.services.consistency.passport_process import REASON_FAILED, PassportParseError
from app.services.consistency.sheet_passport import (
    PageInput,
    PassportCandidate,
    extract_pdf_pages,
    parse_page,
)
from app.worker.registry import handler_for, supported_types
from tests.conftest import FakeObjectStorage, clean_settings, make_context

PLAN_PDF = "АР план.pdf"
SCHEME_PDF = "ИОС2 схема.pdf"
BROKEN_PDF = "Битый.pdf"
PLAN_STAMP = "\n".join(
    [
        "ГИП",
        "План 3 этажа на отм. +9.600",
        "ПД-00000001-12-АР1",
        "Стадия Лист Листов",
        "П 7 40",
        "Разработал",
        "Н.контроль",
    ]
)
SCHEME_STAMP = PLAN_STAMP.replace("АР1", "ИОС2.1").replace(
    "План 3 этажа на отм. +9.600", "Схема В1"
)


def _settings(*, flag: bool = True) -> Settings:
    return clean_settings(
        environment="test", feature_flags="project.consistency=true" if flag else ""
    )


class _Texts:
    """Текстовый слой синтетических файлов: имя файла -> тексты страниц."""

    def __init__(self) -> None:
        self.pages: dict[str, list[str]] = {}


@pytest.fixture
def texts(monkeypatch: pytest.MonkeyPatch) -> _Texts:
    state = _Texts()

    def pages_of(stream: BinaryIO, file_name: str) -> Iterator[PageInput]:
        if file_name not in state.pages:
            yield from extract_pdf_pages(stream, file_name)
            return
        for index, text in enumerate(state.pages[file_name]):
            yield PageInput(page_index=index, text=text, file_name=file_name)

    async def fake(
        path: Path, file_name: str, *, memory_limit_mb: int, timeout_seconds: float
    ) -> list[PassportCandidate]:
        try:
            with path.open("rb") as stream:
                return [parse_page(page) for page in pages_of(stream, file_name)]
        except Exception:
            raise PassportParseError(REASON_FAILED) from None

    monkeypatch.setattr(passports_service, "parse_pdf_in_subprocess", fake)
    state.pages[PLAN_PDF] = [PLAN_STAMP, PLAN_STAMP.replace("7 40", "8 40")]
    state.pages[SCHEME_PDF] = [SCHEME_STAMP]
    return state


async def _project(api: AsyncClient) -> str:
    response = await api.post("/api/v1/projects", json={"name": f"Паспорт {uuid.uuid4().hex[:6]}"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _add_pdf(
    session: AsyncSession,
    storage: FakeObjectStorage,
    project_id: str,
    name: str,
    *,
    kind: DocumentKind = DocumentKind.PDF,
    data: bytes | None = None,
) -> DocumentRevision:
    document = Document(project_id=uuid.UUID(project_id), display_name=name, document_kind=kind)
    session.add(document)
    await session.flush()
    payload = data if data is not None else b"%PDF-1.7\n" + name.encode()
    key = f"test/{uuid.uuid4()}"
    storage.objects[key] = payload
    revision = DocumentRevision(
        document_id=document.id,
        source_filename=name,
        source_mime="application/pdf",
        source_size=len(payload),
        source_sha256=hashlib.sha256(payload + key.encode()).hexdigest(),
        storage_key=key,
    )
    session.add(revision)
    await session.commit()
    return revision


async def _run_job(session: AsyncSession, storage: FakeObjectStorage) -> Job:
    """Один цикл основного исполнителя: захват своего типа и его обработчик."""
    job = await jobs_service.claim(
        session,
        worker_id="passport-test",
        job_types=[JobType.SHEET_PASSPORT_EXTRACT.value],
        lease_seconds=600,
    )
    await session.commit()
    assert job is not None
    handler = handler_for(job.job_type)
    assert handler is not None
    job = await handler(session, job, storage, clean_settings())
    await session.commit()
    return job


async def _extract(
    api: AsyncClient, session: AsyncSession, storage: FakeObjectStorage, project_id: str
) -> Job:
    response = await api.post(f"/api/v1/projects/{project_id}/sheet-passports/extract")
    assert response.status_code == 202, response.text
    job = await _run_job(session, storage)
    assert str(job.id) == response.json()["id"]
    return job


async def _make_stale(session: AsyncSession) -> None:
    """Паспорта разобраны старой версией разборщика: повторный запуск их разбирает заново."""
    await session.execute(update(SheetPassport).values(versions={"parser": "old"}))
    await session.commit()


def _url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/sheet-passports{tail}"


def test_routes_are_in_openapi_and_job_is_registered() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths["/api/v1/projects/{project_id}/sheet-passports"]) == {"get"}
    assert set(paths["/api/v1/projects/{project_id}/sheet-passports/extract"]) == {"post"}
    assert set(paths["/api/v1/projects/{project_id}/sheet-passports/bulk-status"]) == {"post"}
    assert set(paths["/api/v1/projects/{project_id}/sheet-passports/{passport_id}"]) == {"patch"}
    assert JobType.SHEET_PASSPORT_EXTRACT.value in supported_types()


async def test_flag_off_closes_all_routes(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=_settings(flag=False)) as api:
        project_id = str(uuid.uuid4())
        some_id = str(uuid.uuid4())
        responses = [
            await api.post(_url(project_id, "/extract")),
            await api.get(_url(project_id)),
            await api.get(_url(project_id, "/extract-summary")),
            await api.patch(_url(project_id, f"/{some_id}"), json={"title": "x"}),
            await api.post(
                _url(project_id, "/bulk-status"), json={"ids": [some_id], "status": "confirmed"}
            ),
        ]
    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_extract_creates_candidates_and_survives_a_broken_file(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        plan = await _add_pdf(db_session, fake_storage, project_id, PLAN_PDF)
        await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        await _add_pdf(db_session, fake_storage, project_id, BROKEN_PDF, data=b"not a pdf at all")
        # Не PDF в разбор не идёт.
        await _add_pdf(
            db_session, fake_storage, project_id, "Пакет.zip", kind=DocumentKind.RECOGNIZED_PACKAGE
        )

        first = await api.post(_url(project_id, "/extract"))
        assert first.status_code == 202, first.text
        assert first.json()["job_type"] == "sheet_passport_extract"
        # Активное задание возвращается, второе не ставится.
        second = await api.post(_url(project_id, "/extract"))
        assert second.status_code == 202 and second.json()["id"] == first.json()["id"]
        jobs = (await db_session.scalars(select(Job))).all()
        assert [job.job_type for job in jobs] == [JobType.SHEET_PASSPORT_EXTRACT]

        job = await _run_job(db_session, fake_storage)
        assert job.status is JobStatus.SUCCEEDED
        assert job.payload["files_total"] == 3
        assert job.payload["files_parsed"] == 2
        assert job.payload["pages"] == 3
        assert job.payload["created"] == 3
        assert job.payload["error_count"] == 1
        assert [item["file_name"] for item in job.payload["errors"]] == [BROKEN_PDF]
        assert job.payload["versions"]["parser"].startswith("consistency.sheet_passport")

        listing = (await api.get(_url(project_id))).json()
        assert listing["total"] == 3
        order = [(item["file_name"], item["page_index"]) for item in listing["items"]]
        # По файлу и странице: страницы одного файла идут подряд и по возрастанию.
        assert order in (
            [(SCHEME_PDF, 0), (PLAN_PDF, 0), (PLAN_PDF, 1)],
            [(PLAN_PDF, 0), (PLAN_PDF, 1), (SCHEME_PDF, 0)],
        )
        item = next(i for i in listing["items"] if i["page_index"] == 1)
        assert item["revision_id"] == str(plan.id)
        assert item["document_name"] == PLAN_PDF
        assert item["section_mark"] == "АР" and item["stage"] == "П"
        assert item["sheet_kind"] == "floor_plan" and item["status"] == "candidate"
        assert item["sheet_number"] == "8"
        assert item["evidence"]["section_mark"]["source"] == "stamp"
        assert item["versions"]["sections"].startswith("consistency.dict.sections")
        assert item["confirmed_by"] is None

        # Новый запуск после смены версии разборщика - новое задание, строки не множатся.
        await _make_stale(db_session)
        again = await _extract(api, db_session, fake_storage, project_id)
        assert again.payload["created"] == 0 and again.payload["updated"] == 3
        assert (await api.get(_url(project_id))).json()["total"] == 3


async def test_rerun_keeps_confirmed_rows_and_manual_fields(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _add_pdf(db_session, fake_storage, project_id, PLAN_PDF)
        await _extract(api, db_session, fake_storage, project_id)
        items = (await api.get(_url(project_id))).json()["items"]
        first, second = items[0], items[1]

        # Первая страница подтверждена, у второй вручную правлен раздел.
        confirmed = await api.patch(
            _url(project_id, f"/{first['id']}"), json={"status": "confirmed"}
        )
        assert confirmed.status_code == 200, confirmed.text
        edited = await api.patch(_url(project_id, f"/{second['id']}"), json={"section_mark": "КР"})
        assert edited.status_code == 200, edited.text

        # Разбор теперь видит другое: раздел ИОС2, номер листа 9, схема.
        changed = SCHEME_STAMP.replace("7 40", "9 40")
        texts.pages[PLAN_PDF] = [changed, changed]
        await _make_stale(db_session)
        job = await _extract(api, db_session, fake_storage, project_id)
        assert job.payload["skipped_reviewed"] == 1 and job.payload["updated"] == 1

        after = {i["id"]: i for i in (await api.get(_url(project_id))).json()["items"]}
        assert after[first["id"]]["section_mark"] == "АР"
        assert after[first["id"]]["sheet_number"] == "7"
        assert after[first["id"]]["status"] == "confirmed"
        # У второй раздел остался ручным, остальное перезаписано.
        assert after[second["id"]]["section_mark"] == "КР"
        assert after[second["id"]]["evidence"]["section_mark"] == {
            "source": "manual",
            "snippet": "",
        }
        assert after[second["id"]]["sheet_number"] == "9"
        assert after[second["id"]]["sheet_kind"] == "scheme"
        assert after[second["id"]]["evidence"]["sheet_number"]["source"] == "stamp"


async def test_patch_sets_manual_evidence_and_review_stamp(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        await _extract(api, db_session, fake_storage, project_id)
        item = (await api.get(_url(project_id))).json()["items"][0]
        url = _url(project_id, f"/{item['id']}")

        response = await api.patch(
            url,
            json={
                "section_mark": "ОВ",
                "sheet_kind": "floor_plan",
                "stage": "РД",
                "building": " 2 ",
                "level_from": "3",
                "level_from_ordinal": 3,
                "elevation_m": 9.6,
                "title": "",
                "status": "confirmed",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["section_mark"], body["sheet_kind"], body["stage"]) == (
            "ОВ",
            "floor_plan",
            "РД",
        )
        assert body["building"] == "2" and body["title"] is None
        assert body["level_from_ordinal"] == 3 and body["elevation_m"] == 9.6
        for name in ("section_mark", "sheet_kind", "stage", "building", "title", "elevation_m"):
            assert body["evidence"][name] == {"source": "manual", "snippet": ""}
        # Нетронутое поле сохранило своё доказательство.
        assert body["evidence"]["code"]["source"] == "stamp"
        assert body["status"] == "confirmed" and body["confirmed_at"] is not None
        assert body["confirmed_by"] is not None

        reset = await api.patch(url, json={"status": "candidate"})
        assert reset.status_code == 200
        assert reset.json()["confirmed_by"] is None and reset.json()["confirmed_at"] is None
        assert reset.json()["section_mark"] == "ОВ"
        rejected = await api.patch(url, json={"status": "rejected"})
        assert rejected.json()["status"] == "rejected"
        assert rejected.json()["confirmed_by"] is not None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"sheet_kind": "unknown"},
        {"section_mark": "ХХХ"},
        {"stage": "Э"},
        {"status": "done"},
        {"status": None},
        {"elevation_m": 5000},
        {"level_from_ordinal": 1000},
        {"title": "x" * 501},
        {"unknown": 1},
    ],
)
async def test_patch_rejects_bad_values(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
    body: dict[str, object],
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        await _extract(api, db_session, fake_storage, project_id)
        item = (await api.get(_url(project_id))).json()["items"][0]
        response = await api.patch(_url(project_id, f"/{item['id']}"), json=body)
        assert response.status_code == 422, response.text
        assert (await api.get(_url(project_id))).json()["items"][0]["evidence"] == item["evidence"]


async def test_bulk_status_and_filters(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        plan = await _add_pdf(db_session, fake_storage, project_id, PLAN_PDF)
        await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        await _extract(api, db_session, fake_storage, project_id)
        items = (await api.get(_url(project_id))).json()["items"]
        assert len(items) == 3

        plans = (await api.get(_url(project_id, "?section_mark=АР"))).json()
        assert plans["total"] == 2 and {i["file_name"] for i in plans["items"]} == {PLAN_PDF}
        by_revision = (await api.get(_url(project_id, f"?revision_id={plan.id}"))).json()
        assert by_revision["total"] == 2
        assert (await api.get(_url(project_id, "?section_mark=КР"))).json()["total"] == 0
        paged = (await api.get(_url(project_id, "?limit=1&offset=1"))).json()
        assert paged["total"] == 3 and len(paged["items"]) == 1
        assert paged["items"][0]["id"] == items[1]["id"]
        assert (await api.get(_url(project_id, "?limit=1001"))).status_code == 422

        ids = [i["id"] for i in plans["items"]]
        bulk = await api.post(
            _url(project_id, "/bulk-status"), json={"ids": [*ids, ids[0]], "status": "confirmed"}
        )
        assert bulk.status_code == 200 and bulk.json() == {"updated": 2}
        confirmed = (await api.get(_url(project_id, "?status=confirmed"))).json()
        assert {i["id"] for i in confirmed["items"]} == set(ids)
        assert all(i["confirmed_by"] is not None for i in confirmed["items"])
        assert (await api.get(_url(project_id, "?status=candidate"))).json()["total"] == 1
        assert (await api.get(_url(project_id, "?status=bogus"))).status_code == 422

        back = await api.post(
            _url(project_id, "/bulk-status"), json={"ids": ids, "status": "candidate"}
        )
        assert back.json() == {"updated": 2}
        assert (await api.get(_url(project_id, "?status=candidate"))).json()["total"] == 3

        # Один чужой id - 404, остальные не меняются.
        unknown = await api.post(
            _url(project_id, "/bulk-status"),
            json={"ids": [ids[0], str(uuid.uuid4())], "status": "rejected"},
        )
        assert unknown.status_code == 404
        assert (await api.get(_url(project_id, "?status=rejected"))).json()["total"] == 0
        for body in (
            {"ids": [], "status": "confirmed"},
            {"ids": [str(uuid.uuid4())] * 1001, "status": "confirmed"},
            {"ids": ids, "status": "nope"},
        ):
            assert (await api.post(_url(project_id, "/bulk-status"), json=body)).status_code == 422


async def test_foreign_workspace_and_foreign_project_ids_get_404(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    texts: _Texts,
) -> None:
    settings = _settings()
    async with build_api(make_context(), settings=settings) as api:
        project_id = await _project(api)
        other_project = await _project(api)
        await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        await _extract(api, db_session, fake_storage, project_id)
        item = (await api.get(_url(project_id))).json()["items"][0]
        # Паспорт чужого проекта через свой проект недоступен.
        assert (
            await api.patch(_url(other_project, f"/{item['id']}"), json={"title": "x"})
        ).status_code == 404
        assert (
            await api.post(
                _url(other_project, "/bulk-status"),
                json={"ids": [item["id"]], "status": "confirmed"},
            )
        ).status_code == 404
        assert (await api.get(_url(other_project))).json() == {"items": [], "total": 0}
        # Итог разбора чужого проекта через свой не виден.
        assert (await api.get(_url(other_project, "/extract-summary"))).json() is None

    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (await foreign.get(_url(project_id))).status_code == 404
        assert (await foreign.get(_url(project_id, "/extract-summary"))).status_code == 404
        assert (await foreign.post(_url(project_id, "/extract"))).status_code == 404
        assert (
            await foreign.patch(_url(project_id, f"/{item['id']}"), json={"title": "x"})
        ).status_code == 404
        assert (
            await foreign.post(
                _url(project_id, "/bulk-status"),
                json={"ids": [item["id"]], "status": "confirmed"},
            )
        ).status_code == 404
    stored = (await db_session.scalars(select(SheetPassport))).one()
    assert stored.status == "candidate" and stored.title != "x"


async def test_viewer_reads_but_cannot_write(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    settings = _settings()
    async with build_api(make_context(), settings=settings) as api:
        project_id = await _project(api)
        await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        await _extract(api, db_session, fake_storage, project_id)
        item = (await api.get(_url(project_id))).json()["items"][0]
    async with build_api(make_context(Role.VIEWER), settings=settings) as viewer:
        assert (await viewer.get(_url(project_id))).status_code == 200
        assert (await viewer.post(_url(project_id, "/extract"))).status_code == 403
        assert (
            await viewer.patch(_url(project_id, f"/{item['id']}"), json={"status": "confirmed"})
        ).status_code == 403
        assert (
            await viewer.post(
                _url(project_id, "/bulk-status"), json={"ids": [item["id"]], "status": "confirmed"}
            )
        ).status_code == 403


async def test_project_without_pdfs_finishes_with_zero_counts(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        job = await _extract(api, db_session, fake_storage, project_id)
    assert job.status is JobStatus.SUCCEEDED
    assert job.payload["files_total"] == 0 and job.payload["errors"] == []


async def test_latest_revision_of_each_document_is_parsed(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        old = await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        newer = DocumentRevision(
            document_id=old.document_id,
            source_filename=PLAN_PDF,
            source_mime="application/pdf",
            source_size=1,
            source_sha256="a" * 64,
            storage_key=f"test/{uuid.uuid4()}",
        )
        db_session.add(newer)
        await db_session.commit()
        fake_storage.objects[newer.storage_key] = b"%PDF-1.7\n"
        revisions = await passports_service.latest_pdf_revisions(
            db_session, project_id=uuid.UUID(project_id)
        )
        assert [revision.id for revision in revisions] == [newer.id]


async def test_extract_summary_null_without_jobs_then_counts_and_errors(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        empty = await api.get(_url(project_id, "/extract-summary"))
        assert empty.status_code == 200 and empty.json() is None

        await _add_pdf(db_session, fake_storage, project_id, PLAN_PDF)
        await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        await _add_pdf(db_session, fake_storage, project_id, BROKEN_PDF, data=b"not a pdf at all")

        queued = await api.post(_url(project_id, "/extract"))
        assert queued.status_code == 202, queued.text
        waiting = (await api.get(_url(project_id, "/extract-summary"))).json()
        assert waiting["job_id"] == queued.json()["id"] and waiting["status"] == "queued"
        # Итога ещё нет: числа - null, а не 0.
        assert waiting["files_total"] is None and waiting["pages"] is None
        assert waiting["error_count"] is None and waiting["finished_at"] is None
        assert waiting["errors"] == [] and waiting["versions"] == {}

        await _run_job(db_session, fake_storage)
        done = (await api.get(_url(project_id, "/extract-summary"))).json()
        assert done["status"] == "succeeded" and done["finished_at"] is not None
        assert done["files_total"] == 3 and done["files_parsed"] == 2 and done["pages"] == 3
        assert done["created"] == 3 and done["updated"] == 0 and done["skipped_reviewed"] == 0
        assert done["error_count"] == 1
        assert [item["file_name"] for item in done["errors"]] == [BROKEN_PDF]
        assert done["errors"][0]["error"]
        assert done["versions"]["parser"].startswith("consistency.sheet_passport")

        # Берётся последнее задание.
        await _make_stale(db_session)
        again = await _extract(api, db_session, fake_storage, project_id)
        latest = (await api.get(_url(project_id, "/extract-summary"))).json()
        assert latest["job_id"] == str(again.id)
        assert latest["created"] == 0 and latest["updated"] == 3


async def test_rerun_skips_revision_parsed_by_current_parser(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    texts: _Texts,
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _add_pdf(db_session, fake_storage, project_id, PLAN_PDF)
        await _add_pdf(db_session, fake_storage, project_id, SCHEME_PDF)
        first = await _extract(api, db_session, fake_storage, project_id)
        assert first.payload["files_parsed"] == 2 and first.payload["files_already_parsed"] == 0

        # Повтор с той же версией разборщика: ничего не качается и не разбирается.
        fake_storage.objects.clear()
        second = await _extract(api, db_session, fake_storage, project_id)
        assert second.status is JobStatus.SUCCEEDED
        assert second.payload["files_total"] == 2
        assert second.payload["files_already_parsed"] == 2
        assert second.payload["files_parsed"] == 0 and second.payload["error_count"] == 0

        # Одна ревизия разобрана старой версией - только она идёт в работу заново.
        plan_rows = select(SheetPassport.id).where(SheetPassport.file_name == PLAN_PDF)
        await db_session.execute(
            update(SheetPassport)
            .where(SheetPassport.id.in_(plan_rows))
            .values(versions={"parser": "old"})
        )
        await db_session.commit()
        for revision in (await db_session.scalars(select(DocumentRevision))).all():
            fake_storage.objects[revision.storage_key] = b"%PDF-1.7\n"
        third = await _extract(api, db_session, fake_storage, project_id)
        assert third.payload["files_already_parsed"] == 1
        assert third.payload["files_parsed"] == 1 and third.payload["updated"] == 2
