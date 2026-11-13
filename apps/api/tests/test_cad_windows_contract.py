"""Приём окон cad_walls v1.12 (`kind = "window"`): контракт, объём конструкций и 3D этажа.

Окно по плану высоты не имеет (`opening_height_mm = None`, статус `unknown`): допущений нет.
Окно без высоты не вычитается из кладки и не строится в 3D; окно с высотой считается как разрыв
с известной высотой. Ожидаемые числа выписаны руками.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.contracts.cad_constructions import WallsDocument
from app.contracts.cad_floor3d import WallsFloorExtras
from app.services import cad_constructions as calc
from app.services import cad_floor3d as f3d
from tests.test_cad_constructions_calc import NO_LEVELS, construction, document, opening
from tests.test_cad_floor3d import BASE, raw_document, raw_extras
from tests.test_cad_floor3d import NO_LEVELS as NO_LEVELS_3D

WINDOW_LINTEL = [[3000.0, 0.0], [4000.0, 0.0], [4000.0, 200.0], [3000.0, 200.0]]


def window(
    key: str = "win00000001",
    host: str | None = "c1",
    *,
    status: str = "no_data",
    height: int | None = None,
) -> dict[str, Any]:
    """Окно в формате движка v1.12: `leaf`/`block_name` пусты, перемычка — прямоугольник пролёта."""
    return {
        **opening(key, host, kind="window", status=status),
        "width_source": "window_bay" if status == "no_data" else "gap",
        "handle": "1A2B",
        "lintel": WINDOW_LINTEL,
        "lintel_material": None,
        "window": {"bay_id": "GLAZING_BAY_001"},
        "opening_height_mm": height,
        "opening_height_status": "unknown" if height is None else "observed",
    }


# ------------------------------------------------------------------ контракт и объём


def test_window_opening_is_read_by_the_walls_contract() -> None:
    doc = document([construction()], [window()])
    [item] = doc.openings
    assert item.kind == "window" and item.window is not None
    assert item.window.bay_id == "GLAZING_BAY_001"
    assert item.opening_height_mm is None and item.opening_height_status == "unknown"


def test_window_without_height_is_not_subtracted_and_warns() -> None:
    plain = calc.compute_sheet(document([construction()]), {}, NO_LEVELS)
    result = calc.compute_sheet(document([construction()], [window()]), {}, NO_LEVELS)
    computed = result.constructions[0].computed
    assert computed.volume_m3 == plain.constructions[0].computed.volume_m3
    assert computed.wall_area_m2 == plain.constructions[0].computed.wall_area_m2
    assert computed.sources.gap_opening_height is None
    assert computed.warnings == ["opening_no_data"]
    assert result.summary.unaccounted_gap_openings == 1
    assert result.summary.door_openings_without_host == 0
    assert (calc.WINDOW_HEIGHT_UNKNOWN, "Высота окна неизвестна: окна не вычтены из кладки") in (
        result.partition_warnings
    )
    assert plain.partition_warnings == []
    assert [o.kind for o in result.openings] == ["window"]


def test_window_without_height_has_no_lintel_even_with_monolith_material() -> None:
    raw = window(status="ok")
    raw["lintel_material"] = "monolith"
    result = calc.compute_sheet(document([construction()], [raw]), {}, NO_LEVELS)
    assert [t for t in result.totals if t.element == "lintel"] == []
    assert result.summary.lintels_without_volume == 0


def test_window_with_height_is_counted_as_a_gap_with_a_known_height() -> None:
    doc = document([construction()], [window(status="ok", height=1500)])
    result = calc.compute_sheet(doc, {}, NO_LEVELS)
    computed = result.constructions[0].computed
    # H = 3000 - 200 = 2800; надпроёмная часть = ширина 1000 x t 200 x (2800 - 1500)
    assert computed.volume_m3 == pytest.approx((1_000_000 * 2800 + 1000 * 200 * 1300) / 1e9)
    assert computed.sources.gap_opening_height == "observed"
    assert computed.warnings == []
    assert result.summary.unaccounted_gap_openings == 0
    assert result.partition_warnings == []


# ------------------------------------------------------------------ 3D этажа


def _build_3d(opening_patch: dict[str, Any]) -> Any:
    raw = raw_document()
    raw["openings"] = [
        {**window("win00000001", "aaaaaaaaaaaa"), **opening_patch},
    ]
    extras = raw_extras()
    extras["openings"] = [
        {"id": "win00000001", "direction": [1.0, 0.0], "lintel": WINDOW_LINTEL, "leaf": None}
    ]
    return f3d.build_floor3d(
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(extras),
        props_by_key={},
        overrides=NO_LEVELS_3D,
        project_slab=None,
        hole_decisions={},
        door_zones=[],
    )


def test_floor3d_skips_a_window_without_height_and_warns_once() -> None:
    model = _build_3d({"opening_height_mm": None})
    assert model.lintels == [] and model.doors == []
    codes = [w.code for w in model.warnings]
    assert codes.count("window_height_unknown") == 1
    # высота двери листа окну не подставляется
    assert "door_height_missing" not in codes and "lintel_missing" not in codes
    assert all(wall.z_top_mm == BASE + 2800 for wall in model.walls)


def test_floor3d_builds_a_window_with_height_like_a_gap() -> None:
    model = _build_3d(
        {"status": "ok", "opening_height_mm": 1500, "opening_height_status": "observed"}
    )
    [lintel] = model.lintels
    assert (lintel.opening_id, lintel.kind) == ("win00000001", "window")
    assert (lintel.z_bottom_mm, lintel.z_top_mm) == (BASE + 1500, BASE + 2800)
    assert (lintel.door_height_mm, lintel.door_height_source) == (1500, "observed")
    assert "window_height_unknown" not in [w.code for w in model.warnings]


@pytest.mark.parametrize("code", ["window_bay_without_host", "window_bay_door_overlap"])
def test_floor3d_passes_the_window_bay_warnings(code: str) -> None:
    raw = raw_document()
    raw["checks"] = {"warnings": [{"code": code, "message": "предупреждение пролёта"}]}
    model = f3d.build_floor3d(
        WallsDocument.model_validate(raw),
        WallsFloorExtras.model_validate(raw_extras()),
        props_by_key={},
        overrides=NO_LEVELS_3D,
        project_slab=None,
        hole_decisions={},
        door_zones=[],
    )
    assert code in [w.code for w in model.warnings]
