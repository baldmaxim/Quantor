"""Каркас здания (ADR-0043, С2): API сборки, правки, подтверждения и проверок.

Только синтетика: паспорта листов и ответы к документации пишутся в базу напрямую.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dev import DEV_USER_ID
from app.core.config import Settings
from app.domain import DocumentKind, Role
from app.main import create_app
from app.models import DocQuestionAnswer, Document, DocumentRevision, SheetPassport
from tests.conftest import clean_settings, make_context


def _settings(*, flag: bool = True) -> Settings:
    return clean_settings(
        environment="test", feature_flags="project.consistency=true" if flag else ""
    )


def _url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/frame{tail}"


async def _project(api: AsyncClient) -> str:
    response = await api.post("/api/v1/projects", json={"name": f"Каркас {uuid.uuid4().hex[:6]}"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _revision(session: AsyncSession, project_id: str, name: str) -> DocumentRevision:
    document = Document(
        project_id=uuid.UUID(project_id), display_name=name, document_kind=DocumentKind.PDF
    )
    session.add(document)
    await session.flush()
    key = f"test/{uuid.uuid4()}"
    revision = DocumentRevision(
        document_id=document.id,
        source_filename=name,
        source_mime="application/pdf",
        source_size=10,
        source_sha256=hashlib.sha256(key.encode()).hexdigest(),
        storage_key=key,
    )
    session.add(revision)
    await session.flush()
    return revision


async def _passport(
    session: AsyncSession,
    revision: DocumentRevision,
    page: int,
    *,
    mark: str = "АР",
    kind: str = "floor_plan",
    building: str | None = "1",
    levels: tuple[int, int] = (1, 1),
    elevation: float | None = None,
    status: str = "confirmed",
    title: str | None = None,
) -> None:
    document = await session.get(Document, revision.document_id)
    assert document is not None
    session.add(
        SheetPassport(
            project_id=document.project_id,
            revision_id=revision.id,
            page_index=page,
            file_name=revision.source_filename,
            section_mark=mark,
            sheet_kind=kind,
            building=building,
            level_from=f"{levels[0]} этаж",
            level_to=f"{levels[1]} этаж",
            level_from_ordinal=levels[0],
            level_to_ordinal=levels[1],
            elevation_m=elevation,
            title=title,
            status=status,
            evidence={},
            versions={},
        )
    )


async def _seed(session: AsyncSession, project_id: str) -> None:
    ar = await _revision(session, project_id, "АР.pdf")
    vk = await _revision(session, project_id, "ИОС2.pdf")
    await _passport(session, ar, 0, levels=(1, 1), elevation=0.0)
    await _passport(session, ar, 1, levels=(2, 4))
    await _passport(session, ar, 2, levels=(5, 5), status="candidate")
    await _passport(session, vk, 0, mark="ИОС2", levels=(2, 2), elevation=3.3, title="План В1")
    await _passport(session, vk, 1, mark="ИОС2", levels=(5, 5), title="План В1")
    await session.commit()


def _levels(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["code"]: node for node in body["nodes"] if node["kind"] == "level"}


async def test_routes_are_in_openapi_and_closed_by_flag(
    build_api: Callable[..., AsyncClient],
) -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths["/api/v1/projects/{project_id}/frame"]) == {"get"}
    assert set(paths["/api/v1/projects/{project_id}/frame/rebuild"]) == {"post"}
    assert set(paths["/api/v1/projects/{project_id}/frame/nodes"]) == {"post"}
    assert set(paths["/api/v1/projects/{project_id}/frame/nodes/{node_id}"]) == {
        "patch",
        "delete",
    }
    assert set(paths["/api/v1/projects/{project_id}/frame/bulk-status"]) == {"post"}

    async with build_api(make_context(), settings=_settings(flag=False)) as api:
        project_id = str(uuid.uuid4())
        some_id = str(uuid.uuid4())
        responses = [
            await api.get(_url(project_id)),
            await api.post(_url(project_id, "/rebuild")),
            await api.post(_url(project_id, "/nodes"), json={"kind": "building"}),
            await api.patch(_url(project_id, f"/nodes/{some_id}"), json={"status": "confirmed"}),
            await api.delete(_url(project_id, f"/nodes/{some_id}")),
            await api.post(
                _url(project_id, "/bulk-status"), json={"ids": [some_id], "status": "confirmed"}
            ),
        ]
    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_rebuild_uses_confirmed_plans_and_keeps_reviewed_nodes(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _seed(db_session, project_id)

        empty = (await api.get(_url(project_id))).json()
        assert empty["nodes"] == []
        assert empty["confirmed_plans"] == 4 and empty["candidate_plans"] == 1

        first = await api.post(_url(project_id, "/rebuild"))
        assert first.status_code == 200, first.text
        # Корпус, секция и уровни 1-5 (5 - из подтверждённого плана ИОС2).
        assert first.json() == {"created": 7, "updated": 0, "removed": 0, "kept_reviewed": 0}

        body = (await api.get(_url(project_id))).json()
        levels = _levels(body)
        assert sorted(levels) == ["1 этаж", "2 этаж", "3 этаж", "4 этаж", "5 этаж"]
        assert levels["1 этаж"]["elevation_m"] == 0.0
        assert levels["2 этаж"]["elevation_m"] == 3.3
        # Высота выводится из отметок соседних уровней.
        assert levels["1 этаж"]["height_derived_m"] == 3.3
        assert levels["2 этаж"]["passport_count"] == 2

        # Подтверждаем всё; повторная сборка подтверждённое не трогает.
        ids = [node["id"] for node in body["nodes"]]
        bulk = await api.post(
            _url(project_id, "/bulk-status"), json={"ids": ids, "status": "confirmed"}
        )
        assert bulk.json() == {"updated": 7}
        again = (await api.post(_url(project_id, "/rebuild"))).json()
        assert again == {"created": 0, "updated": 0, "removed": 0, "kept_reviewed": 7}

        checks = (await api.get(_url(project_id))).json()["checks"]
        ar_5 = next(
            item
            for item in checks
            if item["code"] == "ar_plan_per_level" and item["level"] == "5 этаж"
        )
        assert ar_5["status"] == "mismatch"
        assert ar_5["refs"][0]["kind"] == "passport"
        scheme = next(item for item in checks if item["code"] == "scheme_per_system")
        assert scheme["status"] == "mismatch"
        storeys = next(item for item in checks if item["code"] == "pz_storeys")
        assert storeys["status"] == "not_run"


async def test_stale_candidates_are_removed_and_manual_fields_survive(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _seed(db_session, project_id)
        await api.post(_url(project_id, "/rebuild"))
        levels = _levels((await api.get(_url(project_id))).json())

        patched = await api.patch(
            _url(project_id, f"/nodes/{levels['3 этаж']['id']}"), json={"elevation_m": 6.6}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["manual_fields"] == ["elevation_m"]
        assert patched.json()["status"] == "candidate"

        # План ИОС2 5-го этажа отклонён: уровень 5 пропадает при пересборке.
        await db_session.execute(
            update(SheetPassport)
            .where(SheetPassport.project_id == uuid.UUID(project_id))
            .where(SheetPassport.page_index == 1, SheetPassport.section_mark == "ИОС2")
            .values(status="rejected")
        )
        await db_session.commit()
        result = (await api.post(_url(project_id, "/rebuild"))).json()
        assert result["removed"] == 1
        after = _levels((await api.get(_url(project_id))).json())
        assert "5 этаж" not in after
        assert after["3 этаж"]["elevation_m"] == 6.6
        # Высота 2 этажа - от ручной отметки 3-го.
        assert after["2 этаж"]["height_derived_m"] == 3.3


async def test_stale_candidate_with_manual_edit_is_kept(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _seed(db_session, project_id)
        await api.post(_url(project_id, "/rebuild"))
        levels = _levels((await api.get(_url(project_id))).json())
        await api.patch(
            _url(project_id, f"/nodes/{levels['5 этаж']['id']}"), json={"height_m": 3.0}
        )
        await db_session.execute(
            update(SheetPassport)
            .where(SheetPassport.project_id == uuid.UUID(project_id))
            .where(SheetPassport.page_index == 1, SheetPassport.section_mark == "ИОС2")
            .values(status="rejected")
        )
        await db_session.commit()
        result = (await api.post(_url(project_id, "/rebuild"))).json()
        assert result["removed"] == 0
        kept = _levels((await api.get(_url(project_id))).json())["5 этаж"]
        assert kept["height_m"] == 3.0 and kept["passport_count"] == 0


async def test_manual_nodes_create_and_delete(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        created = await api.post(
            _url(project_id, "/nodes"),
            json={"kind": "level", "building": "2", "section": "1", "code": "кровля"},
        )
        assert created.status_code == 201, created.text
        level = created.json()
        assert level["origin"] == "manual" and level["ordinal"] is None
        nodes = (await api.get(_url(project_id))).json()["nodes"]
        assert [node["kind"] for node in nodes] == ["building", "section", "level"]

        duplicate = await api.post(
            _url(project_id, "/nodes"),
            json={"kind": "level", "building": "2", "section": "1", "code": "кровля"},
        )
        assert duplicate.status_code == 422
        invalid = await api.post(_url(project_id, "/nodes"), json={"kind": "building", "code": "x"})
        assert invalid.status_code == 422
        # Номер и отметка - только у уровня.
        building = next(node for node in nodes if node["kind"] == "building")
        wrong = await api.patch(_url(project_id, f"/nodes/{building['id']}"), json={"ordinal": 3})
        assert wrong.status_code == 422

        deleted = await api.delete(_url(project_id, f"/nodes/{building['id']}"))
        assert deleted.status_code == 204
        assert (await api.get(_url(project_id))).json()["nodes"] == []


async def test_passport_nodes_cannot_be_deleted_and_answers_feed_checks(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        project_id = await _project(api)
        await _seed(db_session, project_id)
        await api.post(_url(project_id, "/rebuild"))
        body = (await api.get(_url(project_id))).json()
        level = _levels(body)["1 этаж"]
        refused = await api.delete(_url(project_id, f"/nodes/{level['id']}"))
        assert refused.status_code == 422

        ids = [node["id"] for node in body["nodes"]]
        await api.post(_url(project_id, "/bulk-status"), json={"ids": ids, "status": "confirmed"})
        db_session.add(
            DocQuestionAnswer(
                project_id=uuid.UUID(project_id),
                question_code="storeys",
                scope_building="1",
                source="manual",
                value={
                    "kind": "count",
                    "display": "5",
                    "numbers": [5],
                    "qualifier": None,
                    "code": None,
                },
                value_text="5",
                note="ПЗ, раздел 1",
                catalog_version="consistency.doc_questions.v1",
                confirmed_by=DEV_USER_ID,
            )
        )
        await db_session.commit()
        checks = (await api.get(_url(project_id))).json()["checks"]
        storeys = next(item for item in checks if item["code"] == "pz_storeys")
        assert storeys["status"] == "match", storeys
        assert storeys["refs"][0]["kind"] == "answer"


async def test_viewer_reads_but_cannot_change(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    settings = _settings()
    async with build_api(make_context(), settings=settings) as api:
        project_id = await _project(api)
    async with build_api(make_context(Role.VIEWER), settings=settings) as viewer:
        assert (await viewer.get(_url(project_id))).status_code == 200
        assert (await viewer.post(_url(project_id, "/rebuild"))).status_code == 403


async def test_foreign_project_is_not_found(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=_settings()) as api:
        response = await api.get(_url(str(uuid.uuid4())))
    assert response.status_code == 404
