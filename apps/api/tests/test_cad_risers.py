"""Реестр стояков листа CAD (ADR-0041): API, границы доступа, валидация и канонический файл."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_risers import CadRiserEntry
from app.main import create_app
from app.models import CadSheetRisers, Workspace
from app.services import cad_risers
from tests.conftest import clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload, _upload_calibrated, cad_settings


def _riser(**patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "system": "V1",
        "mark": "В1.1.1",
        "dn_mm": 50,
        "role": "own",
        "count": 1,
        "shaft_id": None,
        "source": "ИОС2.1 л.2",
        "note": None,
    }
    body.update(patch)
    return body


def _query(revision_id: str, page_index: int = 0, view: int = 1) -> str:
    return f"?revision_id={revision_id}&page_index={page_index}&view={view}"


def test_risers_routes_are_in_openapi() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    assert set(paths["/api/v1/projects/{project_id}/cad/risers"]) == {"get", "put"}


def test_canonical_file_and_hash_are_stable() -> None:
    entry = CadRiserEntry.model_validate(_riser(mark="  Т3.1.1 ", source=" "))
    risers = cad_risers.entries_to_json([entry])
    assert risers[0]["mark"] == "Т3.1.1" and risers[0]["source"] is None
    raw = cad_risers.registry_bytes(risers)
    assert raw == json.dumps(
        {"schema": "cad_risers.v1", "risers": risers},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert raw.startswith(b'{"risers":[{"count":1,"dn_mm":50,')
    assert cad_risers.registry_sha256(risers) == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "patch",
    [
        {"system": "K1"},
        {"system": "heating"},
        {"mark": ""},
        {"mark": "   "},
        {"mark": "x" * 33},
        {"dn_mm": 9},
        {"dn_mm": 401},
        {"role": "other"},
        {"count": 0},
        {"count": 9},
        {"shaft_id": "S1"},
        {"shaft_id": "S1234"},
        {"shaft_id": "shaft12"},
        {"source": "x" * 201},
        {"note": "x" * 201},
        {"extra": 1},
    ],
)
def test_entry_contract_rejects_bad_values(patch: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        CadRiserEntry.model_validate(_riser(**patch))


def test_entry_contract_accepts_the_bounds() -> None:
    entry = CadRiserEntry.model_validate(
        _riser(dn_mm=None, count=8, shaft_id="S123", mark="x" * 32, source="y" * 200)
    )
    assert entry.dn_mm is None and entry.count == 8 and entry.shaft_id == "S123"
    assert CadRiserEntry.model_validate({"system": "FS", "mark": "В2.6", "role": "own"}).count == 1


async def test_get_empty_put_and_get_back(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = f"/api/v1/projects/{project_id}/cad/risers"
        query = _query(revision_id)

        empty = await api.get(f"{url}{query}")
        assert empty.status_code == 200, empty.text
        assert empty.json()["risers"] == [] and empty.json()["updated_at"] is None

        body = {
            "risers": [
                _riser(),
                _riser(system="VPV", mark="В2.1", dn_mm=65, count=2, shaft_id=" S12 "),
                _riser(system="T4", mark="Т4.1.1", source="", note=""),
            ]
        }
        saved = await api.put(f"{url}{query}", json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["updated_at"] is not None
        back = (await api.get(f"{url}{query}")).json()
        assert back["revision_id"] == revision_id
        assert (back["page_index"], back["view"]) == (0, 1)
        assert [r["mark"] for r in back["risers"]] == ["В1.1.1", "В2.1", "Т4.1.1"]
        assert back["risers"][1]["shaft_id"] == "S12" and back["risers"][1]["count"] == 2
        assert back["risers"][2]["source"] is None and back["risers"][2]["note"] is None

        # Другой вид и другая страница листа - свои реестры.
        assert (await api.get(f"{url}{_query(revision_id, view=2)}")).json()["risers"] == []
        assert (await api.get(f"{url}{_query(revision_id, page_index=3)}")).json()["risers"] == []

        # Повторная запись заменяет целиком (upsert), пустой список - реестра нет.
        await api.put(f"{url}{query}", json={"risers": [_riser(mark="В1.9.9")]})
        assert [r["mark"] for r in (await api.get(f"{url}{query}")).json()["risers"]] == ["В1.9.9"]
        cleared = await api.put(f"{url}{query}", json={"risers": []})
        assert cleared.status_code == 200 and cleared.json()["risers"] == []
        assert (await api.get(f"{url}{query}")).json()["risers"] == []
    assert await db_session.scalar(select(func.count()).select_from(CadSheetRisers)) == 1


async def test_put_validation(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = f"/api/v1/projects/{project_id}/cad/risers{_query(revision_id)}"
        full = {"risers": [_riser(mark=f"В{i}") for i in range(40)]}
        assert (await api.put(url, json=full)).status_code == 200
        for body in (
            {"risers": [_riser(mark=f"В{i}") for i in range(41)]},
            {"risers": [_riser(count=9)]},
            {"risers": [_riser(system="K1")]},
            {"risers": [_riser(dn_mm=5)]},
            {"risers": [_riser(shaft_id="12")]},
            {},
            {"risers": [], "extra": 1},
        ):
            response = await api.put(url, json=body)
            assert response.status_code == 422, (body, response.text)
        bad_query = f"/api/v1/projects/{project_id}/cad/risers?revision_id={revision_id}"
        assert (await api.get(bad_query)).status_code == 422
        assert (await api.get(f"{bad_query}&page_index=-1&view=0")).status_code == 422


async def test_flag_off_closes_the_routes(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = f"/api/v1/projects/{project_id}/cad/risers{_query(revision_id)}"
        assert (await api.put(url, json={"risers": [_riser()]})).status_code == 200
    async with build_api(make_context(), settings=cad_settings(tmp_path, flag=False)) as api:
        for response in (
            await api.get(url),
            await api.put(url, json={"risers": [_riser(mark="В1.2.1")]}),
        ):
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED"
    stored = (await db_session.scalars(select(CadSheetRisers))).one()
    assert [item["mark"] for item in stored.risers] == ["В1.1.1"]


async def test_foreign_workspace_and_wrong_revision_get_404(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = f"/api/v1/projects/{project_id}/cad/risers"
        assert (
            await api.put(f"{url}{_query(revision_id)}", json={"risers": [_riser()]})
        ).status_code == 200
        _, other_revision = await _upload(api, b"%PDF-1.7\n" + b"1" * 512, "Другой.pdf")
        assert (await api.get(f"{url}{_query(other_revision)}")).status_code == 404
        assert (
            await api.put(f"{url}{_query(other_revision)}", json={"risers": []})
        ).status_code == 404
        assert (await api.get(f"{url}{_query(str(uuid.uuid4()))}")).status_code == 404

    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        assert (await foreign.get(f"{url}{_query(revision_id)}")).status_code == 404
        assert (
            await foreign.put(f"{url}{_query(revision_id)}", json={"risers": []})
        ).status_code == 404
        wrong_project = f"/api/v1/projects/{uuid.uuid4()}/cad/risers{_query(revision_id)}"
        assert (await foreign.get(wrong_project)).status_code == 404
    stored = (await db_session.scalars(select(CadSheetRisers))).one()
    assert len(stored.risers) == 1
