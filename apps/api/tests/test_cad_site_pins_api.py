"""Ручная привязка корпуса к площадке: маршруты, права, флаг, замена и отзыв (ADR-0052)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import Role
from app.main import create_app
from app.models import Workspace
from tests.conftest import clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload_calibrated

FLAG_ON = clean_settings(environment="test", feature_flags="cad.export=true")
FLAG_OFF = clean_settings(environment="test", feature_flags="")


def _url(project_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/cad/building3d/site-pins{tail}"


def _body(revision_id: str, *, shift: float = 0.0, source_page: int = 0) -> dict[str, Any]:
    return {
        "source": {"revision_id": revision_id, "page_index": source_page, "view": 1},
        "target": {"revision_id": revision_id, "page_index": 5, "view": 1},
        "source_points": [{"x_mm": 0, "y_mm": 0}, {"x_mm": 20000, "y_mm": 0}],
        "target_points": [
            {"x_mm": 100000, "y_mm": 50000 + shift},
            {"x_mm": 100000, "y_mm": 70000 + shift},
        ],
        "note": "угол корпуса 5",
    }


def test_routes_are_in_openapi() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths["/api/v1/projects/{project_id}/cad/building3d/site-pins"]) == {"get", "post"}
    assert set(paths["/api/v1/projects/{project_id}/cad/building3d/site-pins/{pin_id}"]) == {
        "delete"
    }


async def test_flag_off_closes_all_routes(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=FLAG_OFF) as api:
        project = str(uuid.uuid4())
        assert (await api.get(_url(project))).status_code == 403
        assert (await api.post(_url(project), json={})).status_code == 403
        response = await api.delete(_url(project, f"/{uuid.uuid4()}"))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_create_list_replace_and_revoke(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=FLAG_ON) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        assert (await api.get(_url(project_id))).json() == {"items": []}
        created = await api.post(_url(project_id), json=_body(revision_id))
        assert created.status_code == 201, created.text
        first = created.json()
        assert first["rotation_deg"] == 90.0 and first["baseline_mm"] == 20000.0
        assert first["residual_mm"] == 0.0 and first["note"] == "угол корпуса 5"
        assert first["created_by_name"] is not None and first["revoked_at"] is None
        # Прежняя привязка листа-источника отзывается новой («заменён»).
        again = await api.post(_url(project_id), json=_body(revision_id, shift=300.0))
        assert again.status_code == 201, again.text
        listed = (await api.get(_url(project_id))).json()["items"]
        assert [item["id"] for item in listed] == [again.json()["id"]]
        # Отзыв: запись остаётся с отметкой, повторный отзыв - 409, чужой id - 404.
        revoked = await api.request(
            "DELETE", _url(project_id, f"/{again.json()['id']}"), json={"reason": "ошибся точкой"}
        )
        assert revoked.status_code == 200
        assert revoked.json()["revoke_reason"] == "ошибся точкой"
        assert (await api.get(_url(project_id))).json() == {"items": []}
        twice = await api.delete(_url(project_id, f"/{again.json()['id']}"))
        assert (twice.status_code, twice.json()["detail"]["code"]) == (409, "CAD_ALREADY_REVOKED")
        assert (await api.delete(_url(project_id, f"/{uuid.uuid4()}"))).status_code == 404
        # После отзыва лист можно привязать заново.
        assert (await api.post(_url(project_id), json=_body(revision_id))).status_code == 201


async def test_bad_points_are_refused_with_a_reason(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=FLAG_ON) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        short = _body(revision_id)
        short["source_points"][1]["x_mm"] = 3000
        short["target_points"][1]["y_mm"] = 53000
        response = await api.post(_url(project_id), json=short)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "CAD_SITE_PIN_INVALID"
        assert "слишком близко" in response.json()["detail"]["message"]
        stretched = _body(revision_id)
        stretched["target_points"][1]["y_mm"] = 71000
        response = await api.post(_url(project_id), json=stretched)
        assert response.status_code == 422 and "не совпадают" in response.text
        same = _body(revision_id)
        same["target"]["page_index"] = 0
        response = await api.post(_url(project_id), json=same)
        assert response.status_code == 422 and "один и тот же лист" in response.text
        assert (await api.get(_url(project_id))).json() == {"items": []}


async def test_revision_of_another_project_and_foreign_workspace_are_404(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
) -> None:
    second_id = second_workspace.id
    async with build_api(make_context(), settings=FLAG_ON) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        other_project, _other_revision = await _upload_calibrated(
            api, db_session, BROKEN_PDF, "Другой.pdf"
        )
        assert (await api.get(_url(str(uuid.uuid4())))).status_code == 404
        stranger_revision = _body(str(uuid.uuid4()))
        assert (await api.post(_url(project_id), json=stranger_revision)).status_code == 404
        pin = (await api.post(_url(project_id), json=_body(revision_id))).json()
        # Привязка не видна и не отзывается через другой проект.
        assert (await api.get(_url(other_project))).json() == {"items": []}
        assert (await api.delete(_url(other_project, f"/{pin['id']}"))).status_code == 404
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=FLAG_ON) as foreign:
        assert (await foreign.get(_url(project_id))).status_code == 404
        assert (await foreign.post(_url(project_id), json=_body(revision_id))).status_code == 404


async def test_viewer_reads_but_cannot_write(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=FLAG_ON) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        pin = (await api.post(_url(project_id), json=_body(revision_id))).json()
    viewer = make_context(Role.VIEWER, platform_admin=False)
    async with build_api(viewer, settings=FLAG_ON) as reader:
        listed = await reader.get(_url(project_id))
        assert listed.status_code == 200 and len(listed.json()["items"]) == 1
        assert (await reader.post(_url(project_id), json=_body(revision_id))).status_code == 403
        assert (await reader.delete(_url(project_id, f"/{pin['id']}"))).status_code == 403
