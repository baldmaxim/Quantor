"""Сборка 3D здания: у нового прогона листа нет конструкций - берётся прежняя согласованная пара."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType
from app.models import Job
from app.services import cad as cad_service
from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_building3d_api import _codes, _url, floor_tools  # noqa: F401
from tests.test_cad_constructions_api import (
    _ready_sheet,
    _run_walls_worker,
    walls_settings,
)
from tests.test_cad_constructions_api import (
    _url as walls_url,
)


async def _clone_convert(
    session: AsyncSession, storage: FakeObjectStorage, old_id: str, revision_id: str
) -> Job:
    """Новый успешный `cad_pdf_convert` той же ревизии с копиями артефактов (новые ключи)."""
    old = await session.get(Job, uuid.UUID(old_id))
    assert old is not None
    new_id = uuid.uuid4()
    payload: dict[str, Any] = copy.deepcopy(old.payload)
    for artifact in payload["cad_result"]["artifacts"]:
        key = cad_service.artifact_storage_key(
            uuid.UUID(revision_id), new_id, 1, str(artifact["name"])
        )
        await storage.put_bytes(
            key, storage.objects[str(artifact["key"])], content_type="application/octet-stream"
        )
        artifact["key"] = key
    new = Job(
        id=new_id,
        project_id=old.project_id,
        workspace_id=old.workspace_id,
        job_type=JobType.CAD_PDF_CONVERT,
        status=JobStatus.SUCCEEDED,
        attempt=1,
        max_attempts=old.max_attempts,
        payload=payload,
    )
    session.add(new)
    await session.flush()
    await session.execute(
        update(Job).where(Job.id == new_id).values(created_at=old.created_at + timedelta(hours=1))
    )
    await session.commit()
    session.expire_all()
    return new


async def test_previous_pair_is_used_while_new_walls_are_not_ready(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, old_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        new = await _clone_convert(db_session, fake_storage, old_id, revision_id)

        # Конструкций нового прогона нет совсем: этаж по прежней паре, предупреждение с датой.
        body = (await api.get(_url(project_id))).json()
        (floor,) = body["floors"]
        assert floor["job_id"] == old_id and floor["revision_id"] == revision_id
        assert (floor["page_index"], floor["view"]) == (0, 1)
        assert _codes(body) == ["floor_previous_run"]
        message = body["warnings"][0]["message"]
        assert "ещё не посчитаны" in message and "показан прежний результат от " in message

        # Задание конструкций в очереди, затем идёт, затем упало с кодом.
        queued = await api.post(walls_url(project_id, str(new.id), "walls"))
        assert queued.status_code == 202, queued.text
        walls_id = uuid.UUID(queued.json()["job_id"])
        body = (await api.get(_url(project_id))).json()
        assert body["floors"][0]["job_id"] == old_id
        assert "ещё не посчитаны" in body["warnings"][0]["message"]
        await db_session.execute(
            update(Job).where(Job.id == walls_id).values(status=JobStatus.RUNNING)
        )
        await db_session.commit()
        body = (await api.get(_url(project_id))).json()
        assert "считаются" in body["warnings"][0]["message"]
        await db_session.execute(
            update(Job)
            .where(Job.id == walls_id)
            .values(status=JobStatus.FAILED, error_code="WALLS_BROKEN")
        )
        await db_session.commit()
        body = (await api.get(_url(project_id))).json()
        assert body["floors"][0]["job_id"] == old_id
        assert "завершились ошибкой: WALLS_BROKEN" in body["warnings"][0]["message"]

        # Новые конструкции готовы: следующий запрос берёт новый прогон, предупреждения нет.
        again = await api.post(walls_url(project_id, str(new.id), "walls"))
        assert again.status_code == 202, again.text
        done = await _run_walls_worker(db_session, fake_storage, settings, again.json()["job_id"])
        assert done.status is JobStatus.SUCCEEDED
        body = (await api.get(_url(project_id))).json()
        (floor,) = body["floors"]
        assert floor["job_id"] == str(new.id)
        assert body["warnings"] == []


async def test_without_previous_pair_the_sheet_is_still_skipped(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    floor_tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = walls_settings(floor_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, old_id, walls_id = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        # Прежний прогон лишается без конструкций: пары нет ни у кого.
        await db_session.execute(
            update(Job).where(Job.id == uuid.UUID(walls_id)).values(status=JobStatus.FAILED)
        )
        await db_session.commit()
        await _clone_convert(db_session, fake_storage, old_id, revision_id)
        body = (await api.get(_url(project_id))).json()
    assert body["floors"] == []
    assert _codes(body) == ["walls_not_ready"]
