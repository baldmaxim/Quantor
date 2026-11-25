"""Пороги качества CAD (ревью движка 2026-11-16) на синтетике.

Конструкции «на проверку», сверка авто-зон с экспликацией и их происхождение, пересоздание
авто-зон и массовое удаление, перепостановка задания при смене пина, метка «устарел по версии».
Движок не нужен: родитель `cad_pdf_convert` выставляется в базе и хранилище, скрипты генераторов
подменены заглушками по CLI-контракту.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import WallsDocument
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.models import CadZone, Job
from app.services import cad as cad_service
from app.services import (
    cad_pins,
    cad_pipeline,
    cad_quality,
    cad_summary,
    cad_zones_auto,
    cad_zones_review,
)
from app.services import cad_walls as cad_walls_service
from tests.cad_pins_helper import write_pins
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import PARAMS as WALLS_PARAMS
from tests.test_cad_constructions_api import STUB as WALLS_STUB
from tests.test_cad_constructions_api import _run_walls_worker
from tests.test_cad_finishes import _body as _template_body
from tests.test_cad_finishes import _templates_url
from tests.test_cad_mep import PARAMS as MEP_PARAMS
from tests.test_cad_mep import _parent
from tests.test_cad_zones import _room
from tests.test_cad_zones_auto import _run_zones_worker, _zones_url

# Заглушка CLI зон: семь помещений с разным итогом сверки и одна марка без зоны.
ZONES_STUB = """
import argparse, json, pathlib

parser = argparse.ArgumentParser()
for name in ("pdf", "page-index", "view-dxf", "scale", "preview", "params", "out"):
    parser.add_argument("--" + name)
args = parser.parse_args()


def rect(col, row):
    x, y = 0.05 + col * 0.1, 0.05 + row * 0.1
    return [[x, y], [x + 0.08, y], [x + 0.08, y + 0.08], [x, y + 0.08]]


def room(mark, name, expl, poly, points, apartment="0042", kind="room_apartment", notes=()):
    return {"kind": kind, "apartment_no": apartment, "room_mark": mark, "name": name,
            "expl_area_m2": expl, "poly_area_m2": poly, "points": points, "notes": list(notes)}


twin = rect(5, 0)
zones = [
    room("3-1/1", "Спальня", 12.5, 12.4, rect(0, 0)),
    room("3-1/2", "Кухня", 10.0, 11.5, rect(1, 0), notes=["площадь отличается на +15,0 %"]),
    room("3-1/3", "Санузел", 4.0, 3.5, rect(2, 0)),
    room("3-2/2", "Гостиная", 1.6, 16.5, rect(3, 0)),
    room("6-5/1+6-6/6", "Кухня | Спальня", 20.0, 20.0, rect(4, 0)),
    room("15-1/2", "Прихожая", 5.0, 5.0, twin),
    room("15-3.1", "Коридор", 5.0, 5.0, twin, apartment=None, kind="room_mop"),
    room("3-1/9", "Гардероб", None, 2.0, rect(6, 0)),
]
doc = {"schema": "quantor.cad_mep.zones.v1", "generator_version": "cad_mep.v1",
       "page_index": int(args.page_index), "scale_mm_per_pt": 35.0, "zones": zones,
       "unmatched_marks": [
           {"room_mark": "3-3.4", "name": "Лестничная клетка", "expl_area_m2": 15.1,
            "reason": "полигон не построен"},
           {"name": "без марки"}, "мусор"],
       "summary": []}
mode = pathlib.Path(__file__).with_name("mode")
if mode.exists() and mode.read_text().strip() == "empty":
    doc["zones"] = []
out = pathlib.Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
"""

EXPECTED = {
    "3-1/1": "ok",
    "3-1/2": "review",
    "3-1/3": "ok",
    "3-2/2": "failed",
    "6-5/1+6-6/6": "failed",
    "15-1/2": "failed",
    "15-3.1": "failed",
    "3-1/9": "ok",
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    walls = tmp_path / "tools" / "cad_walls"
    (walls / "params").mkdir(parents=True)
    (walls / "cad_walls").mkdir()
    (walls / "params" / "v1.json").write_text(json.dumps(WALLS_PARAMS), encoding="utf-8")
    (walls / "run_walls.py").write_text(WALLS_STUB, encoding="utf-8")
    mep = tmp_path / "tools" / "cad_mep"
    (mep / "params").mkdir(parents=True)
    (mep / "cad_mep").mkdir()
    (mep / "params" / "v1.json").write_text(json.dumps(MEP_PARAMS), encoding="utf-8")
    (mep / "run_mep.py").write_text("", encoding="utf-8")
    (mep / "run_zones.py").write_text(ZONES_STUB, encoding="utf-8")
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true",
        cad_engine_python=sys.executable,
        cad_walls_runner=str(walls / "run_walls.py"),
        cad_walls_params=str(walls / "params" / "v1.json"),
        cad_mep_runner=str(mep / "run_mep.py"),
        cad_mep_params=str(mep / "params" / "v1.json"),
        cad_engine_pins=write_pins(
            tmp_path, mep=mep / "params" / "v1.json", walls=walls / "params" / "v1.json"
        ),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


def _stub_mode(settings: Settings, mode: str) -> None:
    """Режим заглушки CLI зон: файл `mode` рядом со скриптом."""
    Path(settings.cad_mep_runner).with_name("mode").write_text(mode, encoding="utf-8")


def _zones_list_url(project_id: str, revision_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/zones?revision_id={revision_id}"


async def _auto_zones(
    api: AsyncClient,
    session: AsyncSession,
    storage: FakeObjectStorage,
    settings: Settings,
    project_id: str,
    job_id: str,
) -> Job:
    queued = await api.post(_zones_url(project_id, job_id))
    assert queued.status_code == 202, queued.text
    job = await _run_zones_worker(session, storage, settings, queued.json()["job_id"])
    assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
    return job


# ------------------------------------------------------------------ конструкции: чистые функции


def _walls(**patch: Any) -> WallsDocument:
    def cons(key: str, status: str, side: float) -> dict[str, Any]:
        return {
            "id": key,
            "kind": "masonry",
            "source_layers": [],
            "polygon": {"shell": [[0, 0], [side, 0], [side, 100], [0, 100]], "holes": []},
            "area_plan_mm2": side * 100,
            "thickness_measured_mm": 100.0,
            "thickness_nominal_mm": 100.0 if status == "matched" else None,
            "thickness_status": status,
            "length_axis_mm": side,
            "centroid": [0, 0],
            "bbox": [0, 0, side, 100],
        }

    def door(key: str, status: str) -> dict[str, Any]:
        return {
            "id": key,
            "kind": "door",
            "status": status,
            "host_id": None,
            "adjacent_ids": [],
            "width_mm": 900.0,
            "width_source": "block",
            "thickness_mm": None,
            "block_name": None,
            "handle": None,
            "center": [0, 0],
        }

    doc: dict[str, Any] = {
        "schema": "quantor.cad_walls.v1",
        "generator": "cad_walls.v1",
        "params_version": "v1",
        "params_sha256": "0" * 64,
        "dxf_sha256": "1" * 64,
        "units": "mm",
        "heights": {
            "floor_elevation_mm": 0,
            "floor_height_mm": 3300,
            "elevation_status": "observed",
            "height_status": "derived",
            "evidence": None,
            "message": None,
            "slab_thickness_mm": 200,
            "slab_status": "assumption",
            "door_height_mm": 2100,
            "door_height_status": "assumption",
        },
        # 96 % площади с номиналом, 4 % - без: ниже порога 5 %.
        "constructions": [cons("a", "matched", 9600.0), cons("b", "check", 400.0)],
        "openings": [door(f"d{i}", "ok") for i in range(9)] + [door("d9", "no_data")],
        "checks": {"warnings": []},
        "slab": {"id": "slab", "basis": "zones", "shell": [], "area_mm2": 1.0},
    }
    doc.update(patch)
    doc["heights"].update(patch.get("heights_patch", {}))
    doc.pop("heights_patch", None)
    for index, status in enumerate(patch.get("door_statuses", [])):
        doc["openings"][index]["status"] = status
    doc.pop("door_statuses", None)
    return WallsDocument.model_validate(doc)


def _codes(document: WallsDocument) -> list[str]:
    return [reason.code for reason in cad_quality.walls_reasons(document)]


def test_clean_walls_result_has_no_reasons() -> None:
    # 4 % площади без номинала и 1 дверь из 10 без разрыва - ровно на пороге, замечаний нет.
    assert cad_quality.walls_quality(_walls()) == {"status": "ok", "reasons": []}


def test_walls_reasons_cover_each_threshold() -> None:
    assert _codes(_walls(constructions=[])) == ["no_constructions"]
    assert _codes(_walls(heights_patch={"floor_height_mm": None})) == ["floor_height_missing"]
    assert _codes(_walls(slab={"basis": "walls_only"})) == ["slab_walls_only"]
    assert _codes(_walls(slab=None)) == []
    assert _codes(_walls(door_statuses=["no_data"])) == ["doors_without_gap"]

    wide = _walls()
    wide.constructions[1].area_plan_mm2 = 60000.0
    assert _codes(wide) == ["thickness_check_share"]

    empty = _walls(constructions=[], slab={"basis": "walls_only"})
    assert cad_quality.walls_quality(empty)["status"] == "review"
    assert [reason.text for reason in cad_quality.walls_reasons(empty)] == [
        "на плане нет конструкций",
        "плита построена только по стенам, без зон помещений",
    ]


def test_check_construction_with_section_mm_is_not_counted_as_unsure_thickness() -> None:
    # cad_walls v1.17: монолит без номинала с габаритом сечения считается по площади.
    with_section = _walls()
    with_section.constructions[1].kind = "monolith_column"
    with_section.constructions[1].area_plan_mm2 = 60000.0
    assert with_section.constructions[1].thickness_status == "check"
    without_section = with_section.model_copy(deep=True)
    with_section.constructions[1].section_mm = [100.0, 600.0]
    assert _codes(with_section) == []
    assert cad_quality.walls_quality(with_section) == {"status": "ok", "reasons": []}
    assert _codes(without_section) == ["thickness_check_share"]


def test_only_check_constructions_without_section_mm_make_up_the_unsure_share() -> None:
    # Две «проверочные» на 60000 мм2 каждая: с габаритом сечения - вне доли, без него - внутри.
    document = _walls()
    for item in document.constructions:
        item.thickness_status = "check"
        item.thickness_nominal_mm = None
    document.constructions[0].area_plan_mm2 = 60000.0
    document.constructions[1].area_plan_mm2 = 60000.0
    assert _codes(document) == ["thickness_check_share"]
    document.constructions[0].section_mm = [100.0, 600.0]
    # 60000 из 120000 = 50 % - остаётся вторая конструкция без габарита.
    (reason,) = cad_quality.walls_reasons(document)
    assert reason.code == "thickness_check_share" and "50,0 %" in reason.text
    document.constructions[1].section_mm = [100.0, 600.0]
    assert _codes(document) == []


def test_walls_quality_is_read_from_the_job_result() -> None:
    block = cad_quality.walls_quality(_walls(constructions=[]))
    assert cad_quality.walls_result_quality({"result_status": "walls_ready", "quality": block}) == (
        "review",
        ["на плане нет конструкций"],
    )
    ok = {"result_status": "walls_ready", "quality": {"status": "ok", "reasons": []}}
    assert cad_quality.walls_result_quality(ok) == ("ok", [])
    # Итог до появления порога: по счётчику видно только пустой лист.
    old_empty = {"result_status": "walls_ready", "counts": {"constructions": 0}}
    assert cad_quality.walls_result_quality(old_empty) == ("review", ["на плане нет конструкций"])
    old = {"result_status": "walls_ready", "counts": {"constructions": 12}}
    assert cad_quality.walls_result_quality(old) == (None, [])
    assert cad_quality.walls_result_quality({}) == (None, [])


# ------------------------------------------------------------------ зоны: чистые функции


def _zone_status(area: float | None, expl: float | None, **patch: Any) -> str:
    params: dict[str, Any] = {
        "kind": "room_apartment",
        "name": "Спальня",
        "room_mark": "3-1/1",
        "area_m2": area,
        "expl_area_m2": expl,
    }
    params.update(patch)
    return cad_quality.zone_quality(**params).status


def test_zone_quality_applies_tolerances_by_room_kind() -> None:
    assert _zone_status(11.0, 10.0) == "ok"
    assert _zone_status(11.1, 10.0) == "review"
    assert _zone_status(8.9, 10.0) == "review"
    # Санузел и МОП - допуск 15 %.
    assert _zone_status(8.6, 10.0, name="Санузел") == "ok"
    assert _zone_status(8.4, 10.0, name="Санузел") == "review"
    assert _zone_status(11.4, 10.0, kind="room_mop", name="Коридор") == "ok"
    assert _zone_status(11.6, 10.0, kind="room_mop", name="Коридор") == "review"
    # Больше 1,5 или меньше 0,5 экспликации - отклонена.
    assert _zone_status(15.1, 10.0) == "failed"
    assert _zone_status(4.9, 10.0) == "failed"
    assert _zone_status(15.0, 10.0) == "review"


def test_zone_quality_without_data_and_structural_failures() -> None:
    no_expl = cad_quality.zone_quality(
        kind="room_apartment", name="Спальня", room_mark="3-1/1", area_m2=12.0, expl_area_m2=None
    )
    assert (no_expl.status, no_expl.reason) == ("ok", "нет данных экспликации")
    assert _zone_status(None, 10.0) == "review"
    assert _zone_status(10.0, 10.0, room_mark="6-5/1+6-6/6") == "failed"
    # Марки одной квартиры в слитой зоне - не отказ.
    assert _zone_status(10.0, 10.0, room_mark="6-5/1+6-5/7") == "ok"
    assert _zone_status(10.0, 10.0, has_twin=True, twin_mark="15-3.1") == "failed"

    square = [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]]
    rotated = [*square[2:], *square[:2]]
    other = [[0.5, 0.5], [0.6, 0.5], [0.6, 0.6]]
    assert cad_quality.duplicate_polygons([square, other, rotated]) == {0: 2, 2: 0}


# ------------------------------------------------------------------ зоны: обработчик и API


async def test_auto_zones_get_origin_and_quality_and_failed_stay_out_of_the_slab(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        job = await _auto_zones(api, db_session, fake_storage, settings, project_id, job_id)

        result = cad_service.result_of(job)
        assert result["counts"] == {"in_file": 8, "created": 8, "rejected": 0}
        assert result["quality"] == {"ok": 3, "review": 1, "failed": 4}
        assert [mark["room_mark"] for mark in result["unmatched_marks"]] == ["3-3.4"]

        zones = {
            z["room_mark"]: z
            for z in (await api.get(_zones_list_url(project_id, revision_id))).json()
        }
        assert {mark: zone["quality_status"] for mark, zone in zones.items()} == EXPECTED
        assert all(
            (zone["source"], zone["generator_version"]) == ("auto", "cad_mep.v1")
            for zone in zones.values()
        )
        assert zones["3-1/2"]["expl_area_m2"] == 10.0
        assert zones["3-1/2"]["notes"] == ["площадь отличается на +15,0 %"]
        assert "допуск ±10 %" in zones["3-1/2"]["quality_reason"]
        assert "больше экспликации в 1,5 раза" in zones["3-2/2"]["quality_reason"]
        assert "разных квартир: 6-5, 6-6" in zones["6-5/1+6-6/6"]["quality_reason"]
        assert "одинаковый контур" in zones["15-1/2"]["quality_reason"]
        assert zones["3-1/9"]["quality_reason"] == "нет данных экспликации"

        # Плита и перегородки: в пересчёт конструкций ушли только зоны, не отклонённые сверкой.
        walls_jobs = list(
            await db_session.scalars(select(Job).where(Job.job_type == JobType.CAD_WALLS))
        )
        assert [w.payload["zones_count"] for w in walls_jobs] == [4]
        rows = list(await db_session.scalars(select(CadZone)))
        assert len(cad_zones_review.usable(rows)) == 4

        summary = (
            await api.get(
                f"/api/v1/projects/{project_id}/cad/zones/summary"
                f"?revision_id={revision_id}&page_index=0"
            )
        ).json()
        assert (summary["ok"], summary["review"], summary["failed"]) == (3, 1, 4)
        assert (summary["auto"], summary["human"], summary["unknown"]) == (8, 0, 0)
        assert summary["generator_versions"] == ["cad_mep.v1"]
        assert summary["apartments_compared"] == 6
        assert summary["apartments_area_m2"] == 68.9
        assert summary["apartments_expl_area_m2"] == 53.1
        assert summary["apartments_delta_percent"] == 29.8
        assert summary["unmatched_marks"] == [
            {
                "room_mark": "3-3.4",
                "name": "Лестничная клетка",
                "expl_area_m2": 15.1,
                "reason": "полигон не построен",
            }
        ]
        assert summary["recreate_allowed"] is True


async def test_accept_and_edit_make_the_zone_human_and_block_recreation(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        await _auto_zones(api, db_session, fake_storage, settings, project_id, job_id)
        zones = {
            z["room_mark"]: z
            for z in (await api.get(_zones_list_url(project_id, revision_id))).json()
        }

        accepted = await api.post(f"/api/v1/cad/zones/{zones['3-2/2']['id']}/accept")
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert (body["quality_status"], body["source"]) == ("ok", "human")
        assert body["quality_accepted_by"] is not None and body["quality_accepted_at"] is not None
        # Причина расхождения остаётся следом принятого решения.
        assert "больше экспликации" in body["quality_reason"]
        rows = list(await db_session.scalars(select(CadZone)))
        assert len(cad_zones_review.usable(rows)) == 5

        edited = await api.patch(
            f"/api/v1/cad/zones/{zones['3-1/2']['id']}", json={"name": "Кухня-ниша"}
        )
        assert edited.status_code == 200, edited.text
        assert (edited.json()["source"], edited.json()["quality_status"]) == ("human", "ok")
        assert edited.json()["quality_reason"] is None

        # Отделка считается без зон, отклонённых сверкой; принятая зона в неё вернулась.
        finishes = (
            await api.get(
                f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/finishes?page_index=0"
            )
        ).json()
        in_finishes = {row["room_mark"] for row in finishes["zones"]}
        assert "3-2/2" in in_finishes and "6-5/1+6-6/6" not in in_finishes
        assert len(in_finishes) == 5

        # Назначение шаблона отделки человеком делает зону его разметкой, итог сверки не меняется.
        template = (await api.post(_templates_url(project_id), json=_template_body())).json()
        assigned = await api.post(
            f"/api/v1/projects/{project_id}/cad/zones/finish-assign",
            json={"zone_ids": [zones["3-1/1"]["id"]], "template_id": template["id"]},
        )
        assert assigned.status_code == 200 and assigned.json()["assigned"] == 1
        listed = (await api.get(_zones_list_url(project_id, revision_id))).json()
        by_mark = {z["room_mark"]: z for z in listed}
        assert (by_mark["3-1/1"]["source"], by_mark["3-1/1"]["quality_status"]) == ("human", "ok")
        assert by_mark["3-1/3"]["source"] == "auto"

        # На листе есть зоны человека: авторазметка их не заменяет.
        again = await api.post(_zones_url(project_id, job_id))
        assert again.status_code == 409
        detail = again.json()["detail"]
        assert detail["code"] == "CAD_ZONES_NOT_EMPTY" and "Удалите зоны листа" in detail["message"]

        missing = await api.post(f"/api/v1/cad/zones/{uuid.uuid4()}/accept")
        assert missing.status_code == 404


async def test_manual_start_recreates_a_sheet_of_auto_zones_in_one_transaction(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        await _auto_zones(api, db_session, fake_storage, settings, project_id, job_id)
        before = {z["id"] for z in (await api.get(_zones_list_url(project_id, revision_id))).json()}
        assert len(before) == 8

        second = await _auto_zones(api, db_session, fake_storage, settings, project_id, job_id)
        result = cad_service.result_of(second)
        assert second.payload["recreate_auto"] is True
        assert result["result_status"] == "zones_ready" and result["replaced"] == 8
        after = {z["id"] for z in (await api.get(_zones_list_url(project_id, revision_id))).json()}
        assert len(after) == 8 and not (after & before)

        # Новая разметка не дала ни одной зоны: прежние авто-зоны листа остаются на месте.
        _stub_mode(settings, "empty")
        third = await _auto_zones(api, db_session, fake_storage, settings, project_id, job_id)
        assert cad_service.result_of(third)["result_status"] == "zones_skipped_existing"
        assert cad_service.result_of(third)["replaced"] == 0
        kept = {z["id"] for z in (await api.get(_zones_list_url(project_id, revision_id))).json()}
        assert kept == after

        # Автопостановка после конвертации лист с зонами по-прежнему не трогает, а задание без
        # признака ручного пересоздания зоны не заменяет.
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        assert await cad_zones_auto.enqueue_after_convert(db_session, parent, settings) == []


async def test_bulk_delete_removes_auto_or_all_zones_of_the_sheet(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        await _auto_zones(api, db_session, fake_storage, settings, project_id, job_id)
        created = await api.post(
            f"/api/v1/projects/{project_id}/cad/zones",
            json=_room(
                revision_id, room_mark="ручная", points=[[0.7, 0.7], [0.8, 0.7], [0.8, 0.8]]
            ),
        )
        assert created.status_code == 201 and created.json()["source"] == "human"
        url = f"/api/v1/projects/{project_id}/cad/zones?revision_id={revision_id}&page_index=0"

        assert (await api.delete(url)).status_code == 422  # scope обязателен
        only_auto = await api.delete(f"{url}&scope=auto")
        assert only_auto.status_code == 200 and only_auto.json() == {"deleted": 8}
        left = (await api.get(_zones_list_url(project_id, revision_id))).json()
        assert [zone["room_mark"] for zone in left] == ["ручная"]

        everything = await api.delete(f"{url}&scope=all")
        assert everything.json() == {"deleted": 1}
        assert (await api.get(_zones_list_url(project_id, revision_id))).json() == []
        assert (await api.delete(f"{url}&scope=all")).json() == {"deleted": 0}

    off = settings.model_copy(update={"feature_flags": ""})
    async with build_api(make_context(), settings=off) as closed:
        assert (await closed.delete(f"{url}&scope=all")).status_code == 403
        summary = url.replace("/cad/zones?", "/cad/zones/summary?")
        assert (await closed.get(summary)).status_code == 403


# ------------------------------------------------------------------ смена пина


async def test_zones_job_queued_before_pin_change_is_requeued_once(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, _revision, job_id, _base = await _parent(api, db_session, fake_storage)
        queued = (await api.post(_zones_url(project_id, job_id))).json()["job_id"]
        # Задание поставлено прежней версией генератора.
        stale = await db_session.get(Job, uuid.UUID(queued))
        assert stale is not None
        stale.payload = {
            **stale.payload,
            "generator_version": "cad_mep.v0",
            "params_sha256": "0" * 64,
        }
        await db_session.commit()

        replaced = await _run_zones_worker(db_session, fake_storage, settings, queued)
        assert replaced.status is JobStatus.CANCELLED
        assert replaced.error_code == "CAD_JOB_SUPERSEDED"
        assert cad_service.result_of(replaced)["result_status"] == "superseded"
        new_id = replaced.payload["superseded_by"]
        assert new_id != queued

        fresh = await db_session.get(Job, uuid.UUID(new_id))
        assert fresh is not None and fresh.status is JobStatus.QUEUED
        assert fresh.payload["requeued_from"] == queued
        assert fresh.payload["generator_version"] == "cad_mep.v1"
        assert fresh.payload["view_dxf_sha256"] == replaced.payload["view_dxf_sha256"]
        assert fresh.idempotency_key != replaced.idempotency_key

        done = await _run_zones_worker(db_session, fake_storage, settings, new_id)
        assert done.status is JobStatus.SUCCEEDED
        assert cad_service.result_of(done)["result_status"] == "zones_ready"

        # Перепостановка одна: задание-замена при новом расхождении отказывает, как раньше.
        await db_session.execute(text("delete from cad_zones"))
        again = (await api.post(_zones_url(project_id, job_id))).json()["job_id"]
        chained = await db_session.get(Job, uuid.UUID(again))
        assert chained is not None
        chained.payload = {
            **chained.payload,
            "generator_version": "cad_mep.v0",
            "requeued_from": queued,
        }
        await db_session.commit()
        failed = await _run_zones_worker(db_session, fake_storage, settings, again)
        assert failed.status is JobStatus.FAILED and failed.error_code == "CAD_PARAMS_INVALID"


async def test_walls_job_queued_before_pin_change_is_requeued_and_gets_quality(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        (first,) = await cad_walls_service.enqueue_after_convert(
            db_session, fake_storage, parent, settings
        )
        first.payload = {**first.payload, "generator_version": "cad_walls.v0"}
        await db_session.commit()
        first_id = str(first.id)

        replaced = await _run_walls_worker(db_session, fake_storage, settings, first_id)
        assert replaced.status is JobStatus.CANCELLED
        assert replaced.error_code == "CAD_JOB_SUPERSEDED"
        new_id = replaced.payload["superseded_by"]
        fresh = await db_session.get(Job, uuid.UUID(new_id))
        assert fresh is not None and fresh.payload["requeued_from"] == first_id
        assert fresh.payload["generator_version"] == "cad_walls.v1"
        assert fresh.payload["zones_sha256"] == replaced.payload["zones_sha256"]

        done = await _run_walls_worker(db_session, fake_storage, settings, new_id)
        assert done.status is JobStatus.SUCCEEDED, (done.error_code, done.error_message)
        result = cad_service.result_of(done)
        # Итог задания прежний, порог качества - отдельным блоком: у заглушки 15 % площади
        # конструкций без номинала толщины.
        assert result["result_status"] == "walls_ready"
        assert result["quality"]["status"] == "review"
        assert [reason["code"] for reason in result["quality"]["reasons"]] == [
            "thickness_check_share"
        ]

        # Конвейер показывает замену (она новее) с причинами «на проверку»; лист не «готов».
        pipeline = await cad_pipeline.build_pipeline(
            db_session,
            workspace_id=done.workspace_id or uuid.uuid4(),
            project_id=uuid.UUID(project_id),
            revision_id=uuid.UUID(revision_id),
            pinned=cad_pins.pinned_versions(settings),
        )
        (sheet,) = pipeline.sheets
        walls = sheet.views[0].walls
        assert walls is not None and str(walls.job_id) == new_id
        assert walls.quality_status == "review"
        assert walls.quality_reasons and "толщина не определена" in walls.quality_reasons[0]
        assert cad_summary.sheet_state(sheet) == "review"
        assert sheet.stale == []


# ------------------------------------------------------------------ метка «устарел»


def _repin(settings: Settings) -> None:
    """Смена закрепления в pins.json теста: движок, cad_walls и генератор зон."""
    pins_path = Path(settings.cad_engine_pins)
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    pins["engine"] = {"version": "2099.01.01+new"}
    pins["generators"]["cad_walls"]["generator_version"] = "cad_walls.v2"
    pins["generators"]["cad_mep"]["generator_version"] = "cad_mep.v2"
    pins_path.write_text(json.dumps(pins), encoding="utf-8")


async def test_pipeline_marks_stages_done_by_another_version_as_stale(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        # Авторазметка ставит пересчёт конструкций с зонами: он и есть задание конструкций вида.
        await _auto_zones(api, db_session, fake_storage, settings, project_id, job_id)
        (walls,) = await db_session.scalars(select(Job).where(Job.job_type == JobType.CAD_WALLS))
        done = await _run_walls_worker(db_session, fake_storage, settings, str(walls.id))
        assert done.status is JobStatus.SUCCEEDED, (done.error_code, done.error_message)
        url = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/pipeline"

        # Всё сделано закреплёнными версиями (закрепления движка в pins теста нет).
        (sheet,) = (await api.get(url)).json()["sheets"]
        assert sheet["stale"] == []
        assert sheet["views"][0]["zones_recreatable"] is True

        # Пин сменился: движок, cad_walls и генератор зон.
        _repin(settings)

        (sheet,) = (await api.get(url)).json()["sheets"]
        assert sheet["stale"] == [
            {
                "stage": "convert",
                "view": None,
                "was": cad_service.ENGINE_VERSION,
                "now": "2099.01.01+new",
            },
            {"stage": "walls", "view": 1, "was": "cad_walls.v1", "now": "cad_walls.v2"},
            {"stage": "zones", "view": None, "was": "cad_mep.v1", "now": "cad_mep.v2"},
        ]

        # Версия не записана - «версия неизвестна» (`was = null`), этап тоже считается устаревшим.
        parent = await db_session.get(Job, uuid.UUID(job_id))
        assert parent is not None
        parent.payload = {k: v for k, v in parent.payload.items() if k != "engine_version"}
        # Зона человека версии не имеет: зоны листа из метки уходят и не пересоздаются.
        zone = (await db_session.scalars(select(CadZone).limit(1))).one()
        await db_session.execute(
            update(CadZone).where(CadZone.id == zone.id).values(source="unknown")
        )
        await db_session.commit()
        (sheet,) = (await api.get(url)).json()["sheets"]
        assert [(item["stage"], item["was"]) for item in sheet["stale"]] == [
            ("convert", None),
            ("walls", "cad_walls.v1"),
        ]
        assert sheet["views"][0]["zones_recreatable"] is False


# ------------------------------------------------------------------ миграция 0044


def _migration() -> Any:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20261116_0044_cad_zone_quality.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0044", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_migration_backfill_tells_auto_from_human_only_when_it_is_certain(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    settings: Settings,
) -> None:
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _base = await _parent(api, db_session, fake_storage)
        job = await _auto_zones(api, db_session, fake_storage, settings, project_id, job_id)
        human = await api.post(
            f"/api/v1/projects/{project_id}/cad/zones",
            json=_room(
                revision_id, room_mark="ручная", points=[[0.7, 0.7], [0.8, 0.7], [0.8, 0.8]]
            ),
        )
        assert human.status_code == 201

        # Состояние до миграции: происхождение неизвестно. Одна авто-зона позже правилась, одна
        # создана без автора вне задания разметки (скрипт), остальные не тронуты.
        marks = {z.room_mark: z for z in await db_session.scalars(select(CadZone))}
        started = job.started_at or datetime.now(UTC)
        await db_session.execute(
            text(
                "update cad_zones set source = 'unknown', generator_version = null, "
                "created_at = :at, updated_at = :at"
            ),
            {"at": started + timedelta(milliseconds=1)},
        )
        await db_session.execute(
            text("update cad_zones set updated_at = created_at + interval '1 hour' where id = :id"),
            {"id": marks["3-1/2"].id},
        )
        await db_session.execute(
            text(
                "update cad_zones set created_at = created_at - interval '1 day', "
                "updated_at = created_at - interval '1 day' where id = :id"
            ),
            {"id": marks["3-1/3"].id},
        )
        await db_session.commit()

        migration = _migration()
        await db_session.execute(text(migration.BACKFILL_HUMAN_SQL))
        await db_session.execute(text(migration.BACKFILL_AUTO_SQL))
        await db_session.commit()
        db_session.expire_all()

        rows = {z.room_mark: z for z in await db_session.scalars(select(CadZone))}
        assert rows["ручная"].source == "human"
        assert rows["3-1/2"].source == "unknown"  # правилась после создания
        assert rows["3-1/3"].source == "unknown"  # создана вне задания разметки
        assert (rows["3-1/1"].source, rows["3-1/1"].generator_version) == ("auto", "cad_mep.v1")
        assert sum(1 for z in rows.values() if z.source == "auto") == 6
