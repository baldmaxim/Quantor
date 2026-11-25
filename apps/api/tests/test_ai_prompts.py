"""Версии промтов ИИ-проверки: единственность активной, активация, права, `_prepare`, статистика."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.cad_worker import ai_review
from app.cad_worker.handler import CadError
from app.domain import JobStatus, JobType, Role
from app.models import AiPromptVersion, CadRemark, Job
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_queue import add_job
from tests.test_project_ai_pipeline import _plan
from tests.test_schema_matches_migrations import migrated_engine

# sha256 текстов, которые собирал CLI до версионирования (PROMPT_COMMON + роль + перевод строки).
OLD_SHA = {
    "corrector": "e9b8a45c0e95e3ba24aaab4a5d77dc10b74e60cb9e7e139c57aff369aa7e5c55",
    "verifier": "e0d3b3d1727be4ae1dfa1570deb0a424bf7bfb920c856036b984a99064ed26ac",
}
URL = "/api/v1/admin/ai-prompts"


def _admin() -> Any:
    return make_context(Role.PLATFORM_ADMIN)


async def _seed(
    session: AsyncSession, role: str, version: int, status: str, text: str = "T"
) -> Any:
    row = AiPromptVersion(role=role, version=version, text=text, status=status)
    session.add(row)
    await session.commit()
    return row.id


async def test_only_one_active_version_per_role(db_session: AsyncSession) -> None:
    await _seed(db_session, "corrector", 1, "active")
    await _seed(db_session, "verifier", 1, "active")
    db_session.add(AiPromptVersion(role="corrector", version=2, text="X", status="active"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_create_and_activate_archives_previous(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    first = await _seed(db_session, "corrector", 1, "active", "старый")
    other = await _seed(db_session, "verifier", 1, "active", "проверщик")
    async with build_api(_admin()) as client:
        created = await client.post(
            URL, json={"role": "corrector", "text": "новый", "note": "правка"}
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert (body["version"], body["status"], body["note"]) == (2, "draft", "правка")
        assert body["created_by"] is not None

        done = await client.post(f"{URL}/{body['id']}/activate")
        assert done.status_code == 200, done.text
        assert done.json()["status"] == "active"
        assert done.json()["activated_at"] is not None

        listed = await client.get(URL, params={"role": "corrector"})
        assert [(row["version"], row["status"]) for row in listed.json()] == [
            (2, "active"),
            (1, "archived"),
        ]
        assert "text" not in listed.json()[0]
        one = await client.get(f"{URL}/{first}")
        assert one.json()["text"] == "старый"

    db_session.expire_all()
    verifier = await db_session.get(AiPromptVersion, other)
    assert verifier is not None and verifier.status == "active"


async def test_create_rejects_oversized_and_blank_text(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(_admin()) as client:
        huge = await client.post(URL, json={"role": "corrector", "text": "я" * 40000})
        blank = await client.post(URL, json={"role": "corrector", "text": "  \n"})
        role = await client.post(URL, json={"role": "boss", "text": "x"})
    assert huge.status_code == 422
    assert blank.status_code == 422
    assert role.status_code == 422


async def test_not_admin_is_forbidden(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    prompt = await _seed(db_session, "corrector", 1, "active")
    async with build_api(make_context(Role.WORKSPACE_ADMIN)) as client:
        responses = [
            await client.get(URL),
            await client.get(f"{URL}/stats"),
            await client.get(f"{URL}/{prompt}"),
            await client.post(URL, json={"role": "corrector", "text": "x"}),
            await client.post(f"{URL}/{prompt}/activate"),
        ]
    assert [response.status_code for response in responses] == [403] * 5


class _Session:
    """Сессия для `_prepare`: задания и ревизия - заглушки, запросы к промтам - настоящие."""

    def __init__(self, real: AsyncSession, objects: dict[Any, Any]) -> None:
        self._real = real
        self._objects = objects

    async def get(self, model: Any, key: Any) -> Any:
        return self._objects[model.__name__]

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        return await self._real.scalar(*args, **kwargs)


def _prepare_setup(monkeypatch: pytest.MonkeyPatch, role: str) -> tuple[Job, dict[str, Any]]:
    revision_id = uuid.uuid4()
    project_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    parent = str(uuid.uuid4())
    walls = Job(
        id=uuid.uuid4(),
        project_id=project_id,
        workspace_id=workspace_id,
        attempt=1,
        status=JobStatus.SUCCEEDED,
        job_type=JobType.CAD_WALLS,
        payload={
            "revision_id": str(revision_id),
            "parent_job_id": parent,
            "parent_attempt": 2,
            "view_frame": [1.0, 2.0, 3.0],
            "cad_result": {
                "attempt": 1,
                "page_index": 4,
                "view": 1,
                "dxf_sha256": "d" * 64,
                "walls_sha256": "w" * 64,
                "generator": "g",
            },
        },
    )
    payload = {
        "walls_job_id": str(walls.id),
        "walls_attempt": 1,
        "cad_job_id": parent,
        "cad_attempt": 2,
        "revision_id": str(revision_id),
        "page_index": 4,
        "view": 1,
        "role": role,
        "iteration": 1,
        "model": "m",
        "sources": {},
    }
    job = Job(
        id=uuid.uuid4(),
        project_id=project_id,
        workspace_id=workspace_id,
        job_type=JobType.CAD_AI_REVIEW,
        payload=payload,
    )
    revision = type("Revision", (), {"source_sha256": "i" * 64})()

    async def fake_download(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(ai_review, "_download", fake_download)
    monkeypatch.setattr(ai_review, "_download_artifact", fake_download)
    return job, {"Job": walls, "DocumentRevision": revision}


async def test_prepare_writes_active_prompt_and_version(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_storage: FakeObjectStorage,
) -> None:
    text = "Общая часть.\n\nРоль — правщик.\n"
    await _seed(db_session, "corrector", 1, "archived", "старый")
    active_id = await _seed(db_session, "corrector", 2, "active", text)
    await _seed(db_session, "verifier", 1, "active", "другая роль")
    job, objects = _prepare_setup(monkeypatch, "corrector")

    manifest = await ai_review._prepare(
        cast(AsyncSession, _Session(db_session, objects)), job, fake_storage, tmp_path
    )

    assert (tmp_path / "prompt.txt").read_bytes() == text.encode()
    assert hashlib.sha256((tmp_path / "prompt.txt").read_bytes()).hexdigest() == (
        hashlib.sha256(text.encode()).hexdigest()
    )
    assert manifest["prompt_version_id"] == str(active_id)
    assert manifest["prompt_version"] == 2
    # Версия видна и у упавшего прогона: статистика берёт её из задания.
    assert job.payload["prompt_version_id"] == str(active_id)
    assert job.payload["prompt_version"] == 2


async def test_prepare_fails_without_active_prompt(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake_storage: FakeObjectStorage,
) -> None:
    await _seed(db_session, "corrector", 1, "archived")
    job, objects = _prepare_setup(monkeypatch, "corrector")

    with pytest.raises(CadError) as caught:
        await ai_review._prepare(
            cast(AsyncSession, _Session(db_session, objects)), job, fake_storage, tmp_path
        )

    assert "промта" in caught.value.message
    assert not (tmp_path / "prompt.txt").exists()


def _run(
    session: AsyncSession,
    plan: Any,
    prompt_id: uuid.UUID | None,
    status: JobStatus,
    *,
    cost: float | None = None,
    verdict: str = "needs_correction",
    types: tuple[str, ...] = (),
    keys: tuple[str, ...] = (),
    duration: int | None = None,
) -> Job:
    payload: dict[str, Any] = {"role": "corrector"}
    if prompt_id is not None:
        payload["prompt_version_id"] = str(prompt_id)
    if status is JobStatus.SUCCEEDED:
        payload["ai_review"] = {
            "usage": {"cost_usd": cost, "duration_ms": duration},
            "remark_keys": list(keys),
            "report": {"verdict": verdict, "findings": [{"type": kind} for kind in types]},
        }
    walls = plan.walls[0]
    return add_job(
        session,
        workspace_id=walls.workspace_id,
        project_id=walls.project_id,
        status=status,
        job_type=JobType.CAD_AI_REVIEW,
        payload=payload,
    )


async def test_stats_by_version_with_remark_fates(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    v1 = await _seed(db_session, "corrector", 1, "active")
    v2 = await _seed(db_session, "corrector", 2, "draft")
    async with build_api(_admin(), settings=clean_settings(environment="test")) as probe:
        plan = await _plan(db_session, fake_storage, probe, workspace_id, 1)
    _run(
        db_session,
        plan,
        v1,
        JobStatus.SUCCEEDED,
        cost=0.5,
        duration=1000,
        verdict="needs_correction",
        types=("missing_wall", "missing_wall", "monolith"),
        keys=("ai-open", "ai-done", "ai-gone"),
    )
    _run(
        db_session,
        plan,
        v1,
        JobStatus.SUCCEEDED,
        cost=0.25,
        duration=3000,
        verdict="ready_for_human_review",
        types=(),
        keys=(),
    )
    _run(db_session, plan, v1, JobStatus.FAILED)
    _run(db_session, plan, v1, JobStatus.RUNNING)  # идущий в счёт не входит
    _run(db_session, plan, None, JobStatus.SUCCEEDED, cost=9.0)  # без версии - не учитывается
    for key, status in (("ai-open", "open"), ("ai-done", "resolved")):
        db_session.add(
            CadRemark(
                workspace_id=workspace_id,
                project_id=uuid.UUID(plan.project_id),
                revision_id=plan.revision_id,
                job_id=plan.convert[0].id,
                attempt=1,
                page_index=0,
                view=0,
                remark_key=key,
                type="missing_wall",
                comment="x",
                status=status,
                bbox_x0=0,
                bbox_y0=0,
                bbox_x1=1,
                bbox_y1=1,
            )
        )
    await db_session.commit()

    async with build_api(_admin()) as client:
        response = await client.get(f"{URL}/stats")

    assert response.status_code == 200, response.text
    rows = {row["version"]: row for row in response.json()["rows"]}
    first = rows[1]
    assert first["prompt_id"] == str(v1)
    assert (first["runs_total"], first["runs_succeeded"], first["runs_failed"]) == (3, 2, 1)
    assert first["cost_sum_usd"] == pytest.approx(0.75)
    assert first["cost_avg_usd"] == pytest.approx(0.375)
    assert first["duration_avg_ms"] == pytest.approx(2000)
    assert first["verdicts"] == {"needs_correction": 1, "ready_for_human_review": 1}
    assert first["findings_total"] == 3
    assert first["findings_by_type"] == {"missing_wall": 2, "monolith": 1}
    assert (first["remarks_open"], first["remarks_resolved"], first["remarks_deleted"]) == (1, 1, 1)
    empty = rows[2]
    assert empty["prompt_id"] == str(v2)
    assert empty["runs_total"] == 0
    assert empty["cost_avg_usd"] is None and empty["cost_sum_usd"] is None
    assert empty["verdicts"] == {} and empty["remarks_open"] == 0


async def test_migration_seeds_old_cli_prompts_as_active_version_one(
    migrated_engine: AsyncEngine,
) -> None:
    """Версия 1 в миграции дословно равна тому, что собирал CLI: sha256 старой сборки."""
    async with migrated_engine.connect() as connection:
        rows = (
            await connection.execute(
                text(
                    "select role, version, status, created_by, text from ai_prompt_versions"
                    " order by role"
                )
            )
        ).all()
    assert [(row.role, row.version, row.status, row.created_by) for row in rows] == [
        ("corrector", 1, "active", None),
        ("style", 1, "active", None),
        ("verifier", 1, "active", None),
        ("vor_mapper", 1, "active", None),
    ]
    assert {
        row.role: hashlib.sha256(row.text.encode()).hexdigest()
        for row in rows
        if row.role in OLD_SHA
    } == OLD_SHA
    mapper = next(row.text for row in rows if row.role == "vor_mapper")
    assert mapper.startswith("Ты сопоставляешь позиции ведомости объёмов работ (ВОР) Заказчика")
    assert "vor_items.json" in mapper and "objects.json" in mapper and "unmatched_objects" in mapper
    style = next(row.text for row in rows if row.role == "style")
    assert style.startswith("Ты определяешь, как проектировщик оформил материалы стен на плане")
    assert "hatch_signatures.json" in style and style.endswith("Верни один JSON по схеме.\n")


__all__ = ["migrated_engine"]
