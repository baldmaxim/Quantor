"""Полностью синтетическая модель и пакет Revit: для тестов и примера в docs/building-model.

Примеры `revit-package-v0.example.json` и `revit-building-package-v0.example.json` порождаются
именно этой фикстурой (`python -m tests.revit_fixture` пересобирает их), тест сверяет файлы с
результатом.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from building_model.approval import ApprovalOut
from building_model.canonical import BuildingModel
from building_model.pipeline import TenderArgs, build_model, dumps_model
from building_model.reader import AxisIn, Document, Excluded, read_sheet
from building_model.revit import build_package
from building_model.revit_building import SheetInput, build_building_package
from building_model.revit_format import (
    RevitBuildingPackage,
    RevitPackage,
    dumps_building_package,
    dumps_package,
)
from tests.synth import OX, OY, JsonObj, axis, build, document, door, gap_item, make_sheet, sp, wall

FIXED_AT = "2026-01-01T00:00:00Z"
DOCS_DIR = Path(__file__).resolve().parents[3] / "docs" / "building-model"
EXAMPLE_PATH = DOCS_DIR / "revit-package-v0.example.json"
BUILDING_EXAMPLE_PATH = DOCS_DIR / "revit-building-package-v0.example.json"


def synthetic_sheet() -> JsonObj:
    walls = [
        wall("W0", (0, 0), (6000, 0), t=300, role="outer wall"),
        wall("W1", (6000, 0), (6000, 5000), t=300, role="outer wall"),
        wall("W2", (6000, 5000), (0, 5000), t=300, role="outer wall"),
        wall("W3", (0, 5000), (0, 0), t=300, role="outer wall"),
        wall("W4", (3000, 0), (3000, 5000), t=100),
        wall("W5", (500, 3000), (700, 3000), t=400, role="column"),
    ]
    rooms = [
        {
            "id": "R0", "type": "living", "type_source": "name", "area_m2": 12.0, "tag": "1",
            "polygon_mm": [sp(200, 200), sp(2900, 200), sp(2900, 2900), sp(200, 2900)],
        },
        {
            # П-образное помещение: центроид лежит в вырезе, вне контура.
            "id": "R1", "type": "corridor", "type_source": "geometry", "area_m2": 8.0,
            "polygon_mm": [
                sp(3200, 200), sp(5800, 200), sp(5800, 4800), sp(5000, 4800), sp(5000, 1000),
                sp(4000, 1000), sp(4000, 4800), sp(3200, 4800),
            ],
        },
    ]  # fmt: skip
    return make_sheet(
        title={"floors": [5, 6], "level_m": 14.0, "levels_m": [14.0, 17.3]},
        floor_level={"level_m": 14.0},
        walls=walls,
        doors=[door("D0", (1000, 0), (2000, 0), (1000, 1000), 1000)],
        windows=[gap_item("O0", (0, 1500), (0, 2500)), gap_item("O1", (4000, 5000), (5000, 5000))],
        openings=[gap_item("H0", (9000, 9000), (9800, 9000))],
        rooms=rooms,
        stairs=[
            {
                "id": "T0",
                "polygon_mm": [sp(3300, 3300), sp(3900, 3300), sp(3900, 4500), sp(3300, 4500)],
                "slab_opening_mm": [sp(3300, 3300), sp(3900, 3300), sp(3900, 4500), sp(3300, 4500)],
            }
        ],
        slab_outlines_mm=[[sp(-150, -150), sp(6150, -150), sp(6150, 5150), sp(-150, 5150)]],
    )  # fmt: skip


def synthetic_model() -> BuildingModel:
    return build(synthetic_sheet())


def synthetic_approval(model: BuildingModel) -> ApprovalOut:
    return ApprovalOut(
        page=0,
        model_sha256=model_sha(model),
        mm_per_pt=35.0,
        by="Проверяющий (синтетический пример)",
        at=FIXED_AT,
        note="пример, не реальное подтверждение",
    )


def model_sha(model: BuildingModel) -> str:
    return hashlib.sha256(dumps_model(model).encode("utf-8")).hexdigest()


def synthetic_package(approved: bool = True) -> RevitPackage:
    model = synthetic_model()
    return build_package(model, synthetic_approval(model) if approved else None, model_sha(model))


def example_text() -> str:
    return dumps_package(synthetic_package())


# --- пакет здания: две синтетические страницы с разными началами координат ---

PAGE_SHIFT = (400.0, -700.0)
_POINT_KEYS = frozenset(
    {"a", "b", "polygon_mm", "hinge_mm", "end_a_mm", "end_b_mm", "a_mm", "b_mm"}
    | {"slab_opening_mm", "slab_outlines_mm"}
)


def _is_point(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
    )


def shift_json(value: object, dx: float, dy: float, key: str | None = None) -> object:
    """Сдвигает все точки листа plangeom (положение листа на бумаге)."""
    if isinstance(value, dict):
        return {k: shift_json(v, dx, dy, k) for k, v in value.items()}
    if isinstance(value, list):
        if key in _POINT_KEYS and _is_point(value):
            return [value[0] + dx, value[1] + dy]
        return [shift_json(v, dx, dy, key) for v in value]
    return value


def building_axes(dx: float, dy: float, origin: tuple[str, str]) -> list[JsonObj]:
    """Сетка 3 x 2 оси; пара `origin` имеет больше кружков и становится началом координат модели."""
    raw = [
        ("1", (1.0, 0.0), OX + dx),
        ("3", (1.0, 0.0), OX + 3000 + dx),
        ("2", (1.0, 0.0), OX + 6000 + dx),
        ("A", (0.0, 1.0), OY + dy),
        ("B", (0.0, 1.0), OY - 5000 + dy),
    ]
    return [
        axis(label, normal, offset, 3 if label in origin else 2) for label, normal, offset in raw
    ]


def building_sheet(
    page: int,
    floors: list[int],
    levels_m: list[float],
    origin: tuple[str, str] = ("1", "A"),
    shift: tuple[float, float] = (0.0, 0.0),
) -> JsonObj:
    """Копия синтетического листа с другими этажами, положением на бумаге и началом координат."""
    base = synthetic_sheet()
    moved = shift_json(base, shift[0], shift[1])
    assert isinstance(moved, dict)
    sheet = make_sheet(page=page, **{k: v for k, v in moved.items() if k not in ("page", "source")})
    sheet["title"] = {"floors": floors, "level_m": levels_m[0], "levels_m": levels_m}
    sheet["floor_level"] = {"level_m": levels_m[0]}
    sheet["axes"] = building_axes(shift[0], shift[1], origin)
    return sheet


def building_document(second_floors: list[int] | None = None) -> Document:
    floors = second_floors or [7, 8]
    levels = [20.6, 23.9] if floors == [7, 8] else [round(14.0 + 3.3 * (f - 5), 1) for f in floors]
    first = building_sheet(0, [5, 6], [14.0, 17.3])
    second = building_sheet(1, floors, levels, origin=("2", "B"), shift=PAGE_SHIFT)
    return document(first, second, buildings=[{"sheets": [0, 1]}])


def building_inputs(doc: Document | None = None, approved: bool = True) -> list[SheetInput]:
    used = doc or building_document()
    result: list[SheetInput] = []
    for page in used.pages():
        sheet = read_sheet(used, page)
        assert not isinstance(sheet, Excluded)
        model = build_model(used, page, TenderArgs())
        approval = (
            ApprovalOut(
                page=page,
                model_sha256=model_sha(model),
                mm_per_pt=35.0,
                by="Проверяющий (синтетический пример)",
                at=FIXED_AT,
                note="пример, не реальное подтверждение",
            )
            if approved
            else None
        )
        axes: list[AxisIn] = sheet.axes or []
        result.append(SheetInput(page, model, approval, model_sha(model), axes))
    return result


def building_package(approved: bool = True) -> RevitBuildingPackage:
    return build_building_package(building_inputs(approved=approved), 0, [], [], [], "0" * 64)


def building_example_text() -> str:
    return dumps_building_package(building_package())


if __name__ == "__main__":
    EXAMPLE_PATH.write_text(example_text(), encoding="utf-8")
    BUILDING_EXAMPLE_PATH.write_text(building_example_text(), encoding="utf-8")
    print(f"записано {EXAMPLE_PATH.name}, {BUILDING_EXAMPLE_PATH.name}")
