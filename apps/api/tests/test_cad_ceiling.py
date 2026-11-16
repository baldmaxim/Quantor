"""Потолок коридора для трасс механики: выбор из подтверждённых ответов и флаг генератора."""

from __future__ import annotations

import hashlib
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dev import DEV_USER_ID
from app.cad_worker.handler import CadError
from app.cad_worker.mep_handler import _check_levels, _generator_argv
from app.core.config import Settings
from app.core.workspace import DEV_WORKSPACE_ID
from app.domain import DocumentKind, JobType
from app.models import DocQuestionAnswer, Document, DocumentRevision, Job, Project, SheetPassport
from app.services import cad_ceiling
from app.services import cad_mep as cad_mep_service
from tests.conftest import clean_settings

CODE = "corridor_ceiling_height"


def _settings(*, consistency: bool = True) -> Settings:
    return clean_settings(
        environment="test",
        feature_flags="project.consistency=true" if consistency else "",
    )


async def _project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    project = Project(workspace_id=DEV_WORKSPACE_ID, name="ЖК Потолок")
    session.add(project)
    await session.flush()
    document = Document(project_id=project.id, display_name="АР", document_kind=DocumentKind.PDF)
    session.add(document)
    await session.flush()
    pdf = b"%PDF-1.7\n%test\n"
    revision = DocumentRevision(
        document_id=document.id,
        source_filename="АР.pdf",
        source_mime="application/pdf",
        source_size=len(pdf),
        source_sha256=hashlib.sha256(pdf).hexdigest(),
        storage_key=f"test/{uuid.uuid4()}",
    )
    session.add(revision)
    await session.flush()
    session.add(
        SheetPassport(
            project_id=project.id,
            revision_id=revision.id,
            page_index=0,
            file_name="План.pdf",
            status="confirmed",
            building="9",
            section="3",
        )
    )
    await session.commit()
    return project.id, revision.id


async def _answer(
    session: AsyncSession,
    project_id: uuid.UUID,
    number: int | None,
    *,
    building: str | None = None,
    source: str = "document",
) -> uuid.UUID:
    row = DocQuestionAnswer(
        project_id=project_id,
        question_code=CODE,
        scope_building=building,
        scope_section=None,
        source=source,
        value=None
        if number is None
        else {"kind": "length_mm", "display": str(number), "numbers": [number]},
        value_text=None if number is None else str(number),
        file_name="АР ПЗ.pdf" if source == "document" else None,
        page_index=3 if source == "document" else None,
        catalog_version="test",
        confirmed_by=DEV_USER_ID,
    )
    session.add(row)
    await session.commit()
    return row.id


async def _resolve(
    session: AsyncSession,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    settings: Settings | None = None,
) -> cad_ceiling.CeilingHeight:
    return await cad_ceiling.resolve_ceiling_height(
        session,
        settings=settings or _settings(),
        workspace_id=DEV_WORKSPACE_ID,
        project_id=project_id,
        plan_revision_id=revision_id,
        plan_page_index=0,
    )


async def test_no_answers_gives_nothing(db_session: AsyncSession) -> None:
    project_id, revision_id = await _project(db_session)
    assert await _resolve(db_session, project_id, revision_id) == cad_ceiling.CeilingHeight()


async def test_project_answer_is_used(db_session: AsyncSession) -> None:
    project_id, revision_id = await _project(db_session)
    answer = await _answer(db_session, project_id, 2900)
    result = await _resolve(db_session, project_id, revision_id)
    assert result.ceiling_height_mm == 2900 and result.warnings == ()
    assert result.doc_answer is not None
    assert result.doc_answer.answer_id == answer
    assert result.doc_answer.question_code == CODE


async def test_manual_answer_is_used(db_session: AsyncSession) -> None:
    project_id, revision_id = await _project(db_session)
    await _answer(db_session, project_id, 3000, source="manual")
    result = await _resolve(db_session, project_id, revision_id)
    assert result.ceiling_height_mm == 3000
    assert result.doc_answer is not None and result.doc_answer.file_name is None


async def test_building_answer_beats_project_answer(db_session: AsyncSession) -> None:
    project_id, revision_id = await _project(db_session)
    await _answer(db_session, project_id, 2700)
    narrow = await _answer(db_session, project_id, 2900, building="9")
    await _answer(db_session, project_id, 3300, building="10")  # чужой корпус
    result = await _resolve(db_session, project_id, revision_id)
    assert result.ceiling_height_mm == 2900
    assert result.doc_answer is not None and result.doc_answer.answer_id == narrow


async def test_different_values_on_the_best_scope_are_ambiguous(db_session: AsyncSession) -> None:
    project_id, revision_id = await _project(db_session)
    # Одна область на проект уникальна (uq_doc_question_answers_scope): равная точность для листа -
    # два ответа корпуса с разной записью, оба подходят корпусу 9.
    await _answer(db_session, project_id, 2700, building="9")
    await _answer(db_session, project_id, 2900, building="9, 10")
    result = await _resolve(db_session, project_id, revision_id)
    assert result.ceiling_height_mm is None and result.doc_answer is None
    assert result.warnings == ("ceiling_doc_ambiguous",)


async def test_value_out_of_limits_is_refused(db_session: AsyncSession) -> None:
    project_id, revision_id = await _project(db_session)
    await _answer(db_session, project_id, 5000)
    result = await _resolve(db_session, project_id, revision_id)
    assert result.ceiling_height_mm is None and result.doc_answer is None
    assert result.warnings == ("ceiling_doc_out_of_range",)


async def test_flag_off_gives_nothing(db_session: AsyncSession) -> None:
    project_id, revision_id = await _project(db_session)
    await _answer(db_session, project_id, 2900)
    result = await _resolve(db_session, project_id, revision_id, _settings(consistency=False))
    assert result == cad_ceiling.CeilingHeight()


def test_idempotency_key_includes_ceiling_only_when_given() -> None:
    approval = uuid.uuid4()

    answer_a, answer_b = uuid.uuid4(), uuid.uuid4()

    def key(ceiling: int | None = None, answer: uuid.UUID | None = None) -> str:
        return cad_mep_service.route_idempotency_key(
            approval,
            params_sha256="p" * 64,
            generator_version="cad_mep.v1",
            ceiling_height_mm=ceiling,
            ceiling_doc_answer_id=answer,
        )

    keys = {key(), key(2900), key(3000), key(2900, answer_a), key(2900, answer_b)}
    assert len(keys) == 5  # другой ответ с тем же числом - тоже новое задание
    assert key() == cad_mep_service.route_idempotency_key(
        approval, params_sha256="p" * 64, generator_version="cad_mep.v1"
    )


def _argv(tmp_path: Path, payload: dict[str, object]) -> list[str]:
    runner = tmp_path / "run_mep.py"
    runner.write_text("", encoding="utf-8")
    settings = clean_settings(
        environment="test", cad_engine_python=sys.executable, cad_mep_runner=str(runner)
    )
    files = {
        name: tmp_path / name for name in ("plan_candidates.dxf", "scale.json", "preview.json")
    }
    job = Job(job_type=JobType.CAD_MEP_ROUTE, payload={"approval_id": "a", **payload})
    return _generator_argv(
        settings,
        source=tmp_path / "in.pdf",
        parent_files=files,
        params=tmp_path / "params.json",
        out=tmp_path / "out",
        job=job,
        folder="views/p001_v01",
        page_index=0,
    )


def test_generator_gets_the_ceiling_flag_only_when_in_payload(tmp_path: Path) -> None:
    argv = _argv(tmp_path, {"ceiling_height_mm": 2900})
    assert argv[argv.index("--ceiling-height-mm") + 1] == "2900"
    assert "--ceiling-height-mm" not in _argv(tmp_path, {})
    assert "--ceiling-height-mm" not in _argv(tmp_path, {"ceiling_height_mm": None})


def test_ceiling_payload_check() -> None:
    _check_levels({"ceiling_height_mm": 2900})
    _check_levels({"ceiling_height_mm": None})
    for bad in (1999, 4501, "2900", 2900.0):
        with pytest.raises(CadError):
            _check_levels({"ceiling_height_mm": bad})
