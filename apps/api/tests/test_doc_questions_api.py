"""Вопросы к документации (В3): ответы четырёх источников, область, отказ, доступ, синтетика."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import Role
from app.models import DocQuestionAnswer, DocQuestionCandidate, Workspace
from tests.conftest import FakeObjectStorage, make_context
from tests.doc_questions_support import (
    doc_settings,
    questions_url,
    search,
    standard_project,
)


def _answers_url(project_id: str, code: str) -> str:
    return questions_url(project_id, f"/{code}/answers")


def _flat_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/doc-answers"


async def _view(api: AsyncClient, project_id: str) -> dict[str, dict[str, Any]]:
    body = (await api.get(questions_url(project_id))).json()
    return {item["code"]: item for item in body["questions"]}


def _manual(numbers: list[int], **extra: Any) -> dict[str, Any]:
    return {
        "source": "manual",
        "value_text": "по ведомости отделки",
        "value": {"numbers": numbers, **extra},
        "note": "лист 12 ведомости",
    }


async def test_flag_off_closes_all_routes(build_api: Callable[..., AsyncClient]) -> None:
    async with build_api(make_context(), settings=doc_settings(flag=False)) as api:
        project_id, some_id = str(uuid.uuid4()), str(uuid.uuid4())
        responses = [
            await api.post(questions_url(project_id, "/search")),
            await api.get(questions_url(project_id)),
            await api.post(
                _answers_url(project_id, "slab_thickness"), json={"source": "not_in_project"}
            ),
            await api.delete(questions_url(project_id, f"/answers/{some_id}")),
            await api.post(questions_url(project_id, f"/candidates/{some_id}/reject")),
            await api.get(_flat_url(project_id)),
        ]
    for response in responses:
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_all_four_sources_and_flat_answers(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, revisions = await standard_project(api, db_session, fake_storage, tmp_path)
        await search(api, db_session, fake_storage, project_id)
        view = await _view(api, project_id)
        slab = view["slab_thickness"]["candidates"][0]

        # Пока ничего не подтверждено, doc-answers пуст: кандидат - не ответ.
        assert (await api.get(_flat_url(project_id))).json() == {"items": []}

        # document: область по умолчанию - область кандидата, происхождение копируется.
        doc = await api.post(
            _answers_url(project_id, "slab_thickness"),
            json={"source": "document", "candidate_id": slab["id"]},
        )
        assert doc.status_code == 200, doc.text
        body = doc.json()
        assert body["source"] == "document" and body["candidate_id"] == slab["id"]
        assert (body["scope_building"], body["scope_section"]) == ("9", "3")
        assert body["value"]["numbers"] == [200] and body["value_text"] == "200 мм"
        assert body["file_name"] == slab["file_name"] and body["page_index"] == 0
        assert body["revision_id"] == str(revisions["kr"].id) and "плиты" in body["quote"]
        assert body["catalog_version"] == "consistency.doc_questions.v1"
        assert body["confirmed_by"] is not None and body["confirmed_at"] is not None

        # manual: display собирает сервер; без пояснения и с числом вне границ - 422.
        manual = await api.post(
            _answers_url(project_id, "corridor_ceiling_height"), json=_manual([2800])
        )
        assert manual.status_code == 200, manual.text
        assert manual.json()["value"] == {
            "kind": "length_mm",
            "display": "2800",
            "numbers": [2800],
            "qualifier": None,
            "code": None,
        }
        assert manual.json()["scope_building"] is None and manual.json()["note"]

        # norm_assumption: значение и ссылка из каталога; вопрос без норматива - 422.
        norm = await api.post(
            _answers_url(project_id, "sprinkler_ceiling_gap"), json={"source": "norm_assumption"}
        )
        assert norm.status_code == 200, norm.text
        assert norm.json()["value"]["numbers"] == [80, 300]
        assert norm.json()["norm_ref"].startswith("СП 485.1311500.2020")
        assert norm.json()["value_text"].startswith("80-300 мм (СП 485")
        assert norm.json()["note"]
        cold = await api.post(
            _answers_url(project_id, "hot_over_cold_gap"), json={"source": "norm_assumption"}
        )
        assert (
            cold.json()["value"]["numbers"] == [100] and cold.json()["value"]["qualifier"] == "min"
        )
        no_norm = await api.post(
            _answers_url(project_id, "slab_thickness"),
            json={"source": "norm_assumption", "scope_building": "1"},
        )
        assert no_norm.status_code == 422

        # not_in_project: значения нет (не 0), примечание необязательно.
        absent = await api.post(
            _answers_url(project_id, "duct_section"),
            json={"source": "not_in_project", "note": "в ПЗ ИОС4 нет"},
        )
        assert absent.status_code == 200, absent.text
        assert absent.json()["value"] is None and absent.json()["value_text"] is None

        # doc-answers: плоский список только подтверждённого, по порядку каталога.
        flat = (await api.get(_flat_url(project_id))).json()["items"]
        assert [(i["receiver_param"], i["source"]) for i in flat] == [
            ("corridor_ceiling_height_mm", "manual"),
            ("slab_thickness_mm", "document"),
            ("sprinkler_ceiling_gap_mm", "norm_assumption"),
            ("hot_over_cold_gap_mm", "norm_assumption"),
            ("duct_section_mm", "not_in_project"),
        ]
        slab_item = flat[1]
        assert slab_item["scope"] == {"building": "9", "section": "3"}
        assert slab_item["file_name"] == slab["file_name"] and slab_item["value"]["numbers"] == [
            200
        ]
        assert slab_item["page_index"] == 0 and slab_item["quote"] and slab_item["confirmed_at"]
        assert flat[2]["norm_ref"] and flat[4]["value"] is None
        assert all(item["catalog_version"] for item in flat)
        # Кандидаты вместе с ответами в обзоре вопроса.
        assert len((await _view(api, project_id))["slab_thickness"]["answers"]) == 1


async def test_answer_in_same_scope_is_replaced_other_scopes_coexist(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await standard_project(api, db_session, fake_storage, tmp_path)
        url = _answers_url(project_id, "corridor_ceiling_height")
        first = await api.post(url, json=_manual([2700]))
        second = await api.post(url, json=_manual([2900]))
        # Тот же проект целиком: ответ заменён, id сохранён.
        assert first.json()["id"] == second.json()["id"]
        rows = (await db_session.scalars(select(DocQuestionAnswer))).all()
        assert len(rows) == 1 and rows[0].value is not None and rows[0].value["numbers"] == [2900]

        # Корпус и секция - отдельные области; пустая строка области равна «весь проект».
        corpus = await api.post(url, json={**_manual([3000]), "scope_building": "9"})
        section = await api.post(
            url, json={**_manual([3100]), "scope_building": "9", "scope_section": "3"}
        )
        whole_again = await api.post(url, json={**_manual([2500]), "scope_building": "  "})
        assert whole_again.json()["id"] == first.json()["id"]
        assert len({corpus.json()["id"], section.json()["id"], first.json()["id"]}) == 3
        answers = (await _view(api, project_id))["corridor_ceiling_height"]["answers"]
        assert [(a["scope_building"], a["scope_section"]) for a in answers] == [
            (None, None),
            ("9", None),
            ("9", "3"),
        ]
        # Замена не оставляет следов прежнего источника.
        replaced = await api.post(url, json={"source": "not_in_project"})
        assert replaced.json()["id"] == first.json()["id"] and replaced.json()["value"] is None
        assert replaced.json()["note"] is None and replaced.json()["file_name"] is None


async def test_manual_validation(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await standard_project(api, db_session, fake_storage, tmp_path)

        async def post(code: str, body: dict[str, Any]) -> int:
            return (await api.post(_answers_url(project_id, code), json=body)).status_code

        height = "corridor_ceiling_height"  # length_mm, 2000-4500
        assert await post(height, _manual([1500])) == 422
        assert await post(height, _manual([5000])) == 422
        assert await post(height, _manual([2700, 2800])) == 422
        assert await post(height, _manual([])) == 422
        assert await post(height, {**_manual([2700]), "note": "  "}) == 422
        assert await post(height, {**_manual([2700]), "value_text": ""}) == 422
        assert await post(height, {k: v for k, v in _manual([2700]).items() if k != "note"}) == 422
        assert await post(height, {**_manual([2700]), "extra": 1}) == 422
        assert await post(height, _manual([2700], qualifier="min")) == 200
        assert await post(height, _manual([2700], code="round")) == 422

        # section_mm: ширина и высота, каждая в границах каталога (кабельный лоток 20-1000).
        tray = "cable_tray_section"
        ok = await api.post(_answers_url(project_id, tray), json=_manual([200, 100]))
        assert ok.status_code == 200 and ok.json()["value"]["display"] == "200x100"
        assert await post(tray, _manual([200])) == 422
        assert await post(tray, _manual([200, 100, 50])) == 422
        assert await post(tray, _manual([5, 100])) == 422
        assert await post(tray, _manual([200, 2000])) == 422
        assert await post(tray, _manual([200], code="round")) == 422
        # Круглое сечение - только у воздуховода ДУ / ДП.
        duct = "duct_section"
        round_duct = await api.post(
            _answers_url(project_id, duct), json=_manual([315], code="round")
        )
        assert round_duct.status_code == 200 and round_duct.json()["value"]["display"] == "Ø315"
        assert await post(duct, _manual([315])) == 422
        assert await post(duct, _manual([800, 400])) == 200

        # range_mm (зазор оросителя 20-1500): одно число или «от < до».
        gap = "sprinkler_ceiling_gap"
        assert (await api.post(_answers_url(project_id, gap), json=_manual([100, 300]))).json()[
            "value"
        ]["display"] == "100-300"
        assert await post(gap, _manual([300, 100])) == 422
        assert await post(gap, _manual([10, 100])) == 422
        assert await post(gap, _manual([100, 200, 300])) == 422
        assert await post(gap, _manual([150])) == 200

        # enum: только текст и код розетки; text: числа в границах каталога.
        model = "sprinkler_model"
        enum_body = {**_manual([]), "value_text": "СВН-12 розеткой вниз"}
        enum_ok = await api.post(
            _answers_url(project_id, model),
            json={**enum_body, "value": {"code": "rosette_down"}},
        )
        assert enum_ok.status_code == 200
        assert enum_ok.json()["value"]["display"] == "СВН-12 розеткой вниз"
        assert await post(model, {**enum_body, "value": {"code": "other"}}) == 422
        assert await post(model, {**enum_body, "value": {"numbers": [5]}}) == 422
        floor = "corridor_floor_buildup"
        assert await post(floor, _manual([70])) == 200
        assert await post(floor, _manual([5000])) == 422
        # Неизвестный вопрос и неизвестный источник.
        assert await post("no_such_question", {"source": "not_in_project"}) == 422
        assert await post(height, {"source": "guess"}) == 422


async def test_document_answer_rules_and_survives_rerun(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await standard_project(api, db_session, fake_storage, tmp_path)
        other_project = (await api.post("/api/v1/projects", json={"name": "Другой"})).json()["id"]
        await search(api, db_session, fake_storage, project_id)
        view = await _view(api, project_id)
        slab = view["slab_thickness"]["candidates"][0]
        ceiling = view["corridor_ceiling_height"]["candidates"][0]

        # Кандидат другого вопроса, чужого проекта и несуществующий - не принимаются.
        wrong = await api.post(
            _answers_url(project_id, "slab_thickness"),
            json={"source": "document", "candidate_id": ceiling["id"]},
        )
        assert wrong.status_code == 422
        foreign = await api.post(
            _answers_url(other_project, "slab_thickness"),
            json={"source": "document", "candidate_id": slab["id"]},
        )
        assert foreign.status_code == 404
        missing = await api.post(
            _answers_url(project_id, "slab_thickness"),
            json={"source": "document", "candidate_id": str(uuid.uuid4())},
        )
        assert missing.status_code == 404

        # Явная область переопределяет область кандидата; null - весь проект.
        whole = await api.post(
            _answers_url(project_id, "slab_thickness"),
            json={"source": "document", "candidate_id": slab["id"], "scope_building": None},
        )
        assert whole.status_code == 200
        assert (whole.json()["scope_building"], whole.json()["scope_section"]) == (None, None)

        # Отклонённого кандидата ответом не сделать.
        rejected = await api.post(questions_url(project_id, f"/candidates/{slab['id']}/reject"))
        assert rejected.status_code == 200
        again = await api.post(questions_url(project_id, f"/candidates/{slab['id']}/reject"))
        assert again.status_code == 200 and again.json()["status"] == "rejected"
        refused = await api.post(
            _answers_url(project_id, "slab_thickness"),
            json={"source": "document", "candidate_id": slab["id"]},
        )
        assert refused.status_code == 422

        # Повторный поиск пересобирает кандидатов, ответ с происхождением остаётся.
        await search(api, db_session, fake_storage, project_id)
        gone = await db_session.get(DocQuestionCandidate, uuid.UUID(slab["id"]))
        db_session.expire_all()
        row = (await db_session.scalars(select(DocQuestionAnswer))).one()
        assert gone is not None  # отклонённый хранится
        assert row.candidate_id == uuid.UUID(slab["id"]) and row.quote and row.file_name
        ceiling_answer = await api.post(
            _answers_url(project_id, "corridor_ceiling_height"),
            json={"source": "document", "candidate_id": ceiling["id"]},
        )
        assert ceiling_answer.status_code == 404  # прежний кандидат заменён новым
        await search(api, db_session, fake_storage, project_id)
        flat = (await api.get(_flat_url(project_id))).json()["items"]
        assert [item["question_code"] for item in flat] == ["slab_thickness"]
        assert flat[0]["quote"] and flat[0]["file_name"] and flat[0]["page_index"] == 0


async def test_candidate_replaced_by_search_leaves_answer_with_snapshot(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await standard_project(api, db_session, fake_storage, tmp_path)
        await search(api, db_session, fake_storage, project_id)
        ceiling = (await _view(api, project_id))["corridor_ceiling_height"]["candidates"][0]
        made = await api.post(
            _answers_url(project_id, "corridor_ceiling_height"),
            json={"source": "document", "candidate_id": ceiling["id"]},
        )
        assert made.status_code == 200
        await search(api, db_session, fake_storage, project_id)
        db_session.expire_all()
        row = (await db_session.scalars(select(DocQuestionAnswer))).one()
        # Кандидат удалён пересборкой: связь снята, снимок происхождения на месте.
        assert row.candidate_id is None
        assert row.quote and row.file_name and row.page_index == 1 and row.revision_id is not None
        flat = (await api.get(_flat_url(project_id))).json()["items"]
        assert flat[0]["value"]["numbers"] == [2700] and flat[0]["quote"] == row.quote


async def test_delete_answer(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=doc_settings()) as api:
        project_id, _ = await standard_project(api, db_session, fake_storage, tmp_path)
        other_project = (await api.post("/api/v1/projects", json={"name": "Другой"})).json()["id"]
        made = await api.post(
            _answers_url(project_id, "corridor_ceiling_height"), json=_manual([2700])
        )
        answer_id = made.json()["id"]
        assert (
            await api.delete(questions_url(other_project, f"/answers/{answer_id}"))
        ).status_code == 404
        assert (
            await api.delete(questions_url(project_id, f"/answers/{uuid.uuid4()}"))
        ).status_code == 404
        assert (
            await api.delete(questions_url(project_id, f"/answers/{answer_id}"))
        ).status_code == 204
        assert (await api.get(_flat_url(project_id))).json() == {"items": []}
        assert (
            await api.delete(questions_url(project_id, f"/answers/{answer_id}"))
        ).status_code == 404


async def test_foreign_workspace_gets_404_and_viewer_cannot_write(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    second_workspace: Workspace,
    tmp_path: Path,
) -> None:
    settings = doc_settings()
    async with build_api(make_context(), settings=settings) as api:
        project_id, _ = await standard_project(api, db_session, fake_storage, tmp_path)
        await search(api, db_session, fake_storage, project_id)
        made = await api.post(
            _answers_url(project_id, "corridor_ceiling_height"), json=_manual([2700])
        )
        answer_id = made.json()["id"]
        candidate = (await _view(api, project_id))["slab_thickness"]["candidates"][0]["id"]

    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        responses = [
            await foreign.post(questions_url(project_id, "/search")),
            await foreign.get(questions_url(project_id)),
            await foreign.get(_flat_url(project_id)),
            await foreign.post(_answers_url(project_id, "slab_thickness"), json=_manual([200])),
            await foreign.delete(questions_url(project_id, f"/answers/{answer_id}")),
            await foreign.post(questions_url(project_id, f"/candidates/{candidate}/reject")),
        ]
    assert [response.status_code for response in responses] == [404] * 6
    assert len((await db_session.scalars(select(DocQuestionAnswer))).all()) == 1

    async with build_api(make_context(Role.VIEWER), settings=settings) as viewer:
        assert (await viewer.get(questions_url(project_id))).status_code == 200
        assert (await viewer.get(_flat_url(project_id))).status_code == 200
        writes = [
            await viewer.post(questions_url(project_id, "/search")),
            await viewer.post(_answers_url(project_id, "slab_thickness"), json=_manual([200])),
            await viewer.delete(questions_url(project_id, f"/answers/{answer_id}")),
            await viewer.post(questions_url(project_id, f"/candidates/{candidate}/reject")),
        ]
    assert [response.status_code for response in writes] == [403] * 4
