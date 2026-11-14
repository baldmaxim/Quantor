"""Ведомости листов (С2, «ведомость ↔ листы»): задание разбора, подтверждение, проверки в каркасе.

Только синтетика: текст страниц пишется в поддельное хранилище, паспорта - в базу напрямую.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType, Role
from app.main import create_app
from app.models import DocumentRevision, Job, SheetPassport, SheetRegister
from app.services import jobs as jobs_service
from app.worker.registry import handler_for, supported_types
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.doc_questions_support import add_pdf, add_text, doc_settings, make_project

AR_PDF = "АР.pdf"
EMPTY_PDF = "ИОС2 без текста.pdf"
GENERAL_DATA = """Общие данные
Ведомость рабочих чертежей основного комплекта
Лист Наименование Примечание
1 Общие данные
2 План 1 этажа
3 План 2 этажа
Изм. Кол.уч Лист №док Подп. Дата
"""
CONTINUED = "Ведомость рабочих чертежей (продолжение)\n4 Разрез 1-1\n5 Фасад 1-12\n"


def _url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/sheet-registers{tail}"


async def _sheet(
    session: AsyncSession,
    project_id: str,
    revision: DocumentRevision,
    page: int,
    number: str | None,
    title: str,
    *,
    kind: str = "floor_plan",
    status: str = "confirmed",
) -> None:
    session.add(
        SheetPassport(
            project_id=uuid.UUID(project_id),
            revision_id=revision.id,
            page_index=page,
            file_name=revision.source_filename,
            section_mark="АР",
            sheet_kind=kind,
            sheet_number=number,
            title=title,
            status=status,
            evidence={},
            versions={},
        )
    )
    await session.commit()


async def _run_job(session: AsyncSession, storage: FakeObjectStorage) -> Job:
    job = await jobs_service.claim(
        session,
        worker_id="sheet-register-test",
        job_types=[JobType.SHEET_REGISTER_EXTRACT.value],
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
    response = await api.post(_url(project_id, "/extract"))
    assert response.status_code == 202, response.text
    assert response.json()["job_type"] == "sheet_register_extract"
    job = await _run_job(session, storage)
    assert str(job.id) == response.json()["id"]
    return job


async def _project_with_register(
    api: AsyncClient, session: AsyncSession, storage: FakeObjectStorage, tmp_path: Path
) -> tuple[str, DocumentRevision]:
    """АР: ведомость на 1-й странице с продолжением на 2-й, листы 1-5; PDF без текста."""
    project_id = await make_project(api)
    ar = await add_pdf(session, storage, project_id, AR_PDF)
    await add_pdf(session, storage, project_id, EMPTY_PDF)
    pages = [GENERAL_DATA, CONTINUED, "План 1 этажа", "План 2 этажа", "Разрез", "Фасад"]
    await add_text(session, storage, tmp_path, project_id, ar, pages)
    await _sheet(session, project_id, ar, 0, "1", "Общие данные", kind="general_data")
    await _sheet(session, project_id, ar, 1, "1", "Общие данные (продолжение)", status="rejected")
    await _sheet(session, project_id, ar, 2, "2", "План 1 этажа")
    await _sheet(session, project_id, ar, 3, "3", "Разрез 2-2")
    await _sheet(session, project_id, ar, 4, "4", "Разрез 1-1", status="candidate")
    await _sheet(session, project_id, ar, 5, "6", "Фасад 1-12")
    return project_id, ar


def _checks(body: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [item for item in body["checks"] if item["code"] == code]


def test_routes_are_in_openapi_and_job_is_registered() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/sheet-registers"
    assert set(paths[base]) == {"get"}
    assert set(paths[f"{base}/extract"]) == {"post"}
    assert set(paths[f"{base}/bulk-status"]) == {"post"}
    assert JobType.SHEET_REGISTER_EXTRACT.value in supported_types()


async def test_routes_are_closed_by_flag(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(make_context(), settings=doc_settings(flag=False)) as api:
        project_id = str(uuid.uuid4())
        responses = [
            await api.get(_url(project_id)),
            await api.post(_url(project_id, "/extract")),
            await api.post(
                _url(project_id, "/bulk-status"),
                json={"ids": [str(uuid.uuid4())], "status": "confirmed"},
            ),
        ]
    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_extract_confirm_and_checks(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, ar = await _project_with_register(api, db_session, fake_storage, tmp_path)

        before = (await api.get(f"/api/v1/projects/{project_id}/frame")).json()
        assert "запустите разбор" in _checks(before, "register_sheets")[0]["message"]
        assert before["versions"]["register_checks"] == "consistency.checks.register.v1"

        job = await _extract(api, db_session, fake_storage, project_id)
        assert job.status is JobStatus.SUCCEEDED
        payload = job.payload
        assert payload["registers"] == 1 and payload["revisions_scanned"] == 1
        assert payload["revisions_no_text"] == 1 and payload["no_text_files"] == [EMPTY_PDF]

        view = (await api.get(_url(project_id))).json()
        assert view["last_extract"]["status"] == "succeeded"
        assert view["versions"]["parser"] == "consistency.sheet_register.v1"
        [register] = view["registers"]
        assert register["file_name"] == AR_PDF and register["revision_id"] == str(ar.id)
        assert register["pages"] == [0, 1] and register["status"] == "candidate"
        assert [(e["number"], e["page_index"]) for e in register["entries"]] == [
            ("1", 0),
            ("2", 0),
            ("3", 0),
            ("4", 1),
            ("5", 1),
        ]

        pending = (await api.get(f"/api/v1/projects/{project_id}/frame")).json()
        assert "Найдено ведомостей листов: 1" in _checks(pending, "register_sheets")[0]["message"]

        confirmed = await api.post(
            _url(project_id, "/bulk-status"), json={"ids": [register["id"]], "status": "confirmed"}
        )
        assert confirmed.status_code == 200 and confirmed.json() == {"updated": 1}

        body = (await api.get(f"/api/v1/projects/{project_id}/frame")).json()
        [rows] = _checks(body, "register_sheets")
        assert rows["status"] == "mismatch"
        # 5 - нет листа (на странице 6 стоит номер 6), 4 - паспорт ещё кандидат.
        assert "Нет листа с номером: 5" in rows["message"]
        assert "Паспорт листа не подтверждён: 4" in rows["message"]
        assert rows["refs"][0]["kind"] == "register" and rows["refs"][0]["file_name"] == AR_PDF
        [extra] = _checks(body, "sheets_in_register")
        assert extra["status"] == "mismatch" and "Листов нет в ведомости: 6" in extra["message"]
        [titles] = _checks(body, "register_titles")
        assert titles["status"] == "mismatch"
        assert "лист 3: в ведомости «План 2 этажа», на листе «Разрез 2-2»" in titles["message"]


async def test_rerun_keeps_reviewed_registers(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await _project_with_register(api, db_session, fake_storage, tmp_path)
        await _extract(api, db_session, fake_storage, project_id)
        [register] = (await api.get(_url(project_id))).json()["registers"]
        await api.post(
            _url(project_id, "/bulk-status"), json={"ids": [register["id"]], "status": "rejected"}
        )
        await _extract(api, db_session, fake_storage, project_id)
        rows = (await db_session.scalars(select(SheetRegister))).all()
        assert [(str(row.id), row.status) for row in rows] == [(register["id"], "rejected")]


async def test_bulk_status_foreign_id_and_viewer(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await _project_with_register(api, db_session, fake_storage, tmp_path)
        await _extract(api, db_session, fake_storage, project_id)
        [register] = (await api.get(_url(project_id))).json()["registers"]
        foreign = await api.post(
            _url(project_id, "/bulk-status"),
            json={"ids": [register["id"], str(uuid.uuid4())], "status": "confirmed"},
        )
        assert foreign.status_code == 404
        row = await db_session.get(SheetRegister, uuid.UUID(register["id"]))
        assert row is not None
        await db_session.refresh(row)
        assert row.status == "candidate"

    async with build_api(make_context(Role.VIEWER), settings=doc_settings()) as viewer:
        assert (await viewer.get(_url(project_id))).status_code == 200
        assert (await viewer.post(_url(project_id, "/extract"))).status_code == 403
