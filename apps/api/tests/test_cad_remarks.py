"""Замечания проверяющего к видам результата CAD: хранение на сервере, слияние, границы доступа.

Движок не нужен: задание ставится настоящим API, а номер попытки и итог выставляются прямо в
базе, как их оставил бы исполнитель.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.main import create_app
from app.models import CadRemark, Job, Workspace
from tests.conftest import clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload, cad_settings

SHA = "a" * 64
OTHER_SHA = "b" * 64
T1 = "2026-11-09T10:00:00.000Z"
T2 = "2026-11-09T11:00:00.000Z"
T3 = "2026-11-09T12:00:00.000Z"
QUERY = "attempt=1&page_index=0&view=1"


def _body(**patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "missing_wall",
        "comment": "Нет стены у оси Б",
        "reviewer": "Иванов",
        "status": "open",
        "bbox_pt": [10.0, 20.0, 110.0, 120.0],
        "dxf_sha256": None,
    }
    body.update(patch)
    return body


def _item(key: str, updated_at: str = T1, **patch: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": key,
        "type": "false_wall",
        "comment": f"Замечание {key}",
        "reviewer": "Иванов",
        "status": "open",
        "bbox_pt": [1, 2, 30, 40],
        "created_at": T1,
        "updated_at": updated_at,
    }
    item.update(patch)
    return item


def _file(
    project: str, revision: str, job: str, remarks: list[dict[str, Any]], **patch: Any
) -> dict[str, Any]:
    file: dict[str, Any] = {
        "schema": "quantor.cad-remarks.v1",
        "project_id": project,
        "revision_id": revision,
        "job_id": job,
        "attempt": 1,
        "page_index": 0,
        "legacy_pdf_page": 1,
        "view": 1,
        "dxf_sha256": None,
        "coordinate_system": "pdf_pt_top_left",
        "exported_at": T3,
        "reviewer": "Иванов",
        "engineering_acceptance": False,
        "remarks": remarks,
    }
    file.update(patch)
    return file


async def _job(
    api: AsyncClient, db_session: AsyncSession, *, attempt: int = 2, dxf_sha: str | None = None
) -> tuple[str, str, str, str]:
    """Проект, ревизия, задание и базовый адрес; у задания `attempt` попыток."""
    project_id, revision_id = await _upload(api, BROKEN_PDF)
    base = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad"
    created = await api.post(base, json={"pages": [0]})
    assert created.status_code == 202, created.text
    job_id = created.json()["job_id"]
    values: dict[str, Any] = {"attempt": attempt}
    if dxf_sha is not None:
        job = await db_session.get(Job, uuid.UUID(job_id))
        assert job is not None
        payload = dict(job.payload)
        payload["cad_result"] = {
            "attempt": attempt,
            "artifacts": [
                {"name": "views/p001_v01/plan_candidates.dxf", "sha256": dxf_sha, "size": 10}
            ],
        }
        values["payload"] = payload
    await db_session.execute(update(Job).where(Job.id == uuid.UUID(job_id)).values(**values))
    await db_session.commit()
    return project_id, revision_id, job_id, base


async def test_crud_and_repeated_put_updates(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _job(api, db_session)
        url = f"{base}/{job_id}/remarks"
        key = str(uuid.uuid4())

        assert (await api.get(f"{url}?{QUERY}")).json() == []

        created = await api.put(f"{url}/{key}?{QUERY}", json=_body())
        assert created.status_code == 200, created.text
        row = created.json()
        assert row["id"] == key
        assert (row["type"], row["status"], row["reviewer"]) == ("missing_wall", "open", "Иванов")
        assert row["bbox_pt"] == [10.0, 20.0, 110.0, 120.0]
        assert row["created_at"].endswith("Z") and row["updated_at"] >= row["created_at"]

        again = await api.put(
            f"{url}/{key}?{QUERY}", json=_body(status="resolved", comment="Исправлено")
        )
        assert again.status_code == 200
        assert (again.json()["status"], again.json()["comment"]) == ("resolved", "Исправлено")
        assert again.json()["created_at"] == row["created_at"]
        assert again.json()["updated_at"] >= row["updated_at"]

        listed = (await api.get(f"{url}?{QUERY}")).json()
        assert [item["id"] for item in listed] == [key] and listed[0]["status"] == "resolved"
        count = await db_session.scalar(select(func.count()).select_from(CadRemark))
        assert count == 1
        stored = (await db_session.scalars(select(CadRemark))).one()
        assert stored.created_by is not None and stored.updated_by is not None

        # Другой вид и другая попытка своих замечаний не видят.
        assert (await api.get(f"{url}?attempt=1&page_index=0&view=2")).json() == []
        assert (await api.get(f"{url}?attempt=2&page_index=0&view=1")).json() == []

        assert (await api.delete(f"{url}/{key}?{QUERY}")).status_code == 204
        assert (await api.get(f"{url}?{QUERY}")).json() == []
        missing = await api.delete(f"{url}/{key}?{QUERY}")
        assert missing.status_code == 404


async def test_list_is_sorted_by_creation(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id, job_id, base = await _job(api, db_session)
        url = f"{base}/{job_id}/remarks"
        imported = await api.post(
            f"{url}/import",
            json=_file(
                project_id,
                revision_id,
                job_id,
                [
                    _item("b", created_at=T2, updated_at=T2),
                    _item("c", created_at=T1),
                    _item("a", created_at=T1),
                ],
            ),
        )
        assert imported.status_code == 200, imported.text
        listed = (await api.get(f"{url}?{QUERY}")).json()
        assert [item["id"] for item in listed] == ["a", "c", "b"]


async def test_put_validates_body(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        _, _, job_id, base = await _job(api, db_session)
        url = f"{base}/{job_id}/remarks/k1?{QUERY}"
        for patch in (
            {"bbox_pt": [10, 10, 5, 20]},
            {"bbox_pt": [-1, 0, 5, 5]},
            {"bbox_pt": [0, 0, 1]},
            {"type": "unknown"},
            {"status": "accepted"},
            {"comment": "я" * 4001},
            {"dxf_sha256": "XYZ"},
            {"engineering_acceptance": True},
        ):
            assert (await api.put(url, json=_body(**patch))).status_code == 422, patch
        long_key = "k" * 65
        too_long = await api.put(f"{base}/{job_id}/remarks/{long_key}?{QUERY}", json=_body())
        assert too_long.status_code == 422


async def test_import_merge_rules(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id, job_id, base = await _job(api, db_session)
        url = f"{base}/{job_id}/remarks"
        file = _file(project_id, revision_id, job_id, [_item("r1"), _item("r2")])

        first = await api.post(f"{url}/import", json=file)
        assert first.status_code == 200, first.text
        assert first.json() == {"imported": 2, "updated": 0}

        repeat = await api.post(f"{url}/import", json=file)
        assert repeat.json() == {"imported": 0, "updated": 0}

        later = _file(
            project_id,
            revision_id,
            job_id,
            [_item("r1", T2, comment="Правка из файла", status="resolved")],
        )
        updated = await api.post(f"{url}/import", json=later)
        assert updated.json() == {"imported": 0, "updated": 1}
        listed = {item["id"]: item for item in (await api.get(f"{url}?{QUERY}")).json()}
        assert listed["r1"]["comment"] == "Правка из файла"
        assert listed["r1"]["status"] == "resolved"
        # Время правки берётся из файла, а не ставится заново.
        assert listed["r1"]["updated_at"].startswith("2026-11-09T11:00:00")
        assert listed["r2"]["comment"] == "Замечание r2"

        # Более ранняя версия не откатывает более позднюю.
        older = _file(project_id, revision_id, job_id, [_item("r1", T1, comment="Старое")])
        assert (await api.post(f"{url}/import", json=older)).json() == {
            "imported": 0,
            "updated": 0,
        }
        listed = {item["id"]: item for item in (await api.get(f"{url}?{QUERY}")).json()}
        assert listed["r1"]["comment"] == "Правка из файла"


async def test_import_round_trip_of_listing(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    """Список с сервера, положенный в файл как есть, при импорте ничего не меняет."""
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id, job_id, base = await _job(api, db_session)
        url = f"{base}/{job_id}/remarks"
        await api.put(f"{url}/k1?{QUERY}", json=_body())
        listed = (await api.get(f"{url}?{QUERY}")).json()
        file = _file(project_id, revision_id, job_id, listed)
        assert (await api.post(f"{url}/import", json=file)).json() == {
            "imported": 0,
            "updated": 0,
        }


async def test_import_rejects_foreign_binding(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id, job_id, base = await _job(api, db_session)
        url = f"{base}/{job_id}/remarks"
        other = str(uuid.uuid4())
        cases = (
            {"job_id": other},
            {"revision_id": other},
            {"project_id": other},
            {"legacy_pdf_page": 5},
        )
        for patch in cases:
            response = await api.post(
                f"{url}/import", json=_file(project_id, revision_id, job_id, [_item("r1")], **patch)
            )
            assert response.status_code == 422, (patch, response.text)
            assert response.json()["detail"]["code"] == "CAD_REMARKS_BINDING_MISMATCH"
        assert (await api.get(f"{url}?{QUERY}")).json() == []

        # Чужая схема и приёмка=true — вне контракта файла.
        bad_schema = _file(project_id, revision_id, job_id, [], schema="other.v1")
        assert (await api.post(f"{url}/import", json=bad_schema)).status_code == 422
        accepted = _file(project_id, revision_id, job_id, [], engineering_acceptance=True)
        assert (await api.post(f"{url}/import", json=accepted)).status_code == 422
        # Не больше 500 замечаний.
        many = [_item(f"r{index}") for index in range(501)]
        too_many = await api.post(
            f"{url}/import", json=_file(project_id, revision_id, job_id, many)
        )
        assert too_many.status_code == 422


async def test_import_is_one_transaction(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    """Файл с одним невалидным замечанием не оставляет остальные: отказ до записи."""
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id, job_id, base = await _job(api, db_session)
        url = f"{base}/{job_id}/remarks"
        broken = _item("r2", bbox_pt=[5, 5, 1, 1])
        response = await api.post(
            f"{url}/import", json=_file(project_id, revision_id, job_id, [_item("r1"), broken])
        )
        assert response.status_code == 422
        assert (await api.get(f"{url}?{QUERY}")).json() == []


async def test_dxf_binding_is_checked_when_attempt_result_is_known(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id, job_id, base = await _job(api, db_session, attempt=1, dxf_sha=SHA)
        url = f"{base}/{job_id}/remarks"

        wrong = await api.post(
            f"{url}/import",
            json=_file(project_id, revision_id, job_id, [_item("r1")], dxf_sha256=OTHER_SHA),
        )
        assert wrong.status_code == 422
        assert "DXF" in wrong.json()["detail"]["message"]
        no_dxf = await api.post(
            f"{url}/import",
            json=_file(project_id, revision_id, job_id, [_item("r1")], dxf_sha256=None),
        )
        assert no_dxf.status_code == 422
        assert (
            await api.put(f"{url}/k1?{QUERY}", json=_body(dxf_sha256=OTHER_SHA))
        ).status_code == 422

        ok = await api.post(
            f"{url}/import",
            json=_file(project_id, revision_id, job_id, [_item("r1")], dxf_sha256=SHA),
        )
        assert ok.json() == {"imported": 1, "updated": 0}
        assert (await api.put(f"{url}/k1?{QUERY}", json=_body(dxf_sha256=SHA))).status_code == 200


async def test_attempt_out_of_range_is_404(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id, job_id, base = await _job(api, db_session, attempt=2)
        url = f"{base}/{job_id}/remarks"
        for attempt in (3, 99):
            query = f"attempt={attempt}&page_index=0&view=1"
            assert (await api.get(f"{url}?{query}")).status_code == 404
            assert (await api.put(f"{url}/k1?{query}", json=_body())).status_code == 404
            assert (await api.delete(f"{url}/k1?{query}")).status_code == 404
            file = _file(project_id, revision_id, job_id, [_item("r1")], attempt=attempt)
            assert (await api.post(f"{url}/import", json=file)).status_code == 404
        # Ноль и отрицательные номера отсекает проверка параметров.
        assert (await api.get(f"{url}?attempt=0&page_index=0&view=1")).status_code == 422
        zero = _file(project_id, revision_id, job_id, [_item("r1")], attempt=0)
        assert (await api.post(f"{url}/import", json=zero)).status_code == 404
        # Поставленное, но ещё не захваченное задание (attempt=0) замечаний не принимает.
        await db_session.execute(update(Job).where(Job.id == uuid.UUID(job_id)).values(attempt=0))
        await db_session.commit()
        assert (await api.get(f"{url}?{QUERY}")).status_code == 404


async def test_foreign_workspace_and_wrong_revision_get_404(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _job(api, db_session)
        url = f"{base}/{job_id}/remarks"
        await api.put(f"{url}/k1?{QUERY}", json=_body())
        _, other_revision = await _upload(api, b"%PDF-1.7\n" + b"1" * 512, "Другой.pdf")
        wrong = f"/api/v1/projects/{project_id}/revisions/{other_revision}/cad/{job_id}/remarks"
        assert (await api.get(f"{wrong}?{QUERY}")).status_code == 404

    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        file = _file(project_id, revision_id, job_id, [_item("r1")])
        assert (await foreign.get(f"{url}?{QUERY}")).status_code == 404
        assert (await foreign.put(f"{url}/k1?{QUERY}", json=_body())).status_code == 404
        assert (await foreign.delete(f"{url}/k1?{QUERY}")).status_code == 404
        assert (await foreign.post(f"{url}/import", json=file)).status_code == 404
    # Чужая попытка не тронула замечание.
    count = await db_session.scalar(select(func.count()).select_from(CadRemark))
    assert count == 1


async def test_flag_off_closes_remarks(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        _, _, job_id, base = await _job(api, db_session)
    closed = cad_settings(tmp_path, flag=False)
    async with build_api(make_context(), settings=closed) as api:
        response = await api.get(f"{base}/{job_id}/remarks?{QUERY}")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


def test_routes_exist_only_behind_qa_gate() -> None:
    suffixes = ("/remarks", "/remarks/{remark_key}", "/remarks/import")
    default: Settings = clean_settings()
    default_paths = create_app(default).openapi()["paths"]
    assert not any("remarks" in path for path in default_paths)
    gated = create_app(clean_settings(environment="test", cad_qa_enabled=True)).openapi()["paths"]
    for suffix in suffixes:
        assert (
            f"/api/v1/projects/{{project_id}}/revisions/{{revision_id}}/cad/{{job_id}}{suffix}"
            in gated
        )
