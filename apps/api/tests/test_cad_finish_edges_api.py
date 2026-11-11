"""Ведомость отделки по API с привязкой рёбер (ADR-0042, п. 6): walls.json с перемычками и кадр.

Родитель CAD выставлен прямо в базе и хранилище (кадр: масштаб оператора 35,2778 мм/pt, начало
(10, 20) pt), скрипт `cad_walls` подменён заглушкой, которая отдаёт заранее заданный walls.json.
Комната 4 x 5 м: юг и север - монолит, запад - кладка с дверью 900 мм (перемычка), восток -
каркасная перегородка ГКЛ на 3 м.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import cad_zones
from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_constructions_api import (
    _ready_sheet,
    walls_settings,
    walls_tools,
)
from tests.test_cad_finishes import _body, _sheet_url, _templates_url, _zones_url
from tests.test_cad_zones import _room

__all__ = ["walls_tools"]

FACTOR = 35.2778
ORIGIN = (10.0, 20.0)

STUB = """
import argparse, hashlib, json, pathlib

parser = argparse.ArgumentParser()
for name in ("dxf", "params", "out", "pdf", "page", "zones"):
    parser.add_argument("--" + name)
args = parser.parse_args()
here = pathlib.Path(__file__).parent
doc = json.loads((here / "doc.json").read_text(encoding="utf-8"))
raw = json.loads(pathlib.Path(args.params).read_text(encoding="utf-8"))
doc["params_version"] = pathlib.Path(args.params).stem
doc["params_sha256"] = hashlib.sha256(
    json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
doc["dxf_sha256"] = hashlib.sha256(pathlib.Path(args.dxf).read_bytes()).hexdigest()
pathlib.Path(args.out).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
"""


def rect(x0: float, y0: float, x1: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def construction(key: str, kind: str, shell: list[list[float]]) -> dict[str, Any]:
    xs = [p[0] for p in shell]
    ys = [p[1] for p in shell]
    return {
        "id": key,
        "kind": kind,
        "source_layers": ["тест"],
        "polygon": {"shell": shell, "holes": []},
        "area_plan_mm2": 1.0,
        "thickness_measured_mm": 200.0,
        "thickness_nominal_mm": 200.0,
        "thickness_status": "matched",
        "length_axis_mm": 1.0,
        "centroid": [sum(xs) / 4, sum(ys) / 4],
        "bbox": [min(xs), min(ys), max(xs), max(ys)],
    }


def walls_document(*, outdated: bool = False) -> dict[str, Any]:
    """Комната DXF: x 0..4000, y -5000..0 (мм), контур зоны по внутренним граням."""
    doc: dict[str, Any] = {
        "schema": "quantor.cad_walls.v1",
        "generator": "cad_walls.v1",
        "params_version": "v1",
        "params_sha256": "0" * 64,
        "dxf_sha256": "0" * 64,
        "units": "mm",
        "heights": {
            "floor_elevation_mm": 47600,
            "floor_height_mm": 3000,
            "elevation_status": "observed",
            "height_status": "derived",
            "evidence": "стр. 1",
            "message": None,
            "slab_thickness_mm": 200,
            "slab_status": "assumption",
            "door_height_mm": 2100,
            "door_height_status": "assumption",
        },
        "constructions": [
            construction("monolith0001", "monolith_wall", rect(-200, -5200, 4200, -5000)),
            construction("monolith0002", "monolith_wall", rect(-200, 0, 4200, 200)),
            construction("masonry0001", "masonry", rect(-200, -1000, 0, 0)),
            construction("masonry0002", "masonry", rect(-200, -5000, 0, -1900)),
        ],
        "frame_partitions": [
            construction("gkl000000001", "frame_partition", rect(4000, -3000, 4200, 0))
        ],
        "openings": [
            {
                "id": "door00000001",
                "kind": "door",
                "status": "ok",
                "host_id": "masonry0001",
                "adjacent_ids": ["masonry0001", "masonry0002"],
                "width_mm": 900.0,
                "width_source": "gap",
                "thickness_mm": 200.0,
                "block_name": None,
                "handle": None,
                "center": [-100.0, -1450.0],
            }
        ],
        "totals": [],
        "checks": {"warnings": []},
    }
    if not outdated:
        doc["slab"] = None
        doc["slab_holes"] = []
        doc["openings"][0]["lintel"] = rect(-200, -1900, 0, -1000)
    return doc


def normalized(points: list[tuple[float, float]], width_pt: float, height_pt: float) -> list[Any]:
    return [
        [(ORIGIN[0] + x / FACTOR) / width_pt, (ORIGIN[1] - y / FACTOR) / height_pt]
        for x, y in points
    ]


async def _sheet_with_room(
    api: AsyncClient,
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
    *,
    outdated: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    (walls_tools / "run_walls.py").write_text(STUB, encoding="utf-8")
    (walls_tools / "doc.json").write_text(json.dumps(walls_document(outdated=outdated)))
    settings = walls_settings(walls_tools, tmp_path)
    project_id, revision_id, _job, _walls = await _ready_sheet(
        api, db_session, fake_storage, settings
    )
    geometry = (
        await cad_zones.page_scales(
            db_session, revision_id=uuid.UUID(revision_id), page_indexes={0}
        )
    )[0].geometry
    assert geometry is not None
    ring = normalized(
        [(0, 0), (4000, 0), (4000, -5000), (0, -5000)],
        float(geometry.display_width_pt),
        float(geometry.display_height_pt),
    )
    body = _room(revision_id, name="Спальня") | {"points": ring}
    created = await api.post(await _zones_url(project_id), json=body)
    assert created.status_code == 201, created.text
    template = (
        await api.post(
            _templates_url(project_id),
            json=_body(
                room_types=["living"],
                walls_include_reveals=True,
                wall_layers=[
                    {"work": "Грунтовка", "consumption": 0.2, "consumption_unit": "л"},
                    {"work": "Обеспыливание", "bases": ["monolith"]},
                ],
            ),
        )
    ).json()
    assert template["walls_include_reveals"] is True
    return project_id, revision_id, created.json()


async def test_sheet_links_zone_edges_to_constructions(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=walls_settings(walls_tools, tmp_path)) as api:
        project_id, revision_id, _zone = await _sheet_with_room(
            api, db_session, fake_storage, walls_tools, tmp_path
        )
        sheet = (await api.get(_sheet_url(project_id, revision_id))).json()
        (row,) = sheet["zones"]
        breakdown = row["walls_breakdown"]
        assert breakdown["linked"] is True
        # Ребро ровно по граням: монолит юг + север, ГКЛ с размытием на допуск у торца.
        assert breakdown["monolith_m"] == pytest.approx(8.0, abs=0.35)
        assert breakdown["masonry_m"] == pytest.approx(4.1, abs=0.35)
        assert breakdown["door_m"] == pytest.approx(0.9, abs=0.15)
        assert breakdown["gkl_m"] == pytest.approx(3.0, abs=0.35)
        assert breakdown["open_m"] == pytest.approx(1.9, abs=0.45)
        # Уровни заглушки: этаж 3000 - плита 200 = 2800, минус стяжка шаблона 40 мм; дверь 2100.
        door_over = breakdown["door_over_area_m2"]
        assert door_over == pytest.approx(breakdown["door_m"] * 0.66, rel=1e-6)
        assert breakdown["reveal_m"] == pytest.approx(2 * 2.1 + breakdown["door_m"], abs=0.2)
        assert breakdown["reveal_area_m2"] > 0
        assert row["wall_height_mm"] == pytest.approx(2760.0)
        base_total = sum(breakdown["area_by_base"][name] for name in ("monolith", "masonry", "gkl"))
        assert row["wall_area_m2"] == pytest.approx(base_total + door_over)
        # Откосы входят в слой без ограничения (шаблон включает) и не входят в слой по монолиту.
        plain, dust = (layer for layer in row["layers"] if layer["surface"] == "walls")
        assert plain["bases"] is None and dust["bases"] == ["monolith"]
        assert plain["area_m2"] == pytest.approx(row["wall_area_m2"] + breakdown["reveal_area_m2"])
        assert dust["area_m2"] == pytest.approx(breakdown["area_by_base"]["monolith"])
        codes = {warning["code"]: warning["zone_ids"] for warning in sheet["warnings"]}
        assert codes == {"windows_not_detected": [row["zone_id"]]}


async def test_sheet_with_old_walls_json_falls_back_to_perimeter(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    async with build_api(make_context(), settings=walls_settings(walls_tools, tmp_path)) as api:
        project_id, revision_id, zone = await _sheet_with_room(
            api, db_session, fake_storage, walls_tools, tmp_path, outdated=True
        )
        sheet = (await api.get(_sheet_url(project_id, revision_id))).json()
        (row,) = sheet["zones"]
        assert row["walls_breakdown"]["linked"] is False
        assert row["walls_breakdown"]["monolith_m"] is None
        assert row["wall_area_m2"] == pytest.approx(zone["perimeter_m"] * 2.76)
        plain, dust = (layer for layer in row["layers"] if layer["surface"] == "walls")
        assert plain["area_m2"] == pytest.approx(row["wall_area_m2"]) and dust["area_m2"] is None
        assert [warning["code"] for warning in sheet["warnings"]] == ["edges_unlinked"]
