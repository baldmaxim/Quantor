"""ИИ-сопоставление ВОР: пакет без количеств, проверка отчёта, роль промта, задание и API."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import cad_vor_fill
from app.cad_worker import ai_vor_map
from app.cad_worker.ai_vor_map import execute_ai_vor_map
from app.cad_worker.ai_vor_map_cli import PACKAGE_FILES, REMOTE, remote_command
from app.contracts.ai_prompts import AiPromptCreate
from app.contracts.ai_vor_map import AiVorMapReport
from app.contracts.cad_ai_review import AiLoopPilot
from app.contracts.vor_fill import VorObjectRead
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.models import AiPromptVersion, CadVorDocument, CadVorItem, Job
from app.services import jobs
from tests.conftest import make_context
from tests.test_cad_vor_api import ROWS, _project, _upload, vor_settings

JOB = uuid.uuid4()


def _object(key: str, kind: str, title: str, quantities: list[dict[str, Any]]) -> VorObjectRead:
    return VorObjectRead.model_validate(
        {
            "group_key": key,
            "kind": kind,
            "title": title,
            "quantities": quantities,
            "incomplete": False,
            "sources": [
                {"label": "План 1", "job_id": str(JOB), "page_index": 0, "view": 1, "note": None}
            ],
        }
    )


OBJECTS = [
    _object(
        "masonry|190|aerated_concrete",
        "construction",
        "Кладка, 190 мм, газобетон",
        [{"unit": "m3", "value": 777.123}, {"unit": "m2", "value": 4321.5}],
    ),
    _object("door|abc|900x2100", "door", "Дверь 900 x 2100 мм", [{"unit": "pcs", "value": 1234.0}]),
    _object(
        "masonry|120|brick_solid|lintel",
        "construction",
        "Кладка: перемычки над проёмами, 120 мм",
        [{"unit": "pcs", "value": 31.0}],
    ),
]


def _item(name: str, unit: str | None, **fields: Any) -> CadVorItem:
    return CadVorItem(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        row_no=fields.pop("row_no", 1),
        sheet="ВОР",
        code=fields.pop("code", None),
        name=name,
        unit=unit,
        quantity=fields.pop("quantity", 987654),
        section=fields.pop("section", "Раздел"),
        name_norm=name.lower(),
        thickness_hint_mm=None,
        kind_hint=fields.pop("kind_hint", None),
    )


# ------------------------------------------------------------------ пакет без количеств


def test_package_item_is_a_whitelist_without_quantity() -> None:
    row = _item("Кладка стен 190 мм", "м3", quantity=987654)
    packed = ai_vor_map.package_item(row)
    assert set(packed) == {"id", "row", "sheet", "code", "name", "unit", "section"}
    assert packed["id"] == str(row.id) and "987654" not in json.dumps(packed)


def test_package_object_has_unit_names_without_values() -> None:
    packed = [ai_vor_map.package_object(obj) for obj in OBJECTS]
    assert all(
        set(row) == {"group_key", "kind", "description", "units", "sources"} for row in packed
    )
    assert packed[0]["units"] == ["м³", "м²"] and packed[0]["kind"] == "конструкция"
    assert packed[1]["kind"] == "дверь" and packed[2]["kind"] == "перемычка"
    assert packed[0]["sources"] == ["План 1"]
    dump = json.dumps(packed, ensure_ascii=False)
    for number in ("777.123", "4321.5", "1234.0", "31.0"):
        assert number not in dump


def test_relevance_needs_known_unit_and_section_words() -> None:
    assert ai_vor_map.is_relevant(_item("Кладка перегородок", "м2"))
    assert ai_vor_map.is_relevant(_item("Дверь входная", "шт"))
    assert ai_vor_map.is_relevant(_item("Окраска потолка", "м²"))
    assert ai_vor_map.is_relevant(_item("Прочее", "м2", kind_hint="masonry"))
    assert not ai_vor_map.is_relevant(_item("Кладка перегородок", "т"))
    assert not ai_vor_map.is_relevant(_item("Кладка перегородок", None))
    assert not ai_vor_map.is_relevant(_item("Кабель ВВГ", "м"))


# ------------------------------------------------------------------ отчёт


def _report(**fields: Any) -> dict[str, Any]:
    return {"matches": [], "unmatched_objects": [], "limitations": [], **fields}


def test_report_schema_rejects_numbers_and_limits() -> None:
    match = {"vor_item_id": "a", "group_keys": ["k"], "confidence": "high", "rationale": "ок"}
    AiVorMapReport.model_validate(_report(matches=[match]))
    with pytest.raises(ValidationError):
        AiVorMapReport.model_validate(_report(matches=[{**match, "quantity": 5}]))
    with pytest.raises(ValidationError):
        AiVorMapReport.model_validate(_report(matches=[{**match, "confidence": "sure"}]))
    with pytest.raises(ValidationError):
        AiVorMapReport.model_validate(_report(matches=[{**match, "group_keys": ["k"] * 51}]))
    with pytest.raises(ValidationError):
        AiVorMapReport.model_validate(_report(limitations=["x"] * 13))


def test_sanitize_drops_foreign_ids_and_keys_without_failing() -> None:
    item_id = str(uuid.uuid4())
    report = AiVorMapReport.model_validate(
        _report(
            matches=[
                {
                    "vor_item_id": item_id,
                    "group_keys": ["a", "чужой", "a"],
                    "confidence": "high",
                    "rationale": "толщина",
                },
                {
                    "vor_item_id": str(uuid.uuid4()),
                    "group_keys": ["a"],
                    "confidence": "low",
                    "rationale": "чужая позиция",
                },
                {
                    "vor_item_id": item_id,
                    "group_keys": ["b"],
                    "confidence": "medium",
                    "rationale": "повтор позиции",
                },
                {
                    "vor_item_id": item_id,
                    "group_keys": ["чужой"],
                    "confidence": "low",
                    "rationale": "только чужое",
                },
            ],
            unmatched_objects=[
                {"group_key": "b", "reason": "нет в ВОР"},
                {"group_key": "чужой", "reason": "?"},
            ],
            limitations=["лимит"],
        )
    )
    clean, dropped = ai_vor_map.sanitize_report(report, {item_id}, {"a", "b"})
    assert [(m.vor_item_id, m.group_keys) for m in clean.matches] == [(item_id, ["a", "b"])]
    assert clean.matches[0].confidence == "high"
    assert [row.group_key for row in clean.unmatched_objects] == ["b"]
    assert clean.limitations == ["лимит"]
    assert len(dropped) == 4 and all(isinstance(row, str) for row in dropped)


# ------------------------------------------------------------------ роль промта, REMOTE


def test_vor_mapper_is_a_prompt_role_but_not_a_review_role() -> None:
    body = AiPromptCreate(role="vor_mapper", text="Промт")
    assert body.role == "vor_mapper"
    with pytest.raises(ValidationError):
        AiPromptCreate.model_validate({"role": "other", "text": "Промт"})
    from app.contracts.cad_ai_review import AiReviewStart

    with pytest.raises(ValidationError):
        AiReviewStart.model_validate({"role": "vor_mapper"})


async def test_vor_mapper_active_version_is_unique(db_session: AsyncSession) -> None:
    db_session.add(AiPromptVersion(role="vor_mapper", version=1, text="T", status="active"))
    await db_session.commit()
    from sqlalchemy.exc import IntegrityError

    db_session.add(AiPromptVersion(role="vor_mapper", version=2, text="T", status="active"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


def test_remote_is_a_closed_package_reader() -> None:
    assert set(PACKAGE_FILES) == {
        "manifest.json",
        "vor_items.json",
        "objects.json",
        "prompt.txt",
        "schema.json",
    }
    for name in PACKAGE_FILES:
        assert name in REMOTE
    assert "raw_sources" not in REMOTE and "--allowed-tools" in REMOTE
    assert remote_command(900).endswith(" 900")


# ------------------------------------------------------------------ _prepare и исполнитель


async def _document(api: AsyncClient, db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    project_id = await _project(api)
    assert (await _upload(api, project_id)).status_code == 201
    document = (await db_session.scalars(select(CadVorDocument))).all()[-1]
    return uuid.UUID(project_id), document.id


def _read_package(root: Path) -> dict[str, Any]:
    return {
        "names": {path.name for path in root.iterdir()},
        "prompt": (root / "prompt.txt").read_bytes(),
        "items": json.loads((root / "vor_items.json").read_bytes()),
        "objects": json.loads((root / "objects.json").read_bytes()),
        "schema": json.loads((root / "schema.json").read_bytes()),
        "text": " ".join(
            (root / name).read_text(encoding="utf-8")
            for name in ("vor_items.json", "objects.json", "manifest.json")
        ),
    }


async def test_prepare_writes_package_without_quantities(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id, document_id = await _document(api, db_session)
    db_session.add(
        AiPromptVersion(role="vor_mapper", version=1, text="Промт ВОР\n", status="active")
    )
    await db_session.commit()
    chosen = await ai_vor_map.select_items(db_session, document_id)
    # «Окна ПВХ» не конструктив, дверь и отделка: в выборке только строки с общими словами.
    assert chosen and all("Окна" not in row.name for row in chosen)
    objects = [ai_vor_map.package_object(obj) for obj in OBJECTS]
    job = Job(
        id=uuid.uuid4(),
        project_id=project_id,
        payload={
            "document_id": str(document_id),
            "item_ids": [str(row.id) for row in chosen],
            "objects": objects,
            "model": "claude-opus-5-5",
        },
    )
    manifest = await ai_vor_map._prepare(db_session, job, tmp_path)
    package = _read_package(tmp_path)
    assert package["prompt"] == "Промт ВОР\n".encode()
    assert package["names"] == set(PACKAGE_FILES)
    assert len(package["items"]) == len(chosen)
    assert all("quantity" not in row for row in package["items"])
    for number in ("120,5", "120.5", "300", "15.5"):
        assert f'"{number}"' not in package["text"] and f": {number}" not in package["text"]
    assert package["objects"] == objects
    assert manifest["prompt_version"] == 1 and job.payload["prompt_version"] == 1
    assert "matches" in package["schema"]["properties"]
    assert "quantity" not in json.dumps(package["schema"])


async def test_prepare_fails_without_active_prompt(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    from app.cad_worker.handler import CadError

    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id, document_id = await _document(api, db_session)
    chosen = await ai_vor_map.select_items(db_session, document_id)
    job = Job(
        id=uuid.uuid4(),
        project_id=project_id,
        payload={
            "document_id": str(document_id),
            "item_ids": [str(row.id) for row in chosen],
            "objects": [],
            "model": "claude-opus-5-5",
        },
    )
    with pytest.raises(CadError):
        await ai_vor_map._prepare(db_session, job, tmp_path)


async def _run_execute(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any], exit_code: int = 0
) -> tuple[AsyncMock, AsyncMock]:
    item_id = str(uuid.uuid4())
    job = Job(
        id=uuid.uuid4(),
        status=JobStatus.RUNNING,
        job_type=JobType.CAD_AI_VOR_MAP,
        worker_id="w",
        attempt=1,
        payload={
            "item_ids": [item_id],
            "objects": [{"group_key": "a", "description": "A"}],
        },
    )
    response = json.loads(json.dumps(response).replace("ITEM", item_id))
    manifest = {
        "document_id": str(uuid.uuid4()),
        "model": "claude-opus-5-5",
        "items_count": 1,
        "objects_count": 1,
        "prompt_version_id": str(uuid.uuid4()),
        "prompt_version": 1,
    }

    async def prepare(*args: Any) -> dict[str, Any]:
        return manifest

    async def run(session: Any, job_: Job, owner: Any, attempt: Any, command: list[str], **kw: Any):
        (Path(command[3]) / "vor_map.json").write_text(json.dumps(response), encoding="utf-8")
        return exit_code, ""

    monkeypatch.setattr(ai_vor_map, "_prepare", prepare)
    monkeypatch.setattr(ai_vor_map, "_run_while_owned", run)
    monkeypatch.setattr(ai_vor_map, "_still_owned", AsyncMock(return_value=True))
    monkeypatch.setattr(jobs, "start", AsyncMock())
    succeed = AsyncMock(side_effect=lambda session, job, payload: job)
    monkeypatch.setattr(jobs, "succeed", succeed)
    fail = AsyncMock(side_effect=lambda session, job, **kw: job)
    monkeypatch.setattr(jobs, "fail", fail)
    settings = Settings(cad_review_ssh_config="/ssh/config", cad_engine_python="/engine/python")
    await execute_ai_vor_map(AsyncMock(), job, AsyncMock(), settings)
    return succeed, fail


def _response(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "report": report,
        "usage": {"cost_usd": 0.4, "duration_ms": 900, "input_tokens": 10, "output_tokens": 5},
        "model": "claude-opus-5-5",
        "prompt_sha256": "b" * 64,
        "bundle_sha256": "c" * 64,
    }


async def test_execute_stores_sanitized_report(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _report(
        matches=[
            {
                "vor_item_id": "ITEM",
                "group_keys": ["a", "x"],
                "confidence": "high",
                "rationale": "r",
            }
        ]
    )
    succeed, fail = await _run_execute(monkeypatch, _response(report))
    fail.assert_not_awaited()
    stored = succeed.call_args.kwargs["payload"]["ai_vor_map"]
    assert stored["report"]["matches"][0]["group_keys"] == ["a"]
    assert stored["dropped"] == ["Отброшено ключей объектов вне пакета: 1"]
    assert stored["usage"]["cost_usd"] == 0.4 and stored["prompt_sha256"] == "b" * 64


@pytest.mark.parametrize("code", [124, 255, 3])
async def test_execute_maps_exit_codes_to_failure(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    succeed, fail = await _run_execute(monkeypatch, _response(_report()), code)
    succeed.assert_not_awaited()
    assert fail.call_args.kwargs["error_code"]


async def test_execute_rejects_report_with_extra_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = _report(
        matches=[
            {
                "vor_item_id": "ITEM",
                "group_keys": ["a"],
                "confidence": "high",
                "rationale": "r",
                "quantity": 5,
            }
        ]
    )
    succeed, fail = await _run_execute(monkeypatch, _response(bad))
    succeed.assert_not_awaited()
    fail.assert_awaited_once()


# ------------------------------------------------------------------ пилот и API


def _pilot(project_id: uuid.UUID) -> AiLoopPilot:
    return AiLoopPilot(project_id=project_id, sources={"vor": "/pilot/vor.md"})


def test_pilot_for_project_matches_only_its_project() -> None:
    project = uuid.uuid4()
    settings = Settings(cad_ai_loop=_pilot(project).model_dump_json())
    assert ai_vor_map.pilot_for_project(project, settings) is not None
    assert ai_vor_map.pilot_for_project(uuid.uuid4(), settings) is None
    assert ai_vor_map.pilot_for_project(project, Settings(cad_ai_loop="")) is None
    assert ai_vor_map.pilot_for_project(project, Settings(cad_ai_loop="{")) is None


async def test_api_is_closed_without_flag_and_without_pilot(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=vor_settings(flag=False)) as api:
        url = f"/api/v1/projects/{uuid.uuid4()}/vor/ai-map"
        assert (await api.post(url)).status_code == 403
        assert (await api.get(url)).status_code == 403
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        url = f"/api/v1/projects/{project_id}/vor/ai-map"
        started = await api.post(url)
        assert started.status_code == 409, started.text
        assert started.json()["detail"]["code"] == "CAD_RESULT_NOT_READY"
        state = (await api.get(url)).json()
        assert state["available"] is False and state["job_id"] is None
        assert (await api.post(f"/api/v1/projects/{uuid.uuid4()}/vor/ai-map")).status_code == 404


async def test_api_start_status_suggestions_and_linked_flag(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def objects(*args: Any) -> list[VorObjectRead]:
        return OBJECTS

    monkeypatch.setattr(cad_vor_fill, "_project_objects", objects)
    pilot = AiLoopPilot(project_id=uuid.uuid4(), sources={"vor": "/pilot/vor.md"})
    monkeypatch.setattr(ai_vor_map, "pilot_for_project", lambda project_id, settings: pilot)
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        url = f"/api/v1/projects/{project_id}/vor/ai-map"
        # ВОР не загружен: запускать нечего.
        assert (await api.post(url)).status_code == 409
        document = (await _upload(api, project_id)).json()
        started = await api.post(url)
        assert started.status_code == 202, started.text
        body = started.json()
        assert body["available"] is True and body["status"] == "queued"
        again = await api.post(url)
        assert again.json()["job_id"] == body["job_id"]

        job = await db_session.get(Job, uuid.UUID(body["job_id"]))
        assert job is not None and job.job_type is JobType.CAD_AI_VOR_MAP
        assert job.payload["document_id"] == document["id"] and job.payload["item_ids"]
        assert "quantity" not in json.dumps(job.payload) and "value" not in json.dumps(
            job.payload["objects"]
        )
        item_id = job.payload["item_ids"][0]
        key = OBJECTS[0].group_key
        job.status = JobStatus.SUCCEEDED
        job.payload = {
            **job.payload,
            "ai_vor_map": {
                "document_id": document["id"],
                "model": "claude-opus-5-5",
                "prompt_version_id": None,
                "prompt_version": 1,
                "prompt_sha256": "b" * 64,
                "bundle_sha256": "c" * 64,
                "items_count": 1,
                "objects_count": 3,
                "usage": {},
                "report": _report(
                    matches=[
                        {
                            "vor_item_id": item_id,
                            "group_keys": [key],
                            "confidence": "high",
                            "rationale": "газобетон, толщина",
                        }
                    ],
                    unmatched_objects=[{"group_key": OBJECTS[1].group_key, "reason": "нет в ВОР"}],
                    limitations=["мало данных"],
                ),
                "dropped": ["Отброшено ключей объектов вне пакета: 1"],
            },
        }
        await db_session.commit()

        state = (await api.get(url)).json()
        assert state["status"] == "succeeded" and state["stale"] is False
        assert state["prompt_version"] == 1 and state["model"] == "claude-opus-5-5"
        [suggestion] = state["suggestions"]
        assert suggestion["item"]["id"] == item_id and suggestion["confidence"] == "high"
        assert suggestion["objects"] == [
            {"group_key": key, "kind": "construction", "title": OBJECTS[0].title, "linked": False}
        ]
        assert state["unmatched"][0]["object"]["kind"] == "door"
        assert state["limitations"] == ["мало данных", "Отброшено ключей объектов вне пакета: 1"]

        # Принятие - существующим запросом связи; предложение после этого помечено связанным.
        link = await api.put(
            f"/api/v1/projects/{project_id}/cad/vor/links/{key.replace('|', '%7C')}",
            json={"vor_item_ids": [item_id]},
        )
        assert link.status_code == 200, link.text
        linked = (await api.get(url)).json()
        assert linked["suggestions"][0]["objects"][0]["linked"] is True

        # Новый документ ВОР: предложения устарели и не показываются.
        await _upload(api, project_id, ROWS)
        stale = (await api.get(url)).json()
        assert stale["stale"] is True and stale["suggestions"] == []
