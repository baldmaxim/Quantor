"""Вопросы к документации (В3): задание поиска кандидатов по тексту страниц, синтетика."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import JobStatus, JobType
from app.main import create_app
from app.models import DocQuestionCandidate, Job, RevisionPageText, SheetPassport
from app.services import jobs as jobs_service
from app.services.consistency.doc_questions import DOC_QUESTIONS_VERSION
from app.worker.registry import supported_types
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.doc_questions_support import (
    AR_PDF,
    CEILING_TEXT,
    EMPTY_PDF,
    KR_PDF,
    add_passport,
    add_pdf,
    add_text,
    doc_settings,
    make_project,
    questions_url,
    run_search_job,
    search,
    standard_project,
)


def test_routes_are_in_openapi_and_job_is_registered() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}"
    assert set(paths[f"{base}/doc-questions"]) == {"get"}
    assert set(paths[f"{base}/doc-questions/search"]) == {"post"}
    assert set(paths[f"{base}/doc-questions/{{code}}/answers"]) == {"post"}
    assert set(paths[f"{base}/doc-questions/answers/{{answer_id}}"]) == {"delete"}
    assert set(paths[f"{base}/doc-questions/candidates/{{candidate_id}}/reject"]) == {"post"}
    assert set(paths[f"{base}/doc-answers"]) == {"get"}
    assert JobType.DOC_QUESTIONS_SEARCH.value in supported_types()


async def test_search_saves_candidates_with_scope_and_reports_no_text(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, revisions = await standard_project(api, db_session, fake_storage, tmp_path)

        first = await api.post(questions_url(project_id, "/search"))
        assert first.status_code == 202, first.text
        assert first.json()["job_type"] == "doc_questions_search"
        # Активное задание возвращается, второе не ставится.
        second = await api.post(questions_url(project_id, "/search"))
        assert second.json()["id"] == first.json()["id"]
        assert len((await db_session.scalars(select(Job))).all()) == 1

        job = await search(api, db_session, fake_storage, project_id)
        assert job.status is JobStatus.SUCCEEDED
        payload = job.payload
        assert payload["revisions_total"] == 3 and payload["revisions_scanned"] == 2
        assert payload["revisions_no_text"] == 1 and payload["no_text_files"] == [EMPTY_PDF]
        assert payload["revisions_unreadable"] == 0 and payload["unreadable_files"] == []
        assert payload["questions_found"] == 2 and payload["candidates"] == 2
        assert payload["versions"]["catalog"] == DOC_QUESTIONS_VERSION

        view = (await api.get(questions_url(project_id))).json()
        assert view["catalog_version"] == DOC_QUESTIONS_VERSION
        assert len(view["questions"]) == 12
        by_code = {item["code"]: item for item in view["questions"]}
        slab = by_code["slab_thickness"]["candidates"]
        assert len(slab) == 1
        assert slab[0]["value"]["numbers"] == [200] and slab[0]["value_text"] == "200 мм"
        assert slab[0]["file_name"] == KR_PDF and slab[0]["revision_id"] == str(revisions["kr"].id)
        assert (slab[0]["building"], slab[0]["section"]) == ("9", "3")
        assert slab[0]["status"] == "candidate" and slab[0]["score"] > 0
        assert "плиты перекрытия" in slab[0]["quote"]
        ceiling = by_code["corridor_ceiling_height"]["candidates"]
        assert [c["page_index"] for c in ceiling] == [1] and ceiling[0]["file_name"] == AR_PDF
        assert by_code["duct_section"]["candidates"] == []
        assert by_code["duct_section"]["assumption"] is None
        assert by_code["sprinkler_ceiling_gap"]["assumption"]["reference"].startswith("СП 485")

        summary = view["last_search"]
        assert summary["status"] == "succeeded" and summary["candidates"] == 2
        assert summary["revisions_no_text"] == 1 and summary["no_text_files"] == [EMPTY_PDF]


async def test_rerun_replaces_candidates_and_rejected_do_not_resurrect(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await standard_project(api, db_session, fake_storage, tmp_path)
        await search(api, db_session, fake_storage, project_id)
        view = (await api.get(questions_url(project_id))).json()
        by_code = {item["code"]: item for item in view["questions"]}
        slab_id = by_code["slab_thickness"]["candidates"][0]["id"]
        ceiling_id = by_code["corridor_ceiling_height"]["candidates"][0]["id"]

        rejected = await api.post(questions_url(project_id, f"/candidates/{slab_id}/reject"))
        assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"

        second = await search(api, db_session, fake_storage, project_id)
        assert second.payload["candidates"] == 1
        rows = (await db_session.scalars(select(DocQuestionCandidate))).all()
        by_status = {(row.question_code, row.status) for row in rows}
        # Отклонённый остался один (не продублирован, не воскрес); новый candidate - потолок.
        assert by_status == {
            ("slab_thickness", "rejected"),
            ("corridor_ceiling_height", "candidate"),
        }
        view = (await api.get(questions_url(project_id))).json()
        by_code = {item["code"]: item for item in view["questions"]}
        assert by_code["slab_thickness"]["candidates"] == []
        new_ceiling = by_code["corridor_ceiling_height"]["candidates"]
        # Кандидаты пересобраны: прежний id заменён новым.
        assert len(new_ceiling) == 1 and new_ceiling[0]["id"] != ceiling_id


async def test_changed_value_is_a_new_candidate_after_rejection(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id = await make_project(api)
        ar = await add_pdf(db_session, fake_storage, project_id, AR_PDF)
        await add_text(db_session, fake_storage, tmp_path, project_id, ar, [CEILING_TEXT])
        await add_passport(db_session, project_id, ar, 0, section_mark="АР")
        await search(api, db_session, fake_storage, project_id)
        view = (await api.get(questions_url(project_id))).json()
        first = next(q for q in view["questions"] if q["code"] == "corridor_ceiling_height")
        candidate_id = first["candidates"][0]["id"]
        await api.post(questions_url(project_id, f"/candidates/{candidate_id}/reject"))

        # Ревизия переписана: в тексте другая высота, значит ключ отказа не совпадает.
        await db_session.execute(delete(RevisionPageText))
        await db_session.commit()
        await add_text(
            db_session,
            fake_storage,
            tmp_path,
            project_id,
            ar,
            [CEILING_TEXT.replace("2700", "3000")],
        )
        await search(api, db_session, fake_storage, project_id)
        view = (await api.get(questions_url(project_id))).json()
        ceiling = next(q for q in view["questions"] if q["code"] == "corridor_ceiling_height")
        assert [c["value"]["numbers"] for c in ceiling["candidates"]] == [[3000]]


async def test_unreadable_revision_is_reported_and_keeps_its_old_candidates(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, revisions = await standard_project(api, db_session, fake_storage, tmp_path)
        await search(api, db_session, fake_storage, project_id)

        # Объект текста КР пропал из хранилища: ревизия не читается, остальные идут как шли.
        row = await db_session.get(RevisionPageText, revisions["kr"].id)
        assert row is not None
        fake_storage.objects.pop(row.storage_key)
        job = await search(api, db_session, fake_storage, project_id)
        assert job.status is JobStatus.SUCCEEDED
        assert job.payload["revisions_scanned"] == 1
        assert job.payload["revisions_unreadable"] == 1
        assert job.payload["unreadable_files"] == [KR_PDF]
        view = (await api.get(questions_url(project_id))).json()
        by_code = {item["code"]: item for item in view["questions"]}
        # Старый кандидат плиты не потерян: текст КР не перепроверен.
        assert len(by_code["slab_thickness"]["candidates"]) == 1
        assert len(by_code["corridor_ceiling_height"]["candidates"]) == 1
        assert view["last_search"]["unreadable_files"] == [KR_PDF]


async def test_project_without_pdfs_finishes_with_zero_counts(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id = await make_project(api)
        job = await search(api, db_session, fake_storage, project_id)
        assert job.status is JobStatus.SUCCEEDED
        assert job.payload["revisions_total"] == 0 and job.payload["candidates"] == 0
        assert job.payload["questions_found"] == 0
        view = (await api.get(questions_url(project_id))).json()
        assert all(item["candidates"] == [] for item in view["questions"])


async def test_job_without_project_reference_fails_with_code(
    db_session: AsyncSession, fake_storage: FakeObjectStorage
) -> None:
    await jobs_service.enqueue(
        db_session,
        job_type=JobType.DOC_QUESTIONS_SEARCH,
        workspace_id=make_context().tenant,
        payload={},
    )
    await db_session.commit()
    job = await run_search_job(db_session, fake_storage)
    assert job.status is JobStatus.FAILED and job.error_code == "DOC_QUESTIONS_SEARCH_FAILED"


async def test_customer_document_is_found_by_heading_on_all_pages(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    """Договор опознаётся по заголовку 1-й страницы; вопросы ищутся и на следующих, без паспорта."""
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id = await make_project(api)
        contract = await add_pdf(db_session, fake_storage, project_id, "scan_0001.pdf")
        await add_text(
            db_session,
            fake_storage,
            tmp_path,
            project_id,
            contract,
            ["Договор подряда № 5", "Приложение", CEILING_TEXT],
        )
        job = await search(api, db_session, fake_storage, project_id)
        assert job.payload["candidates"] == 1
        row = (await db_session.scalars(select(DocQuestionCandidate))).one()
        assert row.question_code == "corridor_ceiling_height" and row.page_index == 2
        # Отметка раздела не задана, область не определена - значит null, а не догадка.
        assert row.building is None and row.section is None and row.level is None


async def test_rejected_passport_is_ignored(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await standard_project(api, db_session, fake_storage, tmp_path)
        await db_session.execute(
            update(SheetPassport)
            .where(SheetPassport.section_mark == "КР")
            .values(status="rejected")
        )
        await db_session.commit()
        job = await search(api, db_session, fake_storage, project_id)
        # Без паспорта КР-страница не подходит ни под один источник: плиты среди кандидатов нет.
        assert job.payload["candidates"] == 1
        rows = (await db_session.scalars(select(DocQuestionCandidate))).all()
        assert [row.question_code for row in rows] == ["corridor_ceiling_height"]
