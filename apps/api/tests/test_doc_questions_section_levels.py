"""Вопросы к документации: кандидаты из уровней по разрезам (плита из разреза не берётся)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dev import DEV_USER_ID
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import JobType
from app.models import CadSectionLevel, DocumentRevision
from app.services import jobs as jobs_service
from app.services.doc_questions import SECTION_ACCEPTED_SCORE, SECTION_CANDIDATE_SCORE
from tests.conftest import FakeObjectStorage, make_context
from tests.doc_questions_support import (
    AR_PDF,
    KR_PDF,
    add_passport,
    add_pdf,
    add_text,
    doc_settings,
    make_project,
    questions_url,
    search,
)

BOX = [0.1, 0.1, 0.2, 0.2]
KR_SLAB_TEXT = "План несущих конструкций 4–20 этажа С3 в осях 1-17. Примечание: тщ. плиты 200 мм."
CLEAR_TEXT = "Высота 3,2 м от уровня чистого пола до низа ж/б плиты перекрытия, этаж."


async def add_level(
    session: AsyncSession,
    *,
    project_id: str,
    revision: DocumentRevision,
    job_id: uuid.UUID,
    seq: int,
    elevation: int,
    clear: int | None,
    slab: int | None = 300,
    status: str = "candidate",
    page_index: int = 0,
    corps: str | None = "9",
    section: str | None = "3",
) -> None:
    decided = status != "candidate"
    session.add(
        CadSectionLevel(
            workspace_id=DEV_WORKSPACE_ID,
            project_id=uuid.UUID(project_id),
            job_id=job_id,
            revision_id=revision.id,
            seq=seq,
            page_index=page_index,
            cut="1-1",
            corps=corps,
            section=section,
            elevation_mm=elevation,
            upper_elevation_mm=elevation + 3300,
            clear_height_mm=clear,
            structure_mm=slab,
            evidence="синтетика",
            markup={"upper_mark": BOX, "lower_mark": BOX, "band": BOX, "dims": []},
            status=status,
            decided_by=DEV_USER_ID if decided else None,
            decided_at=datetime.now(UTC) if decided else None,
        )
    )
    await session.commit()


async def sections_job(session: AsyncSession, project_id: str) -> uuid.UUID:
    job = await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_SECTIONS,
        workspace_id=DEV_WORKSPACE_ID,
        project_id=uuid.UUID(project_id),
        payload={"revision_id": "-"},
    )
    await session.commit()
    return job.id


async def test_section_levels_become_candidates_accepted_above_text_rejected_ignored(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id = await make_project(api)
        ar = await add_pdf(db_session, fake_storage, project_id, AR_PDF)
        await add_text(db_session, fake_storage, tmp_path, project_id, ar, [CLEAR_TEXT])
        await add_passport(db_session, project_id, ar, 0, section_mark="АР")
        job_id = await sections_job(db_session, project_id)
        common = {"project_id": project_id, "revision": ar, "job_id": job_id}
        # 3000: два принятых уровня; 3200: один непринятый (совпадает с текстом ПЗ);
        # 2800: отклонённый; 4000: непринятый с другой толщиной плиты; без высоты - пропуск.
        await add_level(
            db_session, seq=0, elevation=47600, clear=3000, slab=300, status="accepted", **common
        )
        await add_level(
            db_session, seq=1, elevation=50900, clear=3000, slab=300, status="accepted", **common
        )
        await add_level(db_session, seq=2, elevation=54200, clear=3200, slab=250, **common)
        await add_level(
            db_session, seq=3, elevation=57500, clear=2800, slab=900, status="rejected", **common
        )
        await add_level(db_session, seq=4, elevation=60800, clear=None, slab=None, **common)
        await add_level(db_session, seq=5, elevation=64100, clear=4000, slab=350, **common)

        job = await search(api, db_session, fake_storage, project_id)
        assert job.payload["questions_found"] >= 1

        view = (await api.get(questions_url(project_id))).json()
        by_code = {item["code"]: item for item in view["questions"]}

        clear = by_code["clear_height"]["candidates"]
        assert [c["value"]["numbers"][0] for c in clear] == [3000, 3200, 4000]
        accepted, medium, other = clear
        assert accepted["score"] == SECTION_ACCEPTED_SCORE and accepted["occurrences"] == 2
        assert accepted["quote"].startswith("Разрез, отм. +47.600, +50.900: высота в свету 3000 мм")
        assert accepted["quote"].endswith("(уровней: 2)")
        assert accepted["revision_id"] == str(ar.id) and accepted["file_name"] == AR_PDF
        assert (accepted["building"], accepted["section"]) == ("9", "3")
        assert medium["score"] <= SECTION_CANDIDATE_SCORE + 40  # у 3200 есть и текстовая находка
        assert other["score"] == SECTION_CANDIDATE_SCORE
        assert accepted["score"] > medium["score"] > 0
        assert 2800 not in [c["value"]["numbers"][0] for c in clear], "отклонённый не берётся"
        assert all(c["status"] == "candidate" for c in clear)

        # «Конструкция» разреза (плита + пол) - не толщина плиты: кандидатов плиты из разреза нет.
        assert by_code["slab_thickness"]["candidates"] == []


async def test_slab_from_kr_text_not_from_section_structure(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id = await make_project(api)
        kr = await add_pdf(db_session, fake_storage, project_id, KR_PDF)
        ar = await add_pdf(db_session, fake_storage, project_id, AR_PDF)
        await add_text(db_session, fake_storage, tmp_path, project_id, kr, [KR_SLAB_TEXT])
        await add_passport(db_session, project_id, kr, 0, section_mark="КР")
        job_id = await sections_job(db_session, project_id)
        await add_level(
            db_session,
            project_id=project_id,
            revision=ar,
            job_id=job_id,
            seq=0,
            elevation=47600,
            clear=3000,
            slab=300,
            status="accepted",
        )
        await search(api, db_session, fake_storage, project_id)
        view = (await api.get(questions_url(project_id))).json()
        slab = next(q for q in view["questions"] if q["code"] == "slab_thickness")["candidates"]
        assert [c["value"]["numbers"][0] for c in slab] == [200]
        assert slab[0]["file_name"] == KR_PDF


async def test_rejected_section_candidate_does_not_resurrect_on_rerun(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id = await make_project(api)
        ar = await add_pdf(db_session, fake_storage, project_id, AR_PDF)
        job_id = await sections_job(db_session, project_id)
        await add_level(
            db_session,
            project_id=project_id,
            revision=ar,
            job_id=job_id,
            seq=0,
            elevation=47600,
            clear=3000,
            slab=None,
        )
        await search(api, db_session, fake_storage, project_id)
        view = (await api.get(questions_url(project_id))).json()
        clear = next(q for q in view["questions"] if q["code"] == "clear_height")["candidates"]
        assert [c["score"] for c in clear] == [SECTION_CANDIDATE_SCORE]
        rejected = await api.post(questions_url(project_id, f"/candidates/{clear[0]['id']}/reject"))
        assert rejected.status_code == 200

        await search(api, db_session, fake_storage, project_id)
        view = (await api.get(questions_url(project_id))).json()
        again = next(q for q in view["questions"] if q["code"] == "clear_height")
        assert again["candidates"] == []
