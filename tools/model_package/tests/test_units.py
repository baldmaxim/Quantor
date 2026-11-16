"""Мелкие правила: дисциплины, категории, свойства, сведение этажей и осей, заголовки."""

from __future__ import annotations

import json

import pytest

from model_package.disciplines import discipline_from_name, resolve_discipline, split_ifc_arg
from model_package.grids import merge_axes
from model_package.ifc_elements import flatten_psets
from model_package.ifc_source import RawAxis, axis_dir
from model_package.qmp_build import _jsonl_line
from model_package.qmp_check import canonical_json, manifest_digest
from model_package.storeys import StoreyIndex, storey_key
from model_package.titles import match_storey, page_elevations, parse_titles


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("KPLSK_UD_PD_R22_ARCH_1 (20260901).ifc", "ARCH"),
        ("KPLSK_UD_PD_R22_PL.ifc", "PL"),
        ("model_ARCH.ifc", "ARCH"),
        ("ARCH.ifc", "ARCH"),
        ("house_R22.ifc", None),
        ("house.ifc", None),
    ],
)
def test_discipline_from_name(name: str, code: str | None) -> None:
    assert discipline_from_name(name) == code


def test_discipline_resolution() -> None:
    assert resolve_discipline("house.ifc", "str") == ("STR", [])
    assert resolve_discipline("house.ifc", None) == ("UNK", [])
    code, warnings = resolve_discipline("a_ARCH.ifc", "STR")
    assert code == "ARCH" and warnings
    with pytest.raises(ValueError, match="латиница"):
        resolve_discipline("house.ifc", "АР")


def test_split_ifc_arg() -> None:
    assert split_ifc_arg(r"C:\data\m.ifc") == (r"C:\data\m.ifc", None)
    assert split_ifc_arg(r"C:\data\m.ifc:EL") == (r"C:\data\m.ifc", "EL")
    assert split_ifc_arg("m.ifc:PL") == ("m.ifc", "PL")


def test_flatten_psets_limits_and_order() -> None:
    psets = {
        "Прочее": {"id": 1, "Длинное": "x" * 300, "Пусто": "", "Нет": None, "Список": ["a", "b"]},
        "Pset_WallCommon": {
            "id": 2,
            "FireRating": "EI60",
            "LoadBearing": True,
            "Nan": float("nan"),
        },
        "Размеры": {f"p{i}": i for i in range(40)},
    }
    out = flatten_psets(psets)
    assert len(out) == 24
    keys = list(out)
    assert keys[:2] == ["Pset_WallCommon.FireRating", "Pset_WallCommon.LoadBearing"]
    assert out["Прочее.Длинное"] == "x" * 120
    assert out["Прочее.Список"] == "a; b"
    assert "Прочее.Пусто" not in out and "Прочее.Нет" not in out
    assert "Pset_WallCommon.Nan" not in out


def test_storey_key_and_merge() -> None:
    assert storey_key("3k9$Jx_a") == "3k9-Jx_a"
    index = StoreyIndex()
    k1, _ = index.register("A$1", "C00_1_этаж", 0.0, "ifc_storey_elevation", "a.ifc")
    k2, _ = index.register("B1", "C00_2_этаж", 3000.0, "ifc_storey_elevation", "a.ifc")
    assert index.register("A$1", "что угодно", 999.0, "ifc_storey_elevation", "b.ifc")[0] == k1
    same, warns = index.register("X1", "C00_2_этаж", 3015.0, "ifc_storey_elevation", "b.ifc")
    assert same == k2 and not warns
    other, warns = index.register("X2", "Level 1", 10.0, "ifc_storey_elevation", "b.ifc")
    assert other == k1 and warns
    new, warns = index.register("X3", "C00_2_этаж", 3500.0, "ifc_storey_elevation", "b.ifc")
    assert new not in (k1, k2) and warns
    assert [s.elevation_mm for s in index.ordered()] == [0.0, 3000.0, 3500.0]


def test_grid_merge_warns_on_gap() -> None:
    axes = [
        RawAxis("1", "U", (0.0, 0.0), (0.0, 9000.0)),
        RawAxis("1", "U", (0.0, 9000.0), (5.0, 0.0)),
        RawAxis("1", "U", (30.0, 0.0), (30.0, 9000.0)),
        RawAxis("А", "V", (0.0, 0.0), (9000.0, 0.0)),
    ]
    rows, warnings = merge_axes(axes)
    assert [(r["tag"], r["dir"]) for r in rows] == [("1", "U"), ("А", "V")]
    assert len(warnings) == 1 and "30" in warnings[0]
    assert axis_dir((0.0, 0.0), (10.0, 9000.0)) == "U"
    assert axis_dir((0.0, 0.0), (9000.0, 10.0)) == "V"


@pytest.mark.parametrize(
    ("text", "elevations"),
    [
        ("План 3 этажа, на отм.+10.540", [10540.0]),
        ("План -2 этажа,\nна отм.-9.540 М1:100", [-9540.0]),
        ("План 6 этажа, на отм.+22,780", [22780.0]),
        ("План 1 этажа на отм. ±0.000", [0.0]),
        (
            "План типовых этажей 4, 5, 6 на отм. +14.620, +18.700, +22.780",
            [14620.0, 18700.0, 22780.0],
        ),
        ("Разрез 1-1 на отм. +3.000", []),
    ],
)
def test_parse_titles(text: str, elevations: list[float]) -> None:
    assert page_elevations(parse_titles(text)) == elevations


def test_match_storey() -> None:
    storeys = [
        {"storey_key": "a", "name": "1", "elevation_mm": 0.0},
        {"storey_key": "b", "name": "тех", "elevation_mm": 4460.0},
        {"storey_key": "c", "name": "x", "elevation_mm": 9000.0},
        {"storey_key": "d", "name": "y", "elevation_mm": 9250.0},
    ]
    exact = match_storey(0.0, storeys)
    assert exact.storey["storey_key"] == "a" and not exact.warnings
    near = match_storey(4260.0, storeys)
    assert near.storey["storey_key"] == "b" and near.delta_mm == 200.0 and near.warnings
    ambiguous = match_storey(9100.0, storeys)
    assert ambiguous.storey is None and len(ambiguous.candidates) == 2 and ambiguous.warnings
    assert match_storey(20000.0, storeys).storey is None


def test_canonical_json_and_jsonl_escapes() -> None:
    m = {"b": 1, "a": "кириллица", "manifest_sha256": "x", "generated_at": "t"}
    assert canonical_json({"b": 1, "a": "я"}) == '{"a":"я","b":1}'.encode()
    assert manifest_digest(m) == manifest_digest({**m, "generated_at": "другое"})
    line = _jsonl_line({"name": "a\u2028b"})
    assert len(line.splitlines()) == 1 and json.loads(line)["name"] == "a\u2028b"


def test_footprint_ring_of_walls_is_not_filled() -> None:
    from shapely.geometry import Polygon, box

    from model_package.footprint import _rings, hole_free

    walls = [box(0, 0, 10000, 200), box(0, 9800, 10000, 10000), box(0, 0, 200, 10000),
             box(9800, 0, 10000, 10000), box(4000, 4000, 4200, 4200)]  # fmt: skip
    rings = _rings(walls)
    area = sum(Polygon(r).area for r in rings)
    assert area == pytest.approx(4 * 10000 * 200 - 4 * 200 * 200 + 200 * 200, rel=1e-6)
    assert all(r[0] != r[-1] for r in rings)
    donut = box(0, 0, 100, 100).difference(box(10, 10, 20, 20)).difference(box(60, 60, 70, 90))
    pieces = hole_free(donut)
    assert all(not p.interiors for p in pieces)
    assert sum(p.area for p in pieces) == pytest.approx(donut.area)


def test_section_of_hollow_shaft_keeps_cavity() -> None:
    import numpy as np
    import trimesh

    from model_package.footprint import section_polygons

    outer = trimesh.creation.box(extents=(2000, 2000, 3000))
    inner = trimesh.creation.box(extents=(1600, 1600, 3000))
    inner.invert()
    shaft = trimesh.util.concatenate([outer, inner])
    polys = section_polygons(np.asarray(shaft.vertices), np.asarray(shaft.faces), 0.0)
    assert sum(p.area for p in polys) == pytest.approx(2000**2 - 1600**2, rel=1e-6)
