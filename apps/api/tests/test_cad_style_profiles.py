"""Профиль оформления проектировщика (ADR-0049): версии, блокировка, флаг, граница арендатора."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_style_profiles import CadStyleVersionWrite
from app.core.config import Settings
from app.domain import Role
from app.main import create_app
from app.models import (
    CadStyleProfile,
    CadStyleProfileVersion,
    Document,
    DocumentRevision,
    Workspace,
)
from app.services import cad_style_profiles as service
from tests.conftest import clean_settings, make_context
from tests.test_cad_qa import BROKEN_PDF, _upload

PROFILE: dict[str, Any] = {
    "monolith_fill_gray": [0.5, 0.6],
    "shaft_fill_gray": [0.8],
    "masonry_hatch_gray": [0.4],
    "concrete_hatch_gray": [0.3],
    "concrete_hatch_signatures": [
        {"color": [0.2, 0.2, 0.2], "pen": 0.25, "angle_deg": 45.0, "pitch_pt": 3.5}
    ],
    "alternate_boundary_gray": [],
    "door_pen_max_width": 0.5,
    "door_stitch_segments": True,
    "door_grid_tolerance": False,
    "masonry_acceptance": {
        "min_area_mm2": 1000,
        "min_effective_width_mm": 50,
        "min_hatch_lines": 3,
        "min_hatch_density": 0.1,
        "min_boundary_fraction": 0.5,
        "max_effective_width_mm": None,
    },
    "shaft_labels": ["ШК", "ЛК"],
}


def settings(*, flag: bool = True) -> Settings:
    return clean_settings(environment="test", feature_flags="cad.export=true" if flag else "")


def body(**changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "title": "Проектировщик А",
        "profile": copy.deepcopy(PROFILE),
        "source": {"kind": "manual"},
        "expected_current_version": None,
    }
    result.update(changes)
    return result


def samples_source(revision_id: str, **changes: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "kind": "samples",
        "revision_id": revision_id,
        "page_index": 0,
        "mm_per_pt": 35.28,
        "samples": [{"class": "door", "x": 0.1, "y": 0.2, "negative": False}],
    }
    source.update(changes)
    return source


async def post_raw(api: AsyncClient, target: str, payload: dict[str, Any]) -> Any:
    """Тело со строкой JSON в ASCII: одиночный суррогат клиент иначе не смог бы закодировать."""
    return await api.post(
        target, content=json.dumps(payload), headers={"Content-Type": "application/json"}
    )


def url(project_id: str, document_id: str, tail: str = "") -> str:
    return f"/api/v1/projects/{project_id}/documents/{document_id}/cad/style-profile{tail}"


async def _setup(api: AsyncClient, session: AsyncSession) -> tuple[str, str, str]:
    project_id, revision_id = await _upload(api, BROKEN_PDF)
    document_id = await session.scalar(
        select(DocumentRevision.document_id).where(DocumentRevision.id == uuid.UUID(revision_id))
    )
    assert document_id is not None
    return project_id, str(document_id), revision_id


def test_routes_are_registered() -> None:
    paths = create_app(settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/documents/{document_id}/cad/style-profile"
    assert "get" in paths[base]
    assert "get" in paths[f"{base}/versions/{{version}}"]
    assert "post" in paths[f"{base}/versions"]


def test_sha256_matches_the_engine_canonical_form() -> None:
    style = {"schema": "cad_engine.style_profile.v1", "id": "d-1", "version": 1, "profile": {}}
    assert (
        service.style_sha256(style)
        == "92bc79c0a4e8fe112a1afe71a6916d77162cafbf656de8206ef468c58bc0a713"
    )
    # Порядок ключей и не-ASCII не влияют на форму: ключи сортируются, кириллица не экранируется.
    shuffled = {"version": 1, "profile": {}, "id": "d-1", "schema": "cad_engine.style_profile.v1"}
    assert service.style_sha256(shuffled) == service.style_sha256(style)
    cyrillic = {"a": "ШК"}
    assert service.style_sha256(cyrillic) == hashlib.sha256('{"a":"ШК"}'.encode()).hexdigest()


def test_profile_key_fits_the_engine_pattern() -> None:
    key = service.profile_key_for(uuid.uuid4())
    assert re.fullmatch(r"[A-Za-z0-9._-]{1,64}", key)
    assert key.startswith("d-") and len(key) == 34


async def test_all_routes_are_closed_when_the_flag_is_off(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    fake = str(uuid.uuid4())
    async with build_api(make_context(), settings=settings(flag=False)) as api:
        for method, tail, payload in (
            ("get", "", None),
            ("get", "/versions/1", None),
            ("post", "/versions", body()),
        ):
            response = await api.request(method, url(fake, fake, tail), json=payload)
            assert response.status_code == 403, (method, tail)
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_first_and_second_version_and_reading(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, revision_id = await _setup(api, db_session)
        assert (await api.get(url(project_id, document_id))).status_code == 404

        source = samples_source(revision_id)
        first = await api.post(url(project_id, document_id, "/versions"), json=body(source=source))
        assert first.status_code == 201, first.text
        created = first.json()
        key = f"d-{uuid.UUID(document_id).hex}"
        assert created["version"] == 1
        assert created["style"] == {
            "schema": "cad_engine.style_profile.v1",
            "id": key,
            "version": 1,
            "profile": PROFILE,
        }
        canonical = json.dumps(
            created["style"], sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        assert created["sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
        assert created["source"]["samples"][0]["class"] == "door"
        assert created["title"] == "Проектировщик А"

        changed = copy.deepcopy(PROFILE)
        changed["door_pen_max_width"] = 1.5
        second = await api.post(
            url(project_id, document_id, "/versions"),
            json=body(profile=changed, title=None, expected_current_version=1),
        )
        assert second.status_code == 201, second.text
        assert second.json()["version"] == 2
        assert second.json()["style"]["version"] == 2
        assert second.json()["sha256"] != created["sha256"]

        profile = (await api.get(url(project_id, document_id))).json()
        assert profile["document_id"] == document_id
        assert profile["profile_key"] == key
        assert profile["current"]["version"] == 2
        assert [item["version"] for item in profile["versions"]] == [2, 1]
        assert all("style" not in item for item in profile["versions"])

        old = await api.get(url(project_id, document_id, "/versions/1"))
        assert old.status_code == 200
        assert old.json()["style"]["profile"]["door_pen_max_width"] == 0.5
        assert old.json() == created
        assert (await api.get(url(project_id, document_id, "/versions/3"))).status_code == 404


async def test_expected_current_version_conflicts(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        versions = url(project_id, document_id, "/versions")
        # Профиля нет, а клиент ждёт версию 1.
        stale = await api.post(versions, json=body(expected_current_version=1))
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "CAD_STYLE_PROFILE_VERSION_CONFLICT"

        assert (await api.post(versions, json=body())).status_code == 201
        # Профиль есть, а клиент считает, что его нет.
        again = await api.post(versions, json=body())
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "CAD_STYLE_PROFILE_VERSION_CONFLICT"
        wrong = await api.post(versions, json=body(expected_current_version=5))
        assert wrong.status_code == 409
        ok = await api.post(versions, json=body(expected_current_version=1))
        assert ok.status_code == 201
        assert ok.json()["version"] == 2


async def test_foreign_workspace_project_and_document_are_not_found(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
) -> None:
    second_id = second_workspace.id
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        other_project_id, other_document_id, _ = await _setup(api, db_session)
        assert (
            await api.post(url(project_id, document_id, "/versions"), json=body())
        ).status_code == 201
        # Документ чужого проекта того же пространства.
        mismatch = url(project_id, other_document_id)
        assert (await api.get(mismatch)).status_code == 404
        assert (await api.post(f"{mismatch}/versions", json=body())).status_code == 404
        assert (await api.get(url(project_id, str(uuid.uuid4())))).status_code == 404
        assert (await api.get(url(str(uuid.uuid4()), document_id))).status_code == 404
        assert other_project_id

    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=settings()) as foreign:
        assert (await foreign.get(url(project_id, document_id))).status_code == 404
        assert (await foreign.get(url(project_id, document_id, "/versions/1"))).status_code == 404
        created = await foreign.post(url(project_id, document_id, "/versions"), json=body())
        assert created.status_code == 404


async def test_revision_of_another_document_is_rejected(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        _, _, foreign_revision = await _setup(api, db_session)
        rejected = await api.post(
            url(project_id, document_id, "/versions"),
            json=body(source=samples_source(foreign_revision)),
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "VALIDATION_FAILED"
        unknown = await api.post(
            url(project_id, document_id, "/versions"),
            json=body(source=samples_source(str(uuid.uuid4()))),
        )
        assert unknown.status_code == 422
        assert unknown.json()["detail"]["code"] == "VALIDATION_FAILED"
        assert (await api.get(url(project_id, document_id))).status_code == 404


async def test_reading_needs_only_read_permission(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        assert (
            await api.post(url(project_id, document_id, "/versions"), json=body())
        ).status_code == 201
    async with build_api(make_context(Role.VIEWER), settings=settings()) as viewer:
        assert (await viewer.get(url(project_id, document_id))).status_code == 200
        denied = await viewer.post(url(project_id, document_id, "/versions"), json=body())
        assert denied.status_code == 403


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(monolith_fill_gray=[1.5]),
        lambda p: p.update(shaft_fill_gray=[-0.1]),
        lambda p: p.update(masonry_hatch_gray=[0.1] * 17),
        lambda p: p.update(monolith_fill_gray=[True]),
        lambda p: p.update(monolith_fill_gray=["0.5"]),
        lambda p: p.update(monolith_fill_gray=[-0.0]),
        lambda p: p.update(door_pen_max_width=0),
        lambda p: p.update(door_pen_max_width=5.1),
        lambda p: p.update(door_pen_max_width=True),
        lambda p: p.update(door_pen_max_width="0.5"),
        lambda p: p.update(door_stitch_segments="yes"),
        lambda p: p.update(extra_field=1),
        lambda p: p.update(shaft_labels=["x" * 33]),
        lambda p: p.update(shaft_labels=["x"] * 51),
        lambda p: p.update(shaft_labels=["a\x00b"]),
        lambda p: p.pop("shaft_labels"),
        lambda p: p["concrete_hatch_signatures"][0].update(extra=1),
        lambda p: p["concrete_hatch_signatures"][0].update(color=[0.1, 1.5, 0.1]),
        lambda p: p["concrete_hatch_signatures"][0].update(color=[0.1, 0.1]),
        lambda p: p["concrete_hatch_signatures"][0].update(angle_deg=180),
        lambda p: p["concrete_hatch_signatures"][0].update(angle_deg=-1),
        lambda p: p["concrete_hatch_signatures"][0].update(pen=0),
        lambda p: p["concrete_hatch_signatures"][0].update(pitch_pt=0),
        lambda p: p["concrete_hatch_signatures"][0].pop("pitch_pt"),
        lambda p: p.update(concrete_hatch_signatures=p["concrete_hatch_signatures"] * 9),
        lambda p: p["masonry_acceptance"].pop("min_hatch_lines"),
        lambda p: p["masonry_acceptance"].update(extra=1),
        lambda p: p["masonry_acceptance"].update(min_area_mm2=-1),
        lambda p: p["masonry_acceptance"].update(min_area_mm2="1000"),
        lambda p: p["masonry_acceptance"].update(min_area_mm2=-0.0),
        lambda p: p["masonry_acceptance"].update(min_area_mm2=1e16),
        lambda p: p["masonry_acceptance"].update(min_hatch_lines=True),
        lambda p: p["masonry_acceptance"].update(min_hatch_density=1e300),
        lambda p: p["masonry_acceptance"].update(max_effective_width_mm=1e16),
    ],
)
async def test_invalid_profile_body_is_rejected(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    mutate: Callable[[dict[str, Any]], object],
) -> None:
    profile = copy.deepcopy(PROFILE)
    mutate(profile)
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        response = await post_raw(
            api, url(project_id, document_id, "/versions"), body(profile=profile)
        )
        assert response.status_code == 422, response.text
        assert (await api.get(url(project_id, document_id))).status_code == 404


def _sample(**changes: Any) -> dict[str, Any]:
    sample: dict[str, Any] = {"class": "door", "x": 0.1, "y": 0.1, "negative": False}
    sample.update(changes)
    return sample


async def test_invalid_source_and_title_are_rejected(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, revision_id = await _setup(api, db_session)
        versions = url(project_id, document_id, "/versions")
        for changes in (
            {"source": {"kind": "auto"}},
            # samples: все поля обязательны.
            {"source": {"kind": "samples"}},
            {"source": {"kind": "samples", "revision_id": revision_id}},
            {"source": samples_source(revision_id, samples=[])},
            {"source": samples_source(revision_id, mm_per_pt=0)},
            {"source": samples_source(revision_id, mm_per_pt="35")},
            {"source": samples_source(revision_id, page_index=-1)},
            {"source": samples_source(revision_id, page_index=True)},
            {"source": samples_source(revision_id, extra=1)},
            {"source": samples_source(revision_id, samples=[_sample(**{"class": "wall"})])},
            {"source": samples_source(revision_id, samples=[_sample(x=1.1)])},
            {"source": samples_source(revision_id, samples=[_sample(x=-0.0)])},
            {"source": samples_source(revision_id, samples=[_sample()] * 201)},
            # manual: полей снятия по образцам нет.
            {"source": {"kind": "manual", "mm_per_pt": 35.28}},
            {"source": {"kind": "manual", "revision_id": revision_id}},
            {"source": {"kind": "manual", "page_index": 0}},
            {"source": {"kind": "manual", "samples": []}},
            {"source": {"kind": "manual", "extra": 1}},
            {"title": "т" * 201},
            {"title": "a\x00b"},
            {"expected_current_version": 0},
            {"expected_current_version": 2**31},
            {"expected_current_version": True},
        ):
            response = await post_raw(api, versions, body(**changes))
            assert response.status_code == 422, changes


async def test_bad_version_in_path_is_not_a_server_error(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        for version in ("0", "-1", str(2**31), str(2**63), "abc"):
            response = await api.get(url(project_id, document_id, f"/versions/{version}"))
            assert response.status_code == 422, version


async def test_stored_hash_matches_the_style_in_the_response_and_the_database(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    profile = copy.deepcopy(PROFILE)
    profile["door_pen_max_width"] = 1  # целое для float допустимо
    profile["monolith_fill_gray"] = [0, 1, 1e-7]
    profile["masonry_acceptance"]["min_area_mm2"] = 1e9
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        response = await api.post(
            url(project_id, document_id, "/versions"), json=body(profile=profile)
        )
        assert response.status_code == 201, response.text
        created = response.json()
    assert created["sha256"] == service.style_sha256(created["style"])
    stored = await db_session.scalar(select(CadStyleProfileVersion))
    assert stored is not None
    assert service.style_sha256(stored.style) == stored.sha256 == created["sha256"]


async def test_update_of_a_version_is_rejected_by_the_database(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        assert (
            await api.post(url(project_id, document_id, "/versions"), json=body())
        ).status_code == 201
    with pytest.raises(DBAPIError, match="immutable"):
        await db_session.execute(text("update cad_style_profile_versions set title = 'другое'"))
    await db_session.rollback()
    title = await db_session.scalar(select(CadStyleProfileVersion.title))
    assert title == "Проектировщик А"


async def test_profile_is_deleted_with_its_document(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    async with build_api(make_context(), settings=settings()) as api:
        project_id, document_id, _ = await _setup(api, db_session)
        versions = url(project_id, document_id, "/versions")
        assert (await api.post(versions, json=body())).status_code == 201
        assert (await api.post(versions, json=body(expected_current_version=1))).status_code == 201
    assert await db_session.scalar(select(func.count()).select_from(CadStyleProfile)) == 1
    assert await db_session.scalar(select(func.count()).select_from(CadStyleProfileVersion)) == 2
    await db_session.execute(delete(Document).where(Document.id == uuid.UUID(document_id)))
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(CadStyleProfile)) == 0
    assert await db_session.scalar(select(func.count()).select_from(CadStyleProfileVersion)) == 0


def test_write_contract_has_no_defaults_for_profile_fields() -> None:
    incomplete = body()
    incomplete["profile"].pop("door_grid_tolerance")
    with pytest.raises(ValueError):
        CadStyleVersionWrite.model_validate(incomplete)


def test_hatch_signatures_accept_valid_and_limit_is_eight() -> None:
    valid = body(profile=copy.deepcopy(PROFILE))
    valid["profile"]["concrete_hatch_signatures"] *= 8
    parsed = CadStyleVersionWrite.model_validate(valid)
    assert len(parsed.profile.concrete_hatch_signatures) == 8
    edge = body(profile=copy.deepcopy(PROFILE))
    edge["profile"]["concrete_hatch_signatures"][0]["angle_deg"] = 179.9
    CadStyleVersionWrite.model_validate(edge)


def test_hatch_signatures_default_to_empty_and_reach_the_engine_body() -> None:
    legacy = body()
    legacy["profile"].pop("concrete_hatch_signatures")
    parsed = CadStyleVersionWrite.model_validate(legacy)
    assert parsed.profile.concrete_hatch_signatures == []
    assert parsed.profile.model_dump(mode="json")["concrete_hatch_signatures"] == []
