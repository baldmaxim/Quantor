"""Координационный файл выпуска базы: сетка осей по группам, этажи, IFC (без базы данных)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.contracts.tender_exchange import ObjectBaseAxis
from app.services.tender_base_coordination import (
    CoordinationFloor,
    build_coordination,
    coordination_ifc,
    ifc_guid,
)

REV = "0f0e0d0c-0b0a-4908-8706-050403020100"


def _axes(vertical: dict[str, int], horizontal: dict[str, int]) -> list[ObjectBaseAxis]:
    return [ObjectBaseAxis(label=k, orient="vertical", pos_mm=v) for k, v in vertical.items()] + [
        ObjectBaseAxis(label=k, orient="horizontal", pos_mm=v) for k, v in horizontal.items()
    ]


def _floor(page: int, z: int, axes: list[ObjectBaseAxis], **kw: object) -> CoordinationFloor:
    base: dict[str, object] = {
        "view_key": f"{REV}:{page}:1",
        "label": f"Этаж {page}",
        "group_key": "k9:s3",
        "group_label": "Корпус 9, секция 3",
        "base_z_mm": z,
        "floor_height_mm": 3000,
        "offset_mm": (0.0, 0.0),
        "rotation_deg": 0.0,
        "alignment": "axes",
    }
    base.update(kw)
    return CoordinationFloor(axes=axes, **base)  # type: ignore[arg-type]


def test_этажи_совмещённые_сдвигом_дают_одну_сетку_без_расхождений() -> None:
    # Лист второго этажа нарисован на 5 м правее и на 2 м выше: «Здание» сдвинуло его обратно.
    first = _floor(
        10, 0, _axes({"1": 1000, "2": 7000}, {"А": 500, "Б": 6500}), alignment="reference"
    )
    second = _floor(
        11,
        3000,
        _axes({"1": 6000, "2": 12000}, {"А": 2500, "Б": 8500}),
        offset_mm=(-5000.0, -2000.0),
    )
    result = build_coordination([second, first])
    (group,) = result.groups
    by_label = {a.label: a for a in group.axes}
    assert by_label["1"].point_mm[0] == 1000 and by_label["2"].point_mm[0] == 7000
    assert by_label["А"].point_mm[1] == 500 and by_label["Б"].point_mm[1] == 6500
    assert all(a.spread_mm == 0 and a.views == 2 for a in group.axes)
    assert [a.label for a in group.axes] == ["1", "2", "А", "Б"]
    assert [s.base_z_mm for s in group.storeys] == [0, 3000]
    assert result.doubts == []


def test_поворот_вида_переводит_ось_в_систему_здания() -> None:
    # Вид повёрнут на 90° против часовой: вертикальная ось x = 1000 становится горизонтальной y =
    # 1000.
    floor = _floor(10, 0, _axes({"1": 1000}, {}), rotation_deg=90.0, offset_mm=(100.0, 0.0))
    (axis,) = build_coordination([floor]).groups[0].axes
    assert axis.point_mm == [100, 1000]
    assert axis.direction == pytest.approx([-1.0, 0.0], abs=1e-6)


def test_разошедшаяся_ось_попадает_в_сомнения_а_медиана_держит_сетку() -> None:
    floors = [
        _floor(10, 0, _axes({"1": 1000}, {"А": 0}), alignment="reference"),
        _floor(11, 3000, _axes({"1": 1000}, {"А": 0})),
        _floor(12, 6000, _axes({"1": 1120}, {"А": 0})),
    ]
    result = build_coordination(floors)
    axis = next(a for a in result.groups[0].axes if a.label == "1")
    assert axis.point_mm[0] == 1000 and axis.spread_mm == 120
    assert any("ось 1 расходится" in d for d in result.doubts)


def test_несовмещённый_вид_не_входит_в_сетку_но_этаж_остаётся() -> None:
    floors = [
        _floor(10, 0, _axes({"1": 1000}, {"А": 0}), alignment="reference"),
        _floor(11, 3000, _axes({"1": 99999}, {"А": 99999}), alignment="none"),
    ]
    result = build_coordination(floors)
    axis = next(a for a in result.groups[0].axes if a.label == "1")
    assert axis.views == 1 and axis.point_mm[0] == 1000
    assert [s.base_z_mm for s in result.groups[0].storeys] == [0, 3000]
    assert any("не совмещён" in d for d in result.doubts)


def test_группы_корпусов_раздельно_и_этаж_на_одной_отметке_один() -> None:
    a = _floor(10, 0, _axes({"1": 0}, {"А": 0}), group_key="k1", group_label="Корпус 1")
    b = _floor(11, 0, _axes({"1": 0}, {"А": 0}), group_key="k2", group_label="Корпус 2")
    c = _floor(12, 0, _axes({"1": 0}, {"А": 0}), group_key="k1", group_label="Корпус 1")
    result = build_coordination([a, b, c])
    assert [g.group_label for g in result.groups] == ["Корпус 1", "Корпус 2"]
    (storey,) = result.groups[0].storeys
    assert storey.view_keys == [a.view_key, c.view_key]


def test_guid_ifc_как_у_ifcopenshell() -> None:
    assert ifc_guid(uuid.UUID(int=0)) == "0" * 22
    assert ifc_guid(uuid.UUID(int=2**128 - 1)) == "3" + "$" * 21
    assert len(ifc_guid(uuid.uuid4())) == 22


def test_ifc_этажи_сетка_и_ссылки() -> None:
    floors = [
        _floor(10, -3000, _axes({"1": 0, "2": 6000}, {"А": 0, "Б": 5000}), alignment="reference"),
        _floor(11, 0, _axes({"1": 0, "2": 6000}, {"А": 0, "Б": 5000})),
    ]
    coordination = build_coordination(floors)
    data = coordination_ifc(
        coordination,
        project_name="341. Капельский",
        release_id=uuid.UUID(int=7),
        moment=datetime(2026, 11, 18, tzinfo=UTC),
    ).decode("ascii")
    assert data.startswith("ISO-10303-21;") and data.rstrip().endswith("END-ISO-10303-21;")
    assert data.count("IFCBUILDINGSTOREY(") == 2 and data.count("IFCGRID(") == 2
    assert data.count("IFCGRIDAXIS(") == 8
    # Кириллица - кодом X2 (UTF-16): «Участок» = 0423 0447 0430 0441 0442 043E 043A
    assert r"\X2\04230447043004410442043E043A\X0\'" in data
    defined = {int(m) for m in re.findall(r"^#(\d+)=", data, flags=re.M)}
    used = {int(m) for m in re.findall(r"#(\d+)", data)}
    assert used <= defined
    # тот же выпуск - те же GlobalId
    again = coordination_ifc(
        coordination,
        project_name="341. Капельский",
        release_id=uuid.UUID(int=7),
        moment=datetime(2026, 11, 18, tzinfo=UTC),
    ).decode("ascii")
    assert again == data


def test_лист_повёрнутый_на_90_сводится_в_ту_же_ось() -> None:
    # Эталон: ось 1 вертикальная x = 1000. Лист второго этажа нарисован повёрнутым: там ось 1
    # горизонтальная y = 500, «Здание» ставит его поворотом на 90° и сдвигом (1500, 0).
    first = _floor(10, 0, _axes({"1": 1000}, {}), alignment="reference")
    turned = _floor(11, 3000, _axes({}, {"1": 500}), rotation_deg=90.0, offset_mm=(1500.0, 0.0))
    result = build_coordination([turned, first])
    (axis,) = result.groups[0].axes
    assert axis.label == "1" and axis.orient == "vertical"
    assert axis.views == 2 and axis.spread_mm == 0 and axis.point_mm[0] == 1000
    assert result.doubts == []


def test_этаж_без_отметки_не_сливается_с_нулевым() -> None:
    known = _floor(10, 0, _axes({"1": 0, "2": 6000}, {"А": 0, "Б": 5000}), alignment="reference")
    unknown = _floor(11, 0, _axes({"1": 0, "2": 6000}, {"А": 0, "Б": 5000}), elevation_known=False)
    coordination = build_coordination([known, unknown])
    storeys = coordination.groups[0].storeys
    assert [(s.base_z_mm, s.elevation_known) for s in storeys] == [(0, True), (0, False)]
    assert any("отметка не найдена" in d for d in coordination.doubts)
    ifc = coordination_ifc(
        coordination,
        project_name="X",
        release_id=uuid.UUID(int=3),
        moment=datetime(2026, 11, 18, tzinfo=UTC),
    ).decode("ascii")
    assert ifc.count("IFCBUILDINGSTOREY(") == 1
