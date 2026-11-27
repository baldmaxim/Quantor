"""Перенос решений человека на новый прогон при равной геометрии вида (cad_decisions_carry).

Исходный прогон (`_parent` из test_cad_mep) - одобрение, трассы по нему и принятие трасс человеком.
Новый прогон - второе успешное `cad_pdf_convert` той же ревизии с теми же файлами вида; отпечаток
геометрии в итогах выставляется тестом.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.handler import _geometry_fingerprints, _page_summary, _scale_hashes
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import JobStatus, JobType
from app.models import CadDecision, Job
from app.models.cad_decision import DECISION_MEP_ACCEPTANCE, DECISION_VIEW_APPROVAL
from app.services import cad as cad_service
from app.services import cad_decisions_carry
from app.services import jobs as jobs_service
from app.services.cad_geometry_fingerprint import dxf_geometry_sha256
from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_mep import (
    APPROVAL,
    FOLDER,
    PARENT_DXF,
    _parent,
    _remark,
    _run_route_worker,
    _sha,
    mep_settings,
    tools,  # noqa: F401  (фикстура)
)

FINGERPRINT = "a" * 64
OTHER_FINGERPRINT = "b" * 64
SCALE = "c" * 64
OTHER_SCALE = "d" * 64
# Полный текстовый DXF: у заглушки PARENT_DXF секций TABLES, BLOCKS, ENTITIES нет (отпечатка нет).
FULL_DXF = (
    b"0\nSECTION\n2\nTABLES\n0\nENDSEC\n0\nSECTION\n2\nBLOCKS\n0\nENDSEC\n"
    b"0\nSECTION\n2\nENTITIES\n0\nLINE\n10\n1.0\n0\nENDSEC\n0\nEOF\n"
)


async def _set_fingerprint(
    session: AsyncSession, job_id: uuid.UUID, value: str | None, scale: str | None = SCALE
) -> None:
    job = await session.get(Job, job_id)
    assert job is not None
    result = dict(job.payload["cad_result"])
    for page in result["pages"]:
        for row in page["views"]:
            if value is None:
                row.pop("dxf_geometry_sha256", None)
            else:
                row["dxf_geometry_sha256"] = value
            if scale is None:
                row.pop("scale_sha256", None)
            else:
                row["scale_sha256"] = scale
    await session.execute(
        update(Job).where(Job.id == job_id).values(payload={**job.payload, "cad_result": result})
    )
    await session.commit()
    session.expire_all()


async def _new_convert(
    session: AsyncSession,
    storage: FakeObjectStorage,
    old: Job,
    *,
    fingerprint: str | None,
    scale: str | None = SCALE,
) -> Job:
    """Второй успешный прогон той же ревизии: те же файлы вида под новым заданием."""
    await session.refresh(old)
    revision_id = str(old.payload["revision_id"])
    job = await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_PDF_CONVERT,
        workspace_id=DEV_WORKSPACE_ID,
        project_id=old.project_id,
        idempotency_key=f"carry-test:{uuid.uuid4()}",
        payload={**old.payload, "cad_results": None},
    )
    job_id = job.id
    result: dict[str, Any] = {**old.payload["cad_result"], "attempt": 1}
    artifacts = []
    for item in old.payload["cad_result"]["artifacts"]:
        source = storage.objects[item["key"]]
        key = cad_service.artifact_storage_key(uuid.UUID(revision_id), job.id, 1, str(item["name"]))
        await storage.put_bytes(key, source, content_type="application/octet-stream")
        artifacts.append({**item, "key": key})
    result["artifacts"] = artifacts
    await session.execute(
        update(Job)
        .where(Job.id == job.id)
        .values(
            status=JobStatus.SUCCEEDED, attempt=1, payload={**job.payload, "cad_result": result}
        )
    )
    await session.commit()
    session.expire_all()
    await _set_fingerprint(session, job_id, fingerprint, scale)
    fresh = await session.get(Job, job_id)
    assert fresh is not None
    return fresh


async def _fresh(session: AsyncSession, *objects: Job | CadDecision) -> None:
    """Объекты истекают после `expire_all`: перечитать перед сверкой."""
    for item in objects:
        await session.refresh(item)


async def _decisions(session: AsyncSession, job_id: uuid.UUID, kind: str) -> list[CadDecision]:
    rows = await session.scalars(
        select(CadDecision).where(CadDecision.job_id == job_id, CadDecision.kind == kind)
    )
    return list(rows)


async def _old_world(
    api: AsyncClient,
    session: AsyncSession,
    storage: FakeObjectStorage,
    *,
    fingerprint: str | None = FINGERPRINT,
) -> tuple[Job, CadDecision, str]:
    _, _, job_id, base = await _parent(api, session, storage)
    await _set_fingerprint(session, uuid.UUID(job_id), fingerprint)
    approved = await api.post(f"{base}/{job_id}/views/0/1/approval", json=APPROVAL)
    assert approved.status_code == 201, approved.text
    old = await session.get(Job, uuid.UUID(job_id))
    assert old is not None
    approval = (await _decisions(session, old.id, DECISION_VIEW_APPROVAL))[0]
    return old, approval, base


async def test_equal_fingerprint_carries_approval_with_original_author(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, approval, _ = await _old_world(api, db_session, fake_storage)
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)

        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()

        carried = await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL)
        await _fresh(db_session, approval, old)
        assert len(carried) == 1
        assert carried[0].carried_from_id == approval.id
        assert carried[0].decided_by == approval.decided_by
        assert carried[0].artifact_sha256 == _sha(PARENT_DXF)
        assert str(old.id) in (carried[0].comment or "")
        assert carried[0].revoked_at is None
        # Принятых трасс у исходного вида не было: трассы не ставятся.
        routes = await db_session.scalars(select(Job).where(Job.job_type == JobType.CAD_MEP_ROUTE))
        assert list(routes) == []

        # Идемпотентность: повторный вызов дублей не плодит.
        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()
        assert len(await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL)) == 1


async def test_different_or_missing_fingerprint_does_not_carry(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, _, _ = await _old_world(api, db_session, fake_storage)
        for new_value in (OTHER_FINGERPRINT, None):
            new = await _new_convert(db_session, fake_storage, old, fingerprint=new_value)
            await cad_decisions_carry.carry_after_convert(db_session, new, settings)
            await db_session.commit()
            assert await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL) == []


async def test_old_result_without_fingerprint_does_not_carry(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, _, _ = await _old_world(api, db_session, fake_storage, fingerprint=None)
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()
        assert await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL) == []


async def test_revoked_approval_does_not_carry_and_old_one_is_not_resurrected(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, approval, base = await _old_world(api, db_session, fake_storage)
        approval_id = approval.id
        revoked = await api.post(f"{base}/decisions/{approval_id}/revoke", json={})
        assert revoked.status_code == 200, revoked.text
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()
        assert await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL) == []

        # Прогон B (отозванное одобрение на нём) не даёт «воскресить» одобрение с прогона A.
        middle = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        await cad_decisions_carry.carry_after_convert(db_session, middle, settings)
        assert await _decisions(db_session, middle.id, DECISION_VIEW_APPROVAL) == []


async def test_open_remarks_on_new_view_block_the_carry(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, _, base = await _old_world(api, db_session, fake_storage)
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        remark = f"{base}/{new.id}/remarks/{uuid.uuid4()}?attempt=1&page_index=0&view=1"
        assert (await api.put(remark, json=_remark(_sha(PARENT_DXF)))).status_code == 200
        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()
        assert await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL) == []


async def _accepted_world(
    api: AsyncClient,
    session: AsyncSession,
    storage: FakeObjectStorage,
    settings: Any,
) -> tuple[Job, CadDecision, CadDecision, str]:
    old, approval, base = await _old_world(api, session, storage)
    route_id = await _approve_and_queue_existing(api, base, str(old.id))
    job = await _run_route_worker(session, storage, settings, route_id)
    assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
    accepted = await api.post(f"{base}/{route_id}/acceptance", json={"attempt": 1})
    assert accepted.status_code == 201, accepted.text
    acceptance = (await _decisions(session, uuid.UUID(route_id), DECISION_MEP_ACCEPTANCE))[0]
    return old, approval, acceptance, base


async def _approve_and_queue_existing(api: AsyncClient, base: str, job_id: str) -> str:
    """Одобрение вида уже есть: ставим только трассы."""
    queued = await api.post(
        f"{base}/{job_id}/views/0/1/mep-routes",
        json={"attempt": 1, "floor_elevation_mm": 47600, "floor_height_mm": 3300},
    )
    assert queued.status_code == 202, queued.text
    return str(queued.json()["job_id"])


async def _route_of(session: AsyncSession, parent: Job) -> Job | None:
    found: Job | None = await session.scalar(
        select(Job).where(
            Job.job_type == JobType.CAD_MEP_ROUTE,
            Job.payload["parent_job_id"].astext == str(parent.id),
        )
    )
    return found


async def test_accepted_routes_are_rescheduled_and_acceptance_carried_when_equal(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, approval, acceptance, _ = await _accepted_world(
            api, db_session, fake_storage, settings
        )
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()

        route = await _route_of(db_session, new)
        assert route is not None and route.status is JobStatus.QUEUED
        assert route.payload["floor_elevation_mm"] == 47600
        assert route.payload["floor_height_mm"] == 3300
        carried_approval = (await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL))[0]
        await _fresh(db_session, approval, acceptance)
        assert route.payload["approval_id"] == str(carried_approval.id)
        assert carried_approval.carried_from_id == approval.id

        done = await _run_route_worker(db_session, fake_storage, settings, str(route.id))
        assert done.status is JobStatus.SUCCEEDED, (done.error_code, done.error_message)
        carried = await _decisions(db_session, route.id, DECISION_MEP_ACCEPTANCE)
        assert len(carried) == 1
        await _fresh(db_session, acceptance)
        assert carried[0].carried_from_id == acceptance.id
        assert carried[0].decided_by == acceptance.decided_by

        # Повтор хука дублей не плодит.
        await cad_decisions_carry.carry_routes_acceptance(db_session, done)
        await db_session.commit()
        assert len(await _decisions(db_session, route.id, DECISION_MEP_ACCEPTANCE)) == 1


async def test_acceptance_is_not_carried_when_routes_differ(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, _, acceptance, _ = await _accepted_world(api, db_session, fake_storage, settings)
        # Принятые трассы имели другую геометрию, чем даст новый прогон: отпечатка у заглушки
        # трасс нет, сверяется sha256 файла.
        await db_session.execute(
            update(CadDecision)
            .where(CadDecision.id == acceptance.id)
            .values(artifact_sha256="e" * 64)
        )
        await db_session.commit()
        db_session.expire_all()
        await _fresh(db_session, old)
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()
        route = await _route_of(db_session, new)
        assert route is not None
        done = await _run_route_worker(db_session, fake_storage, settings, str(route.id))
        assert done.status is JobStatus.SUCCEEDED
        assert await _decisions(db_session, route.id, DECISION_MEP_ACCEPTANCE) == []
        # Одобрение вида при этом перенесено: трассы ждут человека.
        assert len(await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL)) == 1


def test_convert_summary_records_geometry_fingerprint(tmp_path: Path) -> None:
    """Исполнитель convert пишет отпечаток вида в итог; без DXF и в отказах поля нет."""
    folder = tmp_path / FOLDER
    folder.mkdir(parents=True)
    (folder / "plan_candidates.dxf").write_bytes(FULL_DXF)
    (folder / "scale.json").write_bytes(b'{"scale": 100}')
    report: dict[str, Any] = {
        "pages": [
            {
                "index": 0,
                "legacy_pdf_page": 1,
                "views": [
                    {"view": 1, "status": "needs_review", "dxf": {"entities": 3}},
                    {"view": 2, "status": "failed"},
                ],
            }
        ]
    }
    found = _geometry_fingerprints(tmp_path, report)
    assert found == {(0, 1): dxf_geometry_sha256(FULL_DXF)}
    scales = _scale_hashes(tmp_path, report)
    assert scales == {(0, 1): hashlib.sha256(b'{"scale": 100}').hexdigest()}
    views = _page_summary(report, found, scales)[0]["views"]
    assert views[0]["dxf_geometry_sha256"] == found[(0, 1)]
    assert views[0]["scale_sha256"] == scales[(0, 1)]
    assert "dxf_geometry_sha256" not in views[1] and "scale_sha256" not in views[1]
    # Заглушка без секций (неполный DXF) отпечатка не даёт: поля нет, задание не падает.
    (folder / "plan_candidates.dxf").write_bytes(PARENT_DXF)
    assert _geometry_fingerprints(tmp_path, report) == {}
    assert "dxf_geometry_sha256" not in _page_summary(report)[0]["views"][0]


async def test_different_scale_does_not_carry(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, _, _ = await _old_world(api, db_session, fake_storage)
        for scale in (OTHER_SCALE, None):
            new = await _new_convert(
                db_session, fake_storage, old, fingerprint=FINGERPRINT, scale=scale
            )
            await cad_decisions_carry.carry_after_convert(db_session, new, settings)
            await db_session.commit()
            assert await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL) == []


async def test_open_remarks_on_source_view_block_the_carry(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, _, base = await _old_world(api, db_session, fake_storage)
        remark = f"{base}/{old.id}/remarks/{uuid.uuid4()}?attempt=1&page_index=0&view=1"
        assert (await api.put(remark, json=_remark(_sha(PARENT_DXF)))).status_code == 200
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()
        assert await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL) == []


async def test_routes_are_not_scheduled_when_mep_engine_flag_is_off(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, _, _, _ = await _accepted_world(api, db_session, fake_storage, settings)
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        closed = mep_settings(tools, tmp_path, mep_engine=False)
        await cad_decisions_carry.carry_after_convert(db_session, new, closed)
        await db_session.commit()
        # Одобрение вида перенесено, трассы не поставлены.
        assert len(await _decisions(db_session, new.id, DECISION_VIEW_APPROVAL)) == 1
        assert await _route_of(db_session, new) is None


async def test_carry_failure_does_not_break_convert(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = mep_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        old, _, _ = await _old_world(api, db_session, fake_storage)
        new = await _new_convert(db_session, fake_storage, old, fingerprint=FINGERPRINT)
        new_id = new.id
        original = cad_decisions_carry._schedule_accepted_routes

        async def boom(*args: Any, **kwargs: Any) -> None:
            raise OSError("диск")

        # Сбой после записи одобрения: savepoint вида откатывает и его.
        monkeypatch.setattr(cad_decisions_carry, "_schedule_accepted_routes", boom)
        await cad_decisions_carry.carry_after_convert(db_session, new, settings)
        await db_session.commit()
        assert await _decisions(db_session, new_id, DECISION_VIEW_APPROVAL) == []
        fresh = await db_session.get(Job, new_id)
        assert fresh is not None and fresh.status is JobStatus.SUCCEEDED

        # Сбой вне вида: исключение не выходит наружу.
        monkeypatch.setattr(cad_decisions_carry, "_schedule_accepted_routes", original)

        def crash(_job: Job) -> dict[str, Any]:
            raise KeyError("result")

        monkeypatch.setattr(cad_service, "current_result", crash)
        await cad_decisions_carry.carry_after_convert(db_session, fresh, settings)
        assert await _decisions(db_session, new_id, DECISION_VIEW_APPROVAL) == []
