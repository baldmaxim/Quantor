"""Проверенная привязка проёма к угловому примыканию на листе 32 АР ЖК «Знаки»."""

import json
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

PROJECT_ID = "0a4ca7b0-c49e-44f6-a599-2bb533dcfb39"
PDF_SHA256 = "16220ac0374278b2737f4d89294dc18e42dbed8c723e5cb870a13d0129bd5103"
DXF_SHA256 = "65374021eb333fdc706773966f2114aa652c9ad23b7dd2fb0f9491ca43ab5aca"
DOOR_ID = "4bfa916c785b"
HOST_ID = "10a9f2908b07"
# Грани монолитных откосов по наложению PDF и DXF. Координаты полигонов в мм.
LEFT, RIGHT, BOTTOM, TOP = 22967.0, 24419.7, 13972.6, 14173.0


def applies(project_id: str, pdf_sha256: str, dxf_sha256: str, page: int, view: int) -> bool:
    return (project_id, pdf_sha256, dxf_sha256, page, view) == (
        PROJECT_ID,
        PDF_SHA256,
        DXF_SHA256,
        80,
        1,
    )


def _leaf(dxf: Path) -> list[list[float]]:
    ezdxf = import_module("ezdxf")
    geometry = import_module("shapely.geometry")
    ops = import_module("shapely.ops")
    block = ezdxf.readfile(dxf).entitydb["2FEB"]
    if block.dxftype() != "INSERT" or block.dxf.name != "AR_DOOR_BLOCK_015":
        raise ValueError("Блок дверного полотна изменился")
    lines = [
        geometry.LineString(
            [(round(p.x, 1), round(p.y, 1)) for p in (entity.dxf.start, entity.dxf.end)]
        )
        for entity in block.virtual_entities()
        if entity.dxftype() == "LINE"
    ]
    rings = [ring for ring in ops.polygonize(lines) if ring.area > 0]
    if len(rings) != 1 or len(rings[0].exterior.coords) != 5:
        raise ValueError("Прямоугольный контур полотна не найден в DXF")
    return [[x, y] for x, y in list(rings[0].exterior.coords)[:-1]]


def correct(document: dict[str, Any], dxf: Path) -> None:
    geometry = import_module("shapely.geometry")

    if document["dxf_sha256"] != DXF_SHA256:
        raise ValueError("Редакция DXF не совпала")
    door = next(row for row in document["openings"] if row["id"] == DOOR_ID)
    if door["handle"] != "2FEB" or door["host_id"] != HOST_ID:
        raise ValueError("Привязка двери изменилась")
    if door["status"] != "no_data":
        return

    def polygon(row: dict[str, Any]) -> Any:
        ring = row["polygon"]
        return geometry.Polygon(ring["shell"], ring["holes"])

    rows = document["constructions"] + document.get("frame_partitions", [])
    host = polygon(next(row for row in rows if row["id"] == HOST_ID))
    # Проверяем прямоугольник проёма и по одному миллиметру материала за каждой гранью.
    opening = geometry.box(LEFT, BOTTOM + 1, RIGHT, TOP - 1)
    for strip in (
        geometry.box(LEFT - 1, BOTTOM + 1, LEFT, TOP - 1),
        geometry.box(RIGHT, BOTTOM + 1, RIGHT + 1, TOP - 1),
    ):
        if not host.covers(strip):
            raise ValueError("Откос не подтверждён полигоном монолита")
    if any(polygon(row).intersection(opening).area > 1 for row in rows):
        raise ValueError("В границах проёма найдена конструкция")

    door.update(
        status="estimate",
        width_mm=round(RIGHT - LEFT, 1),
        width_source="gap",
        thickness_mm=round(TOP - BOTTOM, 1),
        direction=[1.0, 0.0],
        lintel=[[LEFT, BOTTOM], [RIGHT, BOTTOM], [RIGHT, TOP], [LEFT, TOP]],
        lintel_material="monolith",
        leaf=_leaf(dxf),
    )
    document["opening_corrections"] = [
        {
            "opening_id": DOOR_ID,
            "method": "verified_corner_jambs",
            "reference": "АР1.1, лист 32, стр. 81 PDF, DXF INSERT 2FEB",
        }
    ]
    warnings = document["checks"]["warnings"]
    warnings[:] = [
        row
        for row in warnings
        if not (row["code"] == "door_without_gap" and DOOR_ID in row["message"])
    ]


if __name__ == "__main__":
    path = Path(sys.argv[1])
    document = json.loads(path.read_bytes())
    correct(document, Path(sys.argv[2]))
    path.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False), encoding="utf-8")
