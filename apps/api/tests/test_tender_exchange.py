"""Обмен расчётами с TENDER (ADR-0051): выпуск базы, приём расчёта, версии, слои, права, флаги.

Приём расчёта проверяется на синтетическом выпуске базы, вставленном прямо в базу: движок CAD
для него не нужен. Выпуск базы собирается на настоящем листе (родитель `cad_pdf_convert` и
`cad_walls` на заглушках, как у тестов «Здания»): проверяются состав ZIP, зоны в мм вида и sha256.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import AuditAction, JobStatus, JobType, Role
from app.main import create_app
from app.models import (
    AuditEvent,
    CadConstructionProps,
    CadZone,
    Job,
    Project,
    TenderBaseRelease,
    TenderCalc,
    TenderCalcVersion,
    Workspace,
)
from app.services import projects as projects_service
from app.services.tender_calc_import import find_prices
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import _ready_sheet, walls_settings
from tests.test_cad_mep import _approve_and_queue, _parent, mep_settings

DXF_SHA = "d" * 64
RELEASE_MANIFEST_SHA = "a" * 64
REVISION = uuid.UUID("11111111-2222-3333-4444-555555555555")
VIEW_KEY = f"{REVISION}:0:1"
OTHER_VIEW_KEY = f"{REVISION}:5:1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _settings(**extra: object) -> Settings:
    return clean_settings(
        environment="test", feature_flags="tender.exchange=true,cad.export=true", **extra
    )


def _url(project_id: object, tail: str) -> str:
    return f"/api/v1/projects/{project_id}/tender/{tail}"


# --------------------------------------------------------------------------- синтетический выпуск


async def _project_with_release(
    session: AsyncSession,
    *,
    dxf_sha: str = DXF_SHA,
    current_dxf: str | None = DXF_SHA,
    bbox: list[int] | None = None,
) -> tuple[Project, TenderBaseRelease]:
    """Проект, выпуск базы с одним видом и (если `current_dxf`) задание с текущим DXF вида."""
    project = await projects_service.create_project(
        session, workspace_id=DEV_WORKSPACE_ID, name="Объект"
    )
    release = TenderBaseRelease(
        workspace_id=DEV_WORKSPACE_ID,
        project_id=project.id,
        number=1,
        comment="тест",
        released_by=None,
        include_dxf=False,
        views=[
            {
                "key": VIEW_KEY,
                "dir": "views/p0000-v1-11111111",
                "revision_id": str(REVISION),
                "page_index": 0,
                "view": 1,
                "job_id": str(uuid.uuid4()),
                "dxf_sha256": dxf_sha,
                "document_title": "АР1.1",
                "label": "К9 · С3 · 4 эт.",
                "corps": "9",
                "section": "3",
                "floors": ["К9 · С3 · 4 эт."],
                **({"bbox": bbox} if bbox is not None else {}),
            }
        ],
        package_key=f"projects/{project.id}/tender/base/x.zip",
        package_sha256="b" * 64,
        manifest_sha256=RELEASE_MANIFEST_SHA,
        size_bytes=10,
    )
    session.add(release)
    if current_dxf is not None:
        session.add(
            Job(
                workspace_id=DEV_WORKSPACE_ID,
                project_id=project.id,
                job_type=JobType.CAD_PDF_CONVERT,
                status=JobStatus.SUCCEEDED,
                attempt=1,
                payload={
                    "revision_id": str(REVISION),
                    "cad_result": {
                        "attempt": 1,
                        "pages": [{"index": 0, "views": [{"view": 1}]}],
                        "artifacts": [
                            {
                                "name": "views/p001_v01/plan_candidates.dxf",
                                "sha256": current_dxf,
                                "size": 1,
                            }
                        ],
                    },
                },
            )
        )
    await session.commit()
    return project, release


def _view_file(view_key: str = VIEW_KEY, *, dxf: str = DXF_SHA) -> dict[str, Any]:
    return {
        "schema": "quantor.tender_calc.view.v1",
        "view_key": view_key,
        "dxf_sha256": dxf,
        "floors": ["4", "5", "6"],
        "polylines": [
            {
                "id": "T1-1-a",
                "system": "heating",
                "layer": "T-OV-T1",
                "kind": "route",
                "shape": "round",
                "dn_mm": 20,
                "pts": [[0, 0, 100], [1000, 0, 100]],
                "insulation_mm": 0,
                "slope": None,
                "mark": None,
                "apt": "1",
                "note": "луч к конвектору",
            }
        ],
        "elements": [
            {
                "id": "KV-1",
                "system": "heating",
                "type": "terminal",
                "subtype": "convector",
                "layer": "T-OV-T1",
                "pos": [500, 0, 100],
                "axis": [1000, 0, 0],
                "w_mm": 1500,
                "length_mm": 300,
                "h_mm": 110,
                "dn_mm": None,
                "mark": "КВ-2",
                "apt": "1",
            }
        ],
    }


def _rows(qty: float = 100.5) -> list[dict[str, Any]]:
    return [
        {
            "code": "OV-PEX-16",
            "group": "Трубы",
            "name": "Труба PE-Xa 16×2,0",
            "unit": "м",
            "qty": qty,
            "basis": "geometry",
            "per_floor": [{"floor": "4", "qty": 10.0}],
            "view_keys": [VIEW_KEY],
            "note": "запас 10 % включён",
        },
        {
            "code": "OV-KV",
            "group": "Приборы",
            "name": "Конвектор КВ-2",
            "unit": "шт",
            "qty": 3,
            "basis": "schedule",
            "per_floor": [],
            "view_keys": [],
            "note": None,
        },
    ]


def build_package(
    project: Project,
    release: TenderBaseRelease,
    *,
    label: str = "v1",
    message: str = "",
    title: str = "Отопление жилой части",
    system: str = "heating",
    rows: list[dict[str, Any]] | None = None,
    questions: list[dict[str, Any]] | None = None,
    view: dict[str, Any] | None = None,
    fit_max: float = 12.0,
    fit_view_key: str = VIEW_KEY,
    manifest_patch: dict[str, Any] | None = None,
    extra_members: dict[str, bytes] | None = None,
    corrupt_sha: str | None = None,
) -> bytes:
    """ZIP пакета расчёта; `corrupt_sha` - файл, чей sha256 в `files` намеренно неверен."""
    members: dict[str, Any] = {
        "quantities.json": {
            "schema": "quantor.tender_calc.quantities.v1",
            "rows": rows if rows is not None else _rows(),
        },
        "views/p0000.json": view if view is not None else _view_file(),
    }
    if questions is not None:
        members["questions.json"] = {
            "schema": "quantor.tender_calc.questions.v1",
            "rows": questions,
        }
    raw = {name: json.dumps(data, ensure_ascii=False).encode() for name, data in members.items()}
    files = {name: _sha(data) for name, data in raw.items()}
    if corrupt_sha is not None:
        files[corrupt_sha] = "0" * 64
    manifest: dict[str, Any] = {
        "schema": "quantor.tender_calc.v1",
        "project_id": str(project.id),
        "base": {"release_id": str(release.id), "manifest_sha256": release.manifest_sha256},
        "calc": {"discipline": "mech", "system": system, "title": title},
        "version": {
            "label": label,
            "message": message,
            "author": "Кузьмин А.А.",
            "created_at": "2026-11-16T12:00:00Z",
        },
        "producer": {"skill": "raschet-otopleniya", "skill_ref": "2026-11-16", "tool": "t 1.0"},
        "fit": [
            {
                "view_key": fit_view_key,
                "method": "axes_affine",
                "axes": ["1", "9", "А", "Г"],
                "rms_mm": 5,
                "max_mm": fit_max,
            }
        ],
        "files": files,
    }
    manifest.update(manifest_patch or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for name, data in raw.items():
            archive.writestr(name, data)
        for name, data in (extra_members or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


async def _upload(api: AsyncClient, project: Project, data: bytes) -> Response:
    return await api.post(
        _url(project.id, "calcs/upload"),
        files={"file": ("calc.zip", data, "application/zip")},
    )


def _codes(response: Response) -> list[str]:
    return [item["code"] for item in response.json()["detail"]["violations"]]


# --------------------------------------------------------------------------- приём расчёта


async def test_upload_creates_version_and_stores_files(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    project, release = await _project_with_release(db_session)
    data = build_package(project, release, questions=[{"text": "Шаг 1,5 м", "ids": ["KV-1"]}])
    async with build_api(make_context(), settings=_settings()) as api:
        created = await _upload(api, project, data)
        assert created.status_code == 201, created.text
        body = created.json()
        assert (body["number"], body["status"], body["label"]) == (1, "active", "v1")
        assert body["base_release_number"] == 1 and body["quantity_rows"] == 2
        assert body["view_count"] == 1 and body["question_count"] == 1
        assert body["warning_count"] == 0

        version = (await db_session.execute(select(TenderCalcVersion))).scalar_one()
        assert version.package_sha256 == _sha(data)
        assert fake_storage.objects[version.package_key] == data
        (stored_view,) = version.views
        assert stored_view["polylines"] == 1 and stored_view["elements"] == 1
        assert stored_view["object_key"].endswith(f"/views/{REVISION}_0_1.json")
        assert stored_view["object_key"] in fake_storage.objects
        calc = (await db_session.execute(select(TenderCalc))).scalar_one()
        assert (calc.discipline, calc.system, calc.title) == (
            "mech",
            "heating",
            "Отопление жилой части",
        )

        detail = (await api.get(_url(project.id, f"calc-versions/{body['id']}"))).json()
        assert detail["views"][0]["base_stale"] is False
        assert detail["prev_version_id"] is None and detail["diff"] == []
        assert detail["quantities"][0]["code"] == "OV-PEX-16"
        assert detail["questions"] == [{"text": "Шаг 1,5 м", "ref": None, "ids": ["KV-1"]}]
        assert detail["producer"]["skill"] == "raschet-otopleniya"

        listed = (await api.get(_url(project.id, "calcs"))).json()["calcs"]
        assert len(listed) == 1
        assert listed[0]["version_count"] == 1 and listed[0]["active_version"]["id"] == body["id"]

    actions = (await db_session.execute(select(AuditEvent.action))).scalars().all()
    assert AuditAction.TENDER_CALC_UPLOADED.value in actions


async def test_same_package_is_the_same_version(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    data = build_package(project, release)
    async with build_api(make_context(), settings=_settings()) as api:
        first = await _upload(api, project, data)
        again = await _upload(api, project, data)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    versions = (await db_session.execute(select(TenderCalcVersion))).scalars().all()
    assert len(versions) == 1
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == AuditAction.TENDER_CALC_UPLOADED.value
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1


async def test_new_version_supersedes_previous_and_diffs_quantities(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    first_rows = _rows(100.0)
    second_rows = [
        {**_rows()[0], "qty": 125.5},
        {
            "code": "OV-NEW",
            "group": None,
            "name": "Клапан",
            "unit": "шт",
            "qty": 4,
            "basis": "geometry",
            "per_floor": [],
            "view_keys": [],
            "note": None,
        },
    ]
    async with build_api(make_context(), settings=_settings()) as api:
        one = await _upload(api, project, build_package(project, release, rows=first_rows))
        two = await _upload(
            api, project, build_package(project, release, label="v2", rows=second_rows)
        )
        assert (one.status_code, two.status_code) == (201, 201)
        assert two.json()["number"] == 2

        versions = (
            await api.get(_url(project.id, f"calcs/{two.json()['calc_id']}/versions"))
        ).json()["versions"]
        assert [(v["number"], v["status"]) for v in versions] == [(2, "active"), (1, "superseded")]

        detail = (await api.get(_url(project.id, f"calc-versions/{two.json()['id']}"))).json()
        assert detail["prev_version_id"] == one.json()["id"]
        by_code = {row["code"]: row for row in detail["diff"]}
        assert by_code["OV-PEX-16"] == {
            "code": "OV-PEX-16",
            "name": "Труба PE-Xa 16×2,0",
            "unit": "м",
            "qty_prev": 100.0,
            "qty": 125.5,
            "delta": 25.5,
            "status": "changed",
        }
        assert by_code["OV-NEW"]["status"] == "added" and by_code["OV-NEW"]["qty_prev"] is None
        assert by_code["OV-KV"]["status"] == "removed" and by_code["OV-KV"]["qty"] is None

        same = await _upload(
            api, project, build_package(project, release, label="v3", rows=second_rows)
        )
        same_detail = (await api.get(_url(project.id, f"calc-versions/{same.json()['id']}"))).json()
        assert {row["status"] for row in same_detail["diff"]} == {"same"}

    active = (
        (
            await db_session.execute(
                select(TenderCalcVersion).where(TenderCalcVersion.status == "active")
            )
        )
        .scalars()
        .all()
    )
    assert [v.number for v in active] == [3]


async def test_price_in_package_is_refused_with_file_path(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    priced_key = [{**_rows()[0], "price": 150}]
    priced_value = [{**_rows()[0], "note": "Стоимость 1200 руб."}]
    async with build_api(make_context(), settings=_settings()) as api:
        by_key = await _upload(api, project, build_package(project, release, rows=priced_key))
        by_value = await _upload(api, project, build_package(project, release, rows=priced_value))
    for response in (by_key, by_value):
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "TENDER_PRICE_FORBIDDEN"
        (violation,) = detail["violations"]
        assert violation["code"] == "TENDER_PRICE_FORBIDDEN"
        assert violation["path"].startswith("quantities.json: rows[0]")
    assert (await db_session.execute(select(TenderCalcVersion))).first() is None


def test_price_scan_does_not_mistake_pipes_for_rubles() -> None:
    clean = {"name": "Труба стальная ВГП, рубероид, центральный стояк", "unit": "м"}
    assert find_prices(clean) == []
    assert find_prices({"cost": 1})
    assert find_prices({"a": ["цена 5"]})
    assert find_prices({"a": "1200 ₽"})
    assert find_prices({"note": "НДС 20 %"})
    assert find_prices({"price_total": 1})
    assert find_prices({"a": "12 руб."})


async def test_unsafe_and_foreign_files_are_refused(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    async with build_api(make_context(), settings=_settings()) as api:
        traversal = await _upload(
            api, project, build_package(project, release, extra_members={"../evil.json": b"{}"})
        )
        sheet = await _upload(
            api, project, build_package(project, release, extra_members={"смета.xlsx": b"PK"})
        )
        garbage = await _upload(api, project, b"not a zip at all")
        bomb = await _upload(
            api,
            project,
            build_package(project, release, extra_members={"views/zeros.json": b"0" * 4_000_000}),
        )
    for response in (traversal, sheet, garbage, bomb):
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "TENDER_PACKAGE_INVALID"
    assert (await db_session.execute(select(TenderCalcVersion))).first() is None


async def test_foreign_view_project_and_base_are_refused(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    other = await projects_service.create_project(
        db_session, workspace_id=DEV_WORKSPACE_ID, name="Другой"
    )
    await db_session.commit()
    async with build_api(make_context(), settings=_settings()) as api:
        view = await _upload(
            api,
            project,
            build_package(
                project,
                release,
                view=_view_file(OTHER_VIEW_KEY),
                fit_view_key=OTHER_VIEW_KEY,
                rows=[{**_rows()[0], "view_keys": [OTHER_VIEW_KEY]}],
            ),
        )
        mismatch = await _upload(
            api,
            project,
            build_package(project, release, manifest_patch={"project_id": str(other.id)}),
        )
        unknown_base = await _upload(
            api,
            project,
            build_package(
                project,
                release,
                manifest_patch={
                    "base": {"release_id": str(uuid.uuid4()), "manifest_sha256": "a" * 64}
                },
            ),
        )
        wrong_manifest = await _upload(
            api,
            project,
            build_package(
                project,
                release,
                manifest_patch={
                    "base": {"release_id": str(release.id), "manifest_sha256": "c" * 64}
                },
            ),
        )
    assert view.json()["detail"]["code"] == "TENDER_VIEW_UNKNOWN"
    assert len(view.json()["detail"]["violations"]) == 3  # файл вида, fit, строка объёмов
    assert _codes(mismatch) == ["TENDER_PROJECT_MISMATCH"]
    assert _codes(unknown_base) == ["TENDER_BASE_UNKNOWN"]
    assert _codes(wrong_manifest) == ["TENDER_BASE_UNKNOWN"]


async def test_revoked_base_release_is_refused(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    async with build_api(make_context(), settings=_settings()) as api:
        revoked = await api.post(_url(project.id, f"base/releases/{release.id}/revoke"))
        assert revoked.status_code == 200 and revoked.json()["revoked_at"] is not None
        again = await api.post(_url(project.id, f"base/releases/{release.id}/revoke"))
        assert again.json()["revoked_at"] == revoked.json()["revoked_at"]
        refused = await _upload(api, project, build_package(project, release))
    assert refused.status_code == 422 and _codes(refused) == ["TENDER_BASE_UNKNOWN"]
    revokes = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == AuditAction.TENDER_BASE_REVOKED.value)
        )
    ).all()
    assert len(revokes) == 1


async def test_fit_over_limit_is_refused_and_over_warning_is_a_warning(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    async with build_api(make_context(), settings=_settings()) as api:
        too_large = await _upload(api, project, build_package(project, release, fit_max=600))
        warned = await _upload(api, project, build_package(project, release, fit_max=150))
        detail = (await api.get(_url(project.id, f"calc-versions/{warned.json()['id']}"))).json()
    assert too_large.status_code == 422 and _codes(too_large) == ["TENDER_FIT_TOO_LARGE"]
    assert warned.status_code == 201
    assert [w["code"] for w in detail["warnings"]] == ["fit_over_100"]
    assert detail["warnings"][0]["view_key"] == VIEW_KEY


async def test_stale_base_is_accepted_with_warning_and_flagged(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    """Вид перестроен после выпуска: текущий DXF другой - расчёт принят, база устарела."""
    project, release = await _project_with_release(db_session, current_dxf="e" * 64)
    async with build_api(make_context(), settings=_settings()) as api:
        created = await _upload(api, project, build_package(project, release))
        assert created.status_code == 201
        detail = (await api.get(_url(project.id, f"calc-versions/{created.json()['id']}"))).json()
        assert [w["code"] for w in detail["warnings"]] == ["base_stale"]
        assert detail["views"][0]["base_stale"] is True

        geometry = await api.get(
            _url(project.id, f"calc-versions/{created.json()['id']}/views/{REVISION}/0/1")
        )
        assert geometry.status_code == 200 and geometry.json()["base_stale"] is True
        layers = await api.get(
            _url(project.id, f"view-layers?revision_id={REVISION}&page_index=0&view=1")
        )
        assert layers.json()["layers"][0]["base_stale"] is True


async def test_objects_outside_view_bbox_are_a_warning(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    """Объект дальше рамки вида базы на 1 м - предупреждение; в рамке - нет."""
    project, release = await _project_with_release(db_session, bbox=[0, 0, 2000, 2000])
    far_view = _view_file()
    far_view["elements"][0]["pos"] = [50000, 0, 100]
    far_view["polylines"][0]["pts"] = [[0, 0, 100], [0, 9000, 100]]
    async with build_api(make_context(), settings=_settings()) as api:
        inside = await _upload(api, project, build_package(project, release))
        outside = await _upload(
            api, project, build_package(project, release, label="v2", view=far_view)
        )
        inside_detail = (
            await api.get(_url(project.id, f"calc-versions/{inside.json()['id']}"))
        ).json()
        outside_detail = (
            await api.get(_url(project.id, f"calc-versions/{outside.json()['id']}"))
        ).json()
    assert inside_detail["warnings"] == []
    assert [w["code"] for w in outside_detail["warnings"]] == ["out_of_bbox"]
    assert outside_detail["warnings"][0]["view_key"] == VIEW_KEY
    assert outside_detail["warnings"][0]["message"].startswith("views/p0000.json: 2 объектов")


async def test_release_without_bbox_skips_out_of_bbox_check(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    far_view = _view_file()
    far_view["elements"][0]["pos"] = [50000, 0, 100]
    async with build_api(make_context(), settings=_settings()) as api:
        created = await _upload(api, project, build_package(project, release, view=far_view))
        detail = (await api.get(_url(project.id, f"calc-versions/{created.json()['id']}"))).json()
    assert detail["warnings"] == []


async def test_assumption_without_question_is_a_warning(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    rows = [{**_rows()[0], "basis": "assumption", "note": "допущение"}]
    async with build_api(make_context(), settings=_settings()) as api:
        bare = await _upload(api, project, build_package(project, release, rows=rows))
        asked = await _upload(
            api,
            project,
            build_package(
                project,
                release,
                label="v2",
                rows=rows,
                questions=[{"text": "Принят запас", "ids": ["OV-PEX-16"]}],
            ),
        )
        bare_detail = (await api.get(_url(project.id, f"calc-versions/{bare.json()['id']}"))).json()
        asked_detail = (
            await api.get(_url(project.id, f"calc-versions/{asked.json()['id']}"))
        ).json()
    assert [w["code"] for w in bare_detail["warnings"]] == ["assumption_without_question"]
    assert asked_detail["warnings"] == []


async def test_all_violations_are_reported_at_once(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    bad_view = _view_file()
    bad_view["polylines"][0]["layer"] = "M-OV-T1"  # префикс движка вместо T-
    bad_view["unknown"] = 1
    data = build_package(
        project,
        release,
        rows=[{**_rows()[0], "price": 1}],
        view=bad_view,
        fit_max=700,
        corrupt_sha="quantities.json",
    )
    async with build_api(make_context(), settings=_settings()) as api:
        response = await _upload(api, project, data)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "TENDER_PACKAGE_INVALID"
    codes = set(_codes(response))
    assert {"TENDER_PRICE_FORBIDDEN", "TENDER_PACKAGE_INVALID", "TENDER_FIT_TOO_LARGE"} <= codes
    paths = [item["path"] for item in detail["violations"]]
    assert any(path.startswith("views/p0000.json") for path in paths)
    assert any(path.startswith("quantities.json") for path in paths)


async def test_files_sha256_must_match_manifest(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    async with build_api(make_context(), settings=_settings()) as api:
        response = await _upload(
            api, project, build_package(project, release, corrupt_sha="views/p0000.json")
        )
    assert response.status_code == 422
    (violation,) = response.json()["detail"]["violations"]
    assert violation["path"] == "views/p0000.json"
    assert "sha256" in violation["message"]


async def test_withdraw_hides_the_version_and_requires_coordinator(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    async with build_api(make_context(), settings=_settings()) as api:
        created = await _upload(api, project, build_package(project, release))
    version_id = created.json()["id"]
    withdraw = _url(project.id, f"calc-versions/{version_id}/withdraw")

    engineer = make_context(Role.ENGINEER, platform_admin=False)
    async with build_api(engineer, settings=_settings()) as api:
        denied = await api.post(withdraw)
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "PERMISSION_DENIED"

    coordinator = make_context(Role.WORKSPACE_ADMIN, platform_admin=False)
    async with build_api(coordinator, settings=_settings()) as api:
        done = await api.post(withdraw)
        assert done.status_code == 200 and done.json()["status"] == "withdrawn"
        assert (await api.post(withdraw)).json()["status"] == "withdrawn"
        calcs = (await api.get(_url(project.id, "calcs"))).json()["calcs"]
        assert calcs[0]["active_version"] is None and calcs[0]["version_count"] == 1
        layers = await api.get(
            _url(project.id, f"view-layers?revision_id={REVISION}&page_index=0&view=1")
        )
        assert layers.json() == {"layers": []}
        assert (await api.get(_url(project.id, "building-layers"))).json() == {"layers": []}
    events = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == AuditAction.TENDER_CALC_WITHDRAWN.value)
        )
    ).all()
    assert len(events) == 1


async def test_layers_geometry_and_package_download(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
) -> None:
    project, release = await _project_with_release(db_session)
    data = build_package(project, release)
    async with build_api(make_context(), settings=_settings()) as api:
        created = await _upload(api, project, data)
        version_id = created.json()["id"]

        geometry = (
            await api.get(_url(project.id, f"calc-versions/{version_id}/views/{REVISION}/0/1"))
        ).json()
        assert geometry["floors"] == ["4", "5", "6"]
        assert geometry["polylines"][0]["pts"] == [[0, 0, 100], [1000, 0, 100]]
        assert geometry["elements"][0]["subtype"] == "convector"
        assert geometry["base_stale"] is False
        missing = await api.get(
            _url(project.id, f"calc-versions/{version_id}/views/{REVISION}/9/1")
        )
        assert missing.status_code == 404

        layers = (
            await api.get(
                _url(project.id, f"view-layers?revision_id={REVISION}&page_index=0&view=1")
            )
        ).json()["layers"]
        assert len(layers) == 1
        layer = layers[0]
        assert (layer["system"], layer["title"], layer["number"], layer["label"]) == (
            "heating",
            "Отопление жилой части",
            1,
            "v1",
        )
        assert layer["polylines"][0]["id"] == "T1-1-a" and layer["base_stale"] is False
        none = await api.get(
            _url(project.id, f"view-layers?revision_id={REVISION}&page_index=7&view=1")
        )
        assert none.json() == {"layers": []}

        building = (await api.get(_url(project.id, "building-layers"))).json()["layers"]
        assert building[0]["view_keys"] == [VIEW_KEY] and building[0]["version_id"] == version_id

        package = await api.get(_url(project.id, f"calc-versions/{version_id}/package"))
        assert package.status_code == 200 and package.content == data
        assert package.headers["x-content-sha256"] == _sha(data)
        assert "attachment" in package.headers["content-disposition"]


# --------------------------------------------------------------------------- права, флаг, граница


async def test_permissions_by_role(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    project, release = await _project_with_release(db_session)
    data = build_package(project, release)
    viewer = make_context(Role.VIEWER, platform_admin=False)
    async with build_api(viewer, settings=_settings()) as api:
        assert (await api.get(_url(project.id, "calcs"))).status_code == 200
        assert (await api.get(_url(project.id, "base/releases"))).status_code == 200
        for method, tail in (
            ("POST", "calcs/upload"),
            ("GET", "base/candidates"),
            ("POST", "base/releases"),
            ("POST", f"base/releases/{release.id}/revoke"),
        ):
            response = await api.request(method, _url(project.id, tail))
            assert response.status_code == 403, (method, tail)
            assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
    engineer = make_context(Role.ENGINEER, platform_admin=False)
    async with build_api(engineer, settings=_settings()) as api:
        assert (await _upload(api, project, data)).status_code == 201
        assert (await api.get(_url(project.id, "base/candidates"))).status_code == 403
        released = await api.post(_url(project.id, "base/releases"), json={"include_dxf": False})
        assert released.status_code == 403


async def test_exchange_is_closed_by_the_flag_and_by_workspace(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
) -> None:
    project, release = await _project_with_release(db_session)
    off = clean_settings(environment="test", feature_flags="cad.export=true")
    async with build_api(make_context(), settings=off) as api:
        for method, tail in (
            ("GET", "calcs"),
            ("GET", "base/releases"),
            ("POST", "calcs/upload"),
            ("GET", "building-layers"),
        ):
            response = await api.request(method, _url(project.id, tail))
            assert response.status_code == 403, (method, tail)
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED"
    stranger = make_context(
        Role.WORKSPACE_ADMIN, platform_admin=False, workspace_id=second_workspace.id
    )
    async with build_api(stranger, settings=_settings()) as api:
        assert (await api.get(_url(project.id, "calcs"))).status_code == 404
        assert (await api.get(_url(project.id, f"base/releases/{release.id}"))).status_code == 404
        assert (await _upload(api, project, build_package(project, release))).status_code == 404


def test_routes_are_in_openapi() -> None:
    paths = create_app(_settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/tender"
    expected = {
        f"{base}/base/candidates": {"get"},
        f"{base}/base/releases": {"get", "post"},
        f"{base}/base/releases/{{release_id}}": {"get"},
        f"{base}/base/releases/{{release_id}}/download": {"get"},
        f"{base}/base/releases/{{release_id}}/revoke": {"post"},
        f"{base}/calcs/upload": {"post"},
        f"{base}/calcs": {"get"},
        f"{base}/calcs/{{calc_id}}/versions": {"get"},
        f"{base}/calc-versions/{{version_id}}": {"get"},
        f"{base}/calc-versions/{{version_id}}/views/{{revision_id}}/{{page_index}}/{{view}}": {
            "get"
        },
        f"{base}/calc-versions/{{version_id}}/package": {"get"},
        f"{base}/calc-versions/{{version_id}}/withdraw": {"post"},
        f"{base}/view-layers": {"get"},
        f"{base}/building-layers": {"get"},
        "/api/v1/me/api-tokens": {"get", "post"},
        "/api/v1/me/api-tokens/{token_id}": {"delete"},
    }
    for path, methods in expected.items():
        assert set(paths[path]) == methods, path


# --------------------------------------------------------------------------- трассы движка


async def test_mep_engine_routes_are_closed_by_their_own_flag(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    tools = tmp_path / "t"
    (tools / "params").mkdir(parents=True)
    (tools / "params" / "v1.json").write_text("{}", encoding="utf-8")
    off = mep_settings(tools, tmp_path, mep_engine=False)
    job_id = uuid.uuid4()
    base = f"/api/v1/projects/{uuid.uuid4()}/revisions/{uuid.uuid4()}/cad/{job_id}"
    async with build_api(make_context(), settings=off) as api:
        for tail, body in (
            ("views/0/1/mep-routes", {"attempt": 1}),
            ("recompute", {}),
        ):
            response = await api.post(f"{base}/{tail}", json=body)
            assert response.status_code == 409, (tail, response.text)
            assert response.json()["detail"]["code"] == "CAD_MEP_ENGINE_DISABLED"
        # Чтение прежних трасс флагом не закрывается: трасс нет - 404, а не 409.
        read = await api.get(
            f"/api/v1/projects/{uuid.uuid4()}/cad/mep/routes3d"
            f"?revision_id={uuid.uuid4()}&page_index=0&view=1"
        )
        assert read.status_code in (404, 200)
        assert read.json().get("detail", {}).get("code") != "CAD_MEP_ENGINE_DISABLED"

    on = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=on) as api:
        response = await api.post(f"{base}/views/0/1/mep-routes", json={"attempt": 1})
        assert response.status_code == 404  # флаг открыт: дальше обычная проверка проекта


async def test_mep_engine_routes_work_with_the_flag_on(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    """Контроль: с включённым флагом постановка трасс проходит так же, как раньше."""
    from tests.test_cad_mep import STUB

    tools = tmp_path / "tools" / "cad_mep"
    (tools / "params").mkdir(parents=True)
    (tools / "cad_mep").mkdir()
    (tools / "params" / "v1.json").write_text(json.dumps({}), encoding="utf-8")
    (tools / "run_mep.py").write_text(STUB, encoding="utf-8")
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _project_id, _revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        queued = await _approve_and_queue(api, base, job_id)
    assert queued


# --------------------------------------------------------------------------- выпуск базы


def _flags(settings: Settings, extra: str) -> Settings:
    return settings.model_copy(update={"feature_flags": f"{settings.feature_flags},{extra}"})


async def _sheet_with_zone(
    api: AsyncClient,
    session: AsyncSession,
    storage: FakeObjectStorage,
    settings: Settings,
) -> tuple[str, str, str]:
    project_id, revision_id, job_id, _walls = await _ready_sheet(api, session, storage, settings)
    session.add(
        CadZone(
            workspace_id=DEV_WORKSPACE_ID,
            project_id=uuid.UUID(project_id),
            revision_id=uuid.UUID(revision_id),
            page_index=0,
            kind="room_apartment",
            apartment_no="15.1",
            room_mark="1",
            name="Кухня-гостиная",
            points=[[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]],
        )
    )
    session.add(
        CadConstructionProps(
            workspace_id=DEV_WORKSPACE_ID,
            revision_id=uuid.UUID(revision_id),
            page_index=0,
            view=1,
            construction_key="aaaaaaaaaaaa",
            props={"material": "aerated_concrete", "thickness_override_mm": 250},
            accepted=True,
        )
    )
    session.add(
        CadConstructionProps(
            workspace_id=DEV_WORKSPACE_ID,
            revision_id=uuid.UUID(revision_id),
            page_index=0,
            view=1,
            construction_key="bbbbbbbbbbbb",
            props={"material": "brick_solid"},
            accepted=False,
        )
    )
    await session.commit()
    return project_id, revision_id, job_id


@pytest.fixture
def walls_tools_dir(tmp_path: Path) -> Path:
    from tests.test_cad_constructions_api import PARAMS, STUB

    root = tmp_path / "tools" / "cad_walls"
    (root / "params").mkdir(parents=True)
    (root / "cad_walls").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "run_walls.py").write_text(STUB, encoding="utf-8")
    return root


async def test_base_release_builds_a_checked_package(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools_dir: Path,
    tmp_path: Path,
) -> None:
    settings = _flags(walls_settings(walls_tools_dir, tmp_path), "tender.exchange=true")
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, _job_id = await _sheet_with_zone(
            api, db_session, fake_storage, settings
        )
        candidates = (await api.get(_url(project_id, "base/candidates"))).json()
        (candidate,) = candidates["candidates"]
        view_key = f"{revision_id}:0:1"
        assert candidate["view_key"] == view_key and candidate["ready"] is True
        assert candidate["dir"] == f"p0000-v1-{revision_id[:8]}"
        assert candidate["problems"] == []

        created = await api.post(
            _url(project_id, "base/releases"),
            json={"view_keys": [view_key], "include_dxf": True, "comment": "Корп. 9"},
        )
        assert created.status_code == 201, created.text
        release = created.json()
        assert release["number"] == 1 and release["include_dxf"] is True
        assert release["views"][0]["key"] == view_key and release["comment"] == "Корп. 9"

        download = await api.get(_url(project_id, f"base/releases/{release['id']}/download"))
        assert download.status_code == 200
        assert _sha(download.content) == release["package_sha256"]
        assert "quantor-base-1-" in download.headers["content-disposition"]

        second = await api.post(_url(project_id, "base/releases"), json={})
        assert second.status_code == 201 and second.json()["number"] == 2
        assert second.json()["include_dxf"] is False
        listed = (await api.get(_url(project_id, "base/releases"))).json()
        assert [r["number"] for r in listed] == [2, 1]

        # Агенту - одним запросом: координационный файл последнего действующего выпуска (№ 2).
        coord_json = await api.get(_url(project_id, "base/coordination.json"))
        assert coord_json.status_code == 200, coord_json.text
        assert coord_json.headers["x-quantor-base-release"] == "2"
        assert coord_json.json()["schema"] == "quantor.object_base.coordination.v1"
        coord_ifc = await api.get(_url(project_id, "base/coordination.ifc"))
        assert coord_ifc.status_code == 200 and coord_ifc.text.startswith("ISO-10303-21;")
        assert (await api.get(_url(project_id, "base/coordination.dwg"))).status_code == 422

    archive = zipfile.ZipFile(io.BytesIO(download.content))
    names = set(archive.namelist())
    folder = f"views/p0000-v1-{revision_id[:8]}"
    assert names == {
        "manifest.json",
        "building.json",
        "coordination.json",
        "coordination.ifc",
        f"{folder}/view.json",
        f"{folder}/axes.json",
        f"{folder}/zones.json",
        f"{folder}/constructions.json",
        f"{folder}/plan.dxf",
    }
    manifest = json.loads(archive.read("manifest.json"))
    assert _sha(archive.read("manifest.json")) == release["manifest_sha256"]
    assert manifest["schema"] == "quantor.object_base.v1"
    assert (manifest["units"], manifest["frame"], manifest["z_reference"]) == (
        "mm",
        "view_dxf_mm",
        "finished_floor",
    )
    assert manifest["release"]["number"] == 1 and manifest["release"]["comment"] == "Корп. 9"
    assert manifest["project"]["id"] == project_id
    # sha256 каждого файла в манифесте совпадает с содержимым, а сам манифест в files не входит.
    assert set(manifest["files"]) == names - {"manifest.json"}
    for name, sha in manifest["files"].items():
        assert _sha(archive.read(name)) == sha, name
    (view_row,) = manifest["views"]
    assert view_row["key"] == view_key and view_row["dir"] == folder
    assert view_row["dxf_sha256"] == _sha(archive.read(f"{folder}/plan.dxf"))

    view = json.loads(archive.read(f"{folder}/view.json"))
    frame = view["frame"]
    assert view["key"] == view_key and frame["confirmed"] is True
    assert frame["page_size_pt"] == [1190.55, 841.89]
    assert view["level"]["floor_elevation_mm"] == 47600 and view["level"]["floor_height_mm"] == 3000
    assert view["level"]["elevation_known"] is True
    assert view["placement"]["alignment"] in ("reference", "none")

    # Зона квартиры в мм кадра вида: нормализованные доли -> пункты -> мм (Y вверх).
    (zone,) = json.loads(archive.read(f"{folder}/zones.json"))["zones"]
    assert (zone["kind"], zone["apartment_no"], zone["name"]) == (
        "room_apartment",
        "15.1",
        "Кухня-гостиная",
    )
    ox, oy = frame["origin_pt"]
    factor = frame["mm_per_pdf_point"]
    width, height = frame["page_size_pt"]
    expected = [
        [round((nx * width - ox) * factor), round(-(ny * height - oy) * factor)]
        for nx, ny in [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]]
    ]
    assert zone["points"] == expected
    assert zone["area_m2"] > 0 and zone["room_type"] == "kitchen"

    # Конструкции: принятые свойства применены, непринятые - нет.
    constructions = json.loads(archive.read(f"{folder}/constructions.json"))
    by_id = {c["id"]: c for c in constructions["constructions"]}
    assert by_id["aaaaaaaaaaaa"]["material"] == "газобетон"
    assert by_id["aaaaaaaaaaaa"]["thickness_mm"] == 250
    assert (
        by_id["bbbbbbbbbbbb"]["material"] is None and by_id["bbbbbbbbbbbb"]["thickness_mm"] == 100
    )
    assert by_id["cccccccccccc"]["thickness_mm"] is None
    assert {o["id"] for o in constructions["openings"]} == {"door00000001", "gap000000001"}

    building = json.loads(archive.read("building.json"))
    assert [f["view_key"] for f in building["floors"]] == [view_key]
    assert building["floors"][0]["base_z_mm"] == 47600

    # Координационный файл: этаж выпуска на своей отметке, IFC - текст STEP со своими этажами.
    coordination = json.loads(archive.read("coordination.json"))
    assert coordination["schema"] == "quantor.object_base.coordination.v1"
    (group,) = coordination["groups"]
    assert [s["base_z_mm"] for s in group["storeys"]] == [47600]
    assert group["storeys"][0]["view_keys"] == [view_key]
    ifc = archive.read("coordination.ifc").decode("ascii")
    assert ifc.startswith("ISO-10303-21;") and "FILE_SCHEMA(('IFC4'));" in ifc
    assert ifc.count("IFCBUILDINGSTOREY(") == 1

    stored = (
        (await db_session.execute(select(TenderBaseRelease).order_by(TenderBaseRelease.number)))
        .scalars()
        .all()
    )
    assert [r.number for r in stored] == [1, 2]
    assert stored[0].manifest_sha256 == release["manifest_sha256"]
    assert fake_storage.objects[stored[0].package_key] == download.content
    events = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == AuditAction.TENDER_BASE_RELEASED.value)
        )
    ).all()
    assert len(events) == 2


async def test_base_release_refuses_unknown_view_and_empty_project(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    walls_tools_dir: Path,
    tmp_path: Path,
) -> None:
    settings = _flags(walls_settings(walls_tools_dir, tmp_path), "tender.exchange=true")
    project = await projects_service.create_project(
        db_session, workspace_id=DEV_WORKSPACE_ID, name="Пустой"
    )
    await db_session.commit()
    async with build_api(make_context(), settings=settings) as api:
        empty = await api.post(_url(project.id, "base/releases"), json={})
        assert empty.status_code == 422
        assert empty.json()["detail"]["code"] == "VALIDATION_FAILED"
        unknown = await api.post(
            _url(project.id, "base/releases"), json={"view_keys": [OTHER_VIEW_KEY]}
        )
        assert unknown.status_code == 422
        bad_key = await api.post(_url(project.id, "base/releases"), json={"view_keys": ["x"]})
        assert bad_key.status_code == 422
        candidates = (await api.get(_url(project.id, "base/candidates"))).json()
        assert candidates["candidates"] == []


def test_view_and_candidate_carry_floor_rotation_for_object_base() -> None:
    """Размещение вида в базе несёт поворот: `p = R(rotation_deg) · p_вида + offset_mm`."""
    from unittest.mock import MagicMock

    from app.contracts.cad import CadFrameRead
    from app.services import cad_building3d as b3d
    from app.services import tender_base
    from tests.test_cad_building3d import built, ref_axes, turned_view

    reference = built(axes=ref_axes())
    _ref, floor = b3d.align_floors([reference, turned_view(reference, 90, (1500, -700))])
    assert floor.rotation_deg == 90.0
    source = tender_base.ViewSource(
        key=f"{uuid.uuid4()}:0:1",
        dir="views/p0000-v1-aaaaaaaa",
        floor=floor,
        sheet=MagicMock(),
        job=MagicMock(),
        document_title="План",
        dxf_sha256=None,
        dxf_key=None,
        frame=CadFrameRead(
            confirmed=True,
            reason=None,
            units="mm",
            origin_pt=(10.0, 20.0),
            mm_per_pdf_point=1.0,
        ),
        page_size_pt=(1190.55, 841.89),
    )
    view = tender_base.build_view(source).model_dump(by_alias=True)
    assert view["placement"]["rotation_deg"] == 90.0
    assert view["placement"]["offset_mm"] == [round(floor.offset_mm[0]), round(floor.offset_mm[1])]
    assert tender_base.candidate_read(source).rotation_deg == 90.0


def test_view_bbox_is_in_view_frame_not_building() -> None:
    """Рамка вида в базе - в мм кадра вида: снимаются сдвиг и поворот этажа здания."""
    from app.services.tender_base import _bbox_in_view

    # Только сдвиг: этаж стр. 82 (offset [5589, -248]).
    assert _bbox_in_view([7134, 1941, 46809, 20248], (5589, -248), 0.0) == [
        1545,
        2189,
        41220,
        20496,
    ]
    # Поворот на 90°: вид [0,0]-[10,4] после R(90) = [-4,0]-[0,10], затем сдвиг (100, 200).
    assert _bbox_in_view([96, 200, 100, 210], (100, 200), 90.0) == [0, 0, 10, 4]
    assert _bbox_in_view(None, (0, 0), 0.0) is None


def test_object_base_thickness_of_monolith_without_nominal_uses_measured_section() -> None:
    """cad_walls v1.17: монолит без номинала с `section_mm` - округлённая измеренная толщина."""
    from app.contracts.cad_constructions import CadConstructionProps as PropsContract
    from app.contracts.cad_floor3d import WallsFloorExtras
    from app.services import tender_base
    from tests.test_cad_constructions_calc import document, section_item

    with_section = section_item("col", measured=649.9)
    no_section = section_item("pil", kind="monolith_pylon", measured=649.9)
    del no_section["section_mm"]
    nominal = section_item("wall", kind="monolith_wall", nominal=400.0, measured=649.9)
    doc = document([with_section, no_section, nominal])
    by_id = {c.id: c for c in doc.constructions}

    assert tender_base._thickness(by_id["col"], None) == 650
    assert tender_base._thickness(by_id["pil"], None) is None
    assert tender_base._thickness(by_id["wall"], None) == 400
    override = PropsContract(thickness_override_mm=300)
    assert tender_base._thickness(by_id["col"], override) == 300

    built = tender_base.build_constructions(doc, WallsFloorExtras(), {})
    assert {c.id: c.thickness_mm for c in built.constructions} == {
        "col": 650,
        "pil": None,
        "wall": 400,
    }


def test_object_base_slab_parts_only_when_there_are_several() -> None:
    """`slab.parts` - части плиты листа из двух корпусов; одна часть и старый файл - ключа нет."""
    from app.contracts.cad_constructions import WallsDocument
    from app.contracts.cad_floor3d import WallsFloorExtras
    from app.contracts.tender_exchange import ObjectBaseSlab
    from app.services import tender_base
    from tests.test_cad_constructions_calc import document
    from tests.test_cad_slab import PART_B, SHELL, two_part_extras

    doc: WallsDocument = document([])
    built = tender_base.build_constructions(doc, two_part_extras(), {})
    assert built.slab is not None
    main = [[round(x), round(y)] for x, y in SHELL]
    second = [[round(x), round(y)] for x, y in PART_B]
    assert built.slab.shell == main and built.slab.parts == [main, second]
    dumped = built.model_dump(by_alias=True)["slab"]
    assert dumped["parts"] == [main, second]

    single = WallsFloorExtras.model_validate(
        {"slab": {"shell": SHELL, "area_mm2": 24_000_000.0, "parts": [{"shell": SHELL}]}}
    )
    old = WallsFloorExtras.model_validate({"slab": {"shell": SHELL, "area_mm2": 24_000_000.0}})
    for extras in (single, old):
        built_single = tender_base.build_constructions(doc, extras, {})
        slab = built_single.slab
        assert slab is not None and slab.shell == main and slab.parts is None
        assert b'"parts"' not in tender_base._dump(built_single)
    # Пустой список и одна часть сериализуются так же, как «частей нет»: ключа нет совсем.
    for empty in (None, [], [main]):
        assert "parts" not in ObjectBaseSlab(shell=main, parts=empty).model_dump()


def test_published_json_schemas_match_contracts() -> None:
    """Схемы в docs/tender-exchange/schemas порождены из контрактов (app.tender_schemas_export)."""
    from app.tender_schemas_export import OUTPUT_DIR, schema_files

    expected = schema_files()
    assert sorted(path.name for path in OUTPUT_DIR.glob("*.schema.json")) == sorted(expected)
    for name, content in expected.items():
        assert (OUTPUT_DIR / name).read_text(encoding="utf-8") == content, name
