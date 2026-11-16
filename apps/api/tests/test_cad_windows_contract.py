"""Приём окон cad_walls v1.12 (`kind = "window"`): контракт, объём конструкций и 3D этажа.

Окно по плану высоты не имеет (`opening_height_mm = None`, статус `unknown`): допущений нет.
Окно без высоты не вычитается из кладки и не строится в 3D; окно с высотой считается как разрыв
с известной высотой. Ожидаемые числа выписаны руками.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.api.v1.cad_floor3d import _without_unaccepted_windows
from app.contracts.cad_constructions import WallsDocument
from app.contracts.cad_floor3d import WallsFloorExtras
from app.services import cad_constructions as calc
from app.services import cad_floor3d as f3d
from app.services.cad_facade_windows import FacadeWindowHeight
from tests.test_cad_constructions_calc import NO_LEVELS, construction, document, opening
from tests.test_cad_floor3d import BASE, raw_document, raw_extras
from tests.test_cad_floor3d import NO_LEVELS as NO_LEVELS_3D

REVISION = uuid.uuid4()
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


# ------------------------------------------------------------------ высота окна с фасада (ADR-0048)


def facade_height(
    *, sill: int = 900, head: int = 2400, accepted: bool = True
) -> FacadeWindowHeight:
    return FacadeWindowHeight(
        sill_mm=sill,
        head_mm=head,
        accepted=accepted,
        view_id=uuid.uuid4(),
        view_key="p36v1",
        page_index=35,
        revision_id=REVISION,
        title="Фасад в осях 1-5",
        overlap=1.0,
        axes_checked=True,
    )


def _build_3d_facade(height: FacadeWindowHeight | None) -> Any:
    raw = raw_document()
    raw["openings"] = [window("win00000001", "aaaaaaaaaaaa")]
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
        window_heights=None if height is None else {"win00000001": height},
    )


def test_floor3d_builds_sill_glass_and_lintel_from_a_facade_height() -> None:
    model = _build_3d_facade(facade_height())
    [item] = model.windows
    assert item.opening_id == "win00000001" and item.host_id == "aaaaaaaaaaaa"
    assert (item.sill_z_bottom_mm, item.sill_z_top_mm) == (BASE, BASE + 900)
    assert item.glass_z_top_mm == BASE + 2400
    assert (item.sill_mm, item.head_mm, item.accepted) == (900, 2400, True)
    assert (item.facade_view_key, item.facade_page_index) == ("p36v1", 35)
    assert item.facade_revision_id == REVISION and item.facade_title == "Фасад в осях 1-5"
    [lintel] = model.lintels
    assert (lintel.kind, lintel.opening_id) == ("window", "win00000001")
    assert (lintel.z_bottom_mm, lintel.z_top_mm) == (BASE + 2400, BASE + 2800)
    assert (lintel.door_height_mm, lintel.door_height_source) == (2400, "observed")
    codes = [w.code for w in model.warnings]
    assert "window_height_unknown" not in codes and "facade_windows_unaccepted" not in codes


def test_floor3d_window_without_a_sill_has_equal_sill_levels() -> None:
    [item] = _build_3d_facade(facade_height(sill=0, head=1500)).windows
    assert item.sill_z_bottom_mm == item.sill_z_top_mm == BASE
    assert item.glass_z_top_mm == BASE + 1500


def test_floor3d_window_reaching_the_wall_top_has_no_lintel() -> None:
    model = _build_3d_facade(facade_height(sill=900, head=2900))
    [item] = model.windows
    assert item.glass_z_top_mm == BASE + 2800
    assert model.lintels == []
    assert "opening_reaches_wall_top" in [w.code for w in model.warnings]


def test_floor3d_marks_a_window_from_an_unaccepted_view_as_a_candidate() -> None:
    model = _build_3d_facade(facade_height(accepted=False))
    [item] = model.windows
    assert item.accepted is False
    warning = next(w for w in model.warnings if w.code == "facade_windows_unaccepted")
    assert "1" in warning.message


def test_floor3d_without_facade_heights_has_no_windows() -> None:
    model = _build_3d_facade(None)
    assert model.windows == [] and model.lintels == []
    assert [w.code for w in model.warnings].count("window_height_unknown") == 1


def _window_doc(material: str | None = None) -> WallsDocument:
    raw = window(status="ok")
    raw["lintel_material"] = material
    return document([construction()], [raw])


def test_accepted_facade_window_is_subtracted_by_head_minus_sill() -> None:
    spans = {"win00000001": facade_height()}
    result = calc.compute_sheet(_window_doc(), {}, NO_LEVELS, window_heights=spans)
    computed = result.constructions[0].computed
    # H = 2800; пустота 2400 - 900 = 1500: добавка 1000 x 200 x (2800 - 1500)
    assert computed.volume_m3 == pytest.approx((1_000_000 * 2800 + 1000 * 200 * 1300) / 1e9)
    assert computed.sources.gap_opening_height == "observed"
    assert computed.warnings == []
    assert result.summary.unaccounted_gap_openings == 0
    assert result.partition_warnings == []


def test_candidate_facade_window_is_not_subtracted_and_warns() -> None:
    spans = {"win00000001": facade_height(accepted=False)}
    result = calc.compute_sheet(_window_doc(), {}, NO_LEVELS, window_heights=spans)
    computed = result.constructions[0].computed
    assert computed.volume_m3 == pytest.approx(1_000_000 * 2800 / 1e9)
    assert computed.sources.gap_opening_height is None
    assert result.summary.unaccounted_gap_openings == 1
    codes = [code for code, _message in result.partition_warnings]
    assert calc.WINDOW_HEIGHT_UNKNOWN in codes and calc.FACADE_WINDOWS_CANDIDATE in codes


def test_window_own_height_wins_over_a_facade_height() -> None:
    doc = document([construction()], [window(status="ok", height=1500)])
    spans = {"win00000001": facade_height(sill=0, head=900)}
    result = calc.compute_sheet(doc, {}, NO_LEVELS, window_heights=spans)
    assert result.constructions[0].computed.volume_m3 == pytest.approx(
        (1_000_000 * 2800 + 1000 * 200 * 1300) / 1e9
    )
    assert result.partition_warnings == []


def test_monolith_lintel_over_a_facade_window_starts_at_the_window_head() -> None:
    spans = {"win00000001": facade_height()}
    result = calc.compute_sheet(_window_doc("monolith"), {}, NO_LEVELS, window_heights=spans)
    # кладка под подоконником остаётся в хозяине: 1000 x 200 x 900; над окном - перемычка
    assert result.constructions[0].computed.volume_m3 == pytest.approx(
        (1_000_000 * 2800 + 1000 * 200 * 900) / 1e9
    )
    [lintels] = [t for t in result.totals if t.element == "lintel"]
    # площадь контура 1000 x 200 x (2800 - 2400)
    assert lintels.volume_m3 == pytest.approx(200_000 * 400 / 1e9)
    assert result.summary.lintels_without_volume == 0


def test_floor3d_window_with_a_sill_not_below_the_wall_top_is_not_built() -> None:
    model = _build_3d_facade(facade_height(sill=2800, head=3500))
    assert model.windows == [] and model.lintels == []
    codes = [w.code for w in model.warnings]
    assert "facade_window_above_wall" in codes and "opening_reaches_wall_top" not in codes


def test_floor3d_window_carries_the_axes_check_flag() -> None:
    [item] = _build_3d_facade(facade_height()).windows
    assert item.axes_checked is True


def test_dxf_model_drops_candidate_windows_and_their_lintels() -> None:
    candidate = _build_3d_facade(facade_height(accepted=False))
    assert candidate.windows and candidate.lintels
    stripped = _without_unaccepted_windows(candidate)
    assert stripped.windows == [] and stripped.lintels == []
    accepted = _build_3d_facade(facade_height())
    assert _without_unaccepted_windows(accepted) is accepted


def test_stair_window_above_the_wall_subtracts_only_the_part_inside_it() -> None:
    # стена 2800, sill 2400, head 3900: пустота min(3900, 2800) - 2400 = 400
    spans = {"win00000001": facade_height(sill=2400, head=3900)}
    result = calc.compute_sheet(_window_doc(), {}, NO_LEVELS, window_heights=spans)
    assert result.constructions[0].computed.volume_m3 == pytest.approx(
        (1_000_000 * 2800 + 1000 * 200 * (2800 - 400)) / 1e9
    )


def test_window_with_a_sill_above_the_wall_top_subtracts_nothing() -> None:
    spans = {"win00000001": facade_height(sill=3000, head=3500)}
    result = calc.compute_sheet(_window_doc(), {}, NO_LEVELS, window_heights=spans)
    assert result.constructions[0].computed.volume_m3 == pytest.approx(
        (1_000_000 * 2800 + 1000 * 200 * 2800) / 1e9
    )


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
