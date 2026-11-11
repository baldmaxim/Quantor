"""Отделка помещений в пилоте CAD (ADR-0042): тип помещения, шаблоны, назначение, ведомость."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_finishes import (
    CadFinishLayer,
    CadFinishTemplatePatch,
    CadFinishTemplateRead,
    CadFinishTemplateWrite,
)
from app.contracts.cad_room_types import (
    APARTMENT_ROOM_TYPES,
    MOP_ROOM_TYPES,
    ROOM_TYPE_VALUES,
    CadRoomType,
)
from app.contracts.cad_zones import CadZoneKind, CadZoneRead
from app.domain import Role
from app.main import create_app
from app.models import CadFinishTemplate, CadZone, Workspace
from app.services.cad_finishes import build_finish_sheet
from app.services.cad_zones import derive_room_type
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import (
    _ready_sheet,
    _url,
    walls_settings,
    walls_tools,
)
from tests.test_cad_qa import BROKEN_PDF, _upload, _upload_calibrated, cad_settings
from tests.test_cad_zones import RECT, _door, _room

__all__ = ["walls_tools"]

REVISION = uuid.uuid4()
NOW = datetime(2026, 11, 11, tzinfo=UTC)


# ------------------------------------------------------------------ справочник и вывод типа


def test_room_type_dictionary_has_one_source() -> None:
    assert set(ROOM_TYPE_VALUES) == MOP_ROOM_TYPES | APARTMENT_ROOM_TYPES
    assert not MOP_ROOM_TYPES & APARTMENT_ROOM_TYPES
    assert len(ROOM_TYPE_VALUES) == len(set(ROOM_TYPE_VALUES)) == 18
    assert set(get_args(CadRoomType)) == set(ROOM_TYPE_VALUES)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Тамбур-шлюз", "airlock"),
        ("Шлюз", "airlock"),
        ("Лифтовой холл", "lift_hall"),
        ("Тамбур", "vestibule"),
        ("Лестничная клетка", "stair"),
        ("Вестибюль", "entrance_hall"),
        ("Входная группа", "entrance_hall"),
        ("ПУИ", "pui"),
        ("Помещение уборочного инвентаря", "pui"),
        ("Мусорокамера", "garbage"),
        ("Электрощитовая", "tech"),
        ("Венткамера", "tech"),
        ("ИТП", "tech"),
        ("Насосная", "tech"),
        ("Техническое помещение", "tech"),
        ("Коридор", "corridor"),
        ("Холл", "corridor"),
        ("Кладовая МОП", "mop_other"),
        (None, "mop_other"),
        ("", "mop_other"),
    ],
)
def test_derive_room_type_for_mop(name: str | None, expected: str) -> None:
    assert derive_room_type("room_mop", name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Кухня-гостиная", "kitchen"),
        ("Столовая", "kitchen"),
        ("Санузел", "bath"),
        ("С/у", "bath"),
        ("Ванная", "bath"),
        ("Душевая", "bath"),
        ("Туалет", "wc"),
        ("Уборная", "wc"),
        ("WC", "wc"),
        ("Прихожая", "hall"),
        ("Коридор", "hall"),
        ("Холл", "hall"),
        ("Тамбур", "hall"),
        ("Гардеробная", "storage"),
        ("Кладовая", "storage"),
        ("Постирочная", "storage"),
        ("Хоз. помещение", "storage"),
        ("Балкон", "balcony"),
        ("Лоджия", "balcony"),
        ("Терраса", "balcony"),
        ("Жилая комната", "living"),
        ("Спальня", "living"),
        ("Гостиная", "living"),
        ("Кабинет", "living"),
        ("Детская", "living"),
        ("Помещение 5", "apt_other"),
        (None, "apt_other"),
    ],
)
def test_derive_room_type_for_apartment(name: str | None, expected: str) -> None:
    assert derive_room_type("room_apartment", name) == expected


def test_derived_type_ignores_case_and_door_has_none() -> None:
    assert derive_room_type("room_mop", "ТАМБУР-ШЛЮЗ") == "airlock"
    assert derive_room_type("door", "Тамбур") is None
    assert derive_room_type("parking_space", "Лифт") is None


# ------------------------------------------------------------------ контракты слоя и шаблона


def test_layer_contract_rules() -> None:
    assert CadFinishLayer(work="Грунтовка").coats == 1
    assert CadFinishLayer(work=" Окраска ", material="  ").material is None
    for bad in (
        {"work": ""},
        {"work": "x", "coats": 0},
        {"work": "x", "coats": 6},
        {"work": "x", "thickness_mm": 0},
        {"work": "x", "thickness_mm": 200.5},
        {"work": "x", "consumption": 0, "consumption_unit": "кг"},
        {"work": "x", "consumption": 1.0},  # расход без единицы
        {"work": "x", "consumption": 1.0, "consumption_unit": " "},
        {"work": "x", "consumption": 1.0, "consumption_unit": "кг", "consumption_per_mm": True},
        {"work": "x", "consumption_unit": "x" * 21, "consumption": 1.0},
        {"work": "x", "unknown": 1},
    ):
        with pytest.raises(ValidationError):
            CadFinishLayer.model_validate(bad)
    ok = CadFinishLayer(
        work="Стяжка",
        thickness_mm=40,
        consumption=1.8,
        consumption_unit="кг",
        consumption_per_mm=True,
    )
    assert ok.thickness_mm == 40


def test_template_contract_rules() -> None:
    layer = {"work": "Грунтовка"}
    with pytest.raises(ValidationError):
        CadFinishTemplateWrite.model_validate({"name": "x", "wall_layers": [layer] * 21})
    with pytest.raises(ValidationError):
        CadFinishTemplateWrite.model_validate({"name": "x", "wall_height_mm": 999})
    with pytest.raises(ValidationError):
        CadFinishTemplateWrite.model_validate({"name": "x", "wall_height_mm": 6001})
    with pytest.raises(ValidationError):
        CadFinishTemplateWrite.model_validate({"name": "x", "room_types": ["kitchen", "kitchen"]})
    with pytest.raises(ValidationError):
        CadFinishTemplateWrite.model_validate({"name": "x", "room_types": ["bedroom"]})
    with pytest.raises(ValidationError):
        CadFinishTemplateWrite.model_validate({"name": "", "room_types": []})
    # Правка: явный null очищает только высоту стен.
    assert CadFinishTemplatePatch.model_validate({"wall_height_mm": None}).model_fields_set == {
        "wall_height_mm"
    }
    for field in (
        "name",
        "room_types",
        "walls_include_reveals",
        "floor_layers",
        "wall_layers",
        "ceiling_layers",
    ):
        with pytest.raises(ValidationError):
            CadFinishTemplatePatch.model_validate({field: None})


def test_routes_are_in_openapi() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/cad"
    assert set(paths[f"{base}/finish-templates"]) == {"get", "post"}
    assert set(paths[f"{base}/finish-templates/{{template_id}}"]) == {"patch", "delete"}
    assert set(paths[f"{base}/zones/finish-assign"]) == {"post"}
    sheet = "/api/v1/projects/{project_id}/revisions/{revision_id}/cad/finishes"
    assert set(paths[sheet]) == {"get"}


# ------------------------------------------------------------------ ведомость: расчёт без базы


def _zone(
    *,
    kind: CadZoneKind = "room_apartment",
    room_type: CadRoomType | None = "living",
    area: float | None = 20.0,
    perimeter: float | None = 18.0,
    template_id: uuid.UUID | None = None,
    calibration_missing: bool = False,
    geometry_issue: str | None = None,
    name: str | None = "Комната",
) -> CadZoneRead:
    return CadZoneRead(
        id=uuid.uuid4(),
        revision_id=REVISION,
        page_index=0,
        kind=kind,
        apartment_no="0042" if kind == "room_apartment" else None,
        room_mark=None,
        name=name,
        points=[(0.1, 0.1), (0.4, 0.1), (0.4, 0.4)],
        door_height_mm=2100 if kind == "door" else None,
        parking_type="permanent" if kind == "parking_space" else None,
        room_type=room_type if kind in ("room_apartment", "room_mop") else None,
        room_type_source="derived" if kind in ("room_apartment", "room_mop") else None,
        finish_template_id=template_id,
        area_m2=area,
        perimeter_m=perimeter,
        width_m=None,
        calibration_missing=calibration_missing,
        geometry_issue=geometry_issue,
        created_at=NOW,
        updated_at=NOW,
    )


def _template(
    name: str = "Чистовая",
    *,
    room_types: list[str] | None = None,
    wall_height_mm: int | None = None,
    floor: list[dict[str, Any]] | None = None,
    walls: list[dict[str, Any]] | None = None,
    ceiling: list[dict[str, Any]] | None = None,
) -> CadFinishTemplateRead:
    return CadFinishTemplateRead.model_validate(
        {
            "id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "name": name,
            "room_types": room_types or [],
            "wall_height_mm": wall_height_mm,
            "walls_include_reveals": False,
            "floor_layers": floor or [],
            "wall_layers": walls or [],
            "ceiling_layers": ceiling or [],
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


SCREED = {
    "work": "Стяжка",
    "material": "Смесь М150",
    "thickness_mm": 40,
    "consumption": 2.0,
    "consumption_unit": "кг",
    "consumption_per_mm": True,
}
PRIMER = {
    "work": "Грунтовка",
    "material": "Бетоноконтакт",
    "coats": 2,
    "consumption": 0.2,
    "consumption_unit": "л",
}
PAINT = {
    "work": "Окраска",
    "material": "ВД-краска",
    "coats": 2,
    "consumption": 0.15,
    "consumption_unit": "кг",
}


def _sheet(
    zones: list[CadZoneRead], templates: list[CadFinishTemplateRead], height: int | None = 2800
) -> Any:
    return build_finish_sheet(
        revision_id=REVISION,
        page_index=0,
        zones=zones,
        templates=templates,
        levels_wall_height_mm=height,
    )


def test_sheet_quantities_for_a_four_by_five_room_with_height_from_levels() -> None:
    template = _template(room_types=["living"], floor=[SCREED], walls=[PRIMER], ceiling=[PAINT])
    sheet = _sheet([_zone()], [template])

    (zone,) = sheet.zones
    assert zone.template_id == template.id and zone.template_source == "by_type"
    assert zone.floor_area_m2 == zone.ceiling_area_m2 == 20.0
    # Высота уровней 2800 минус толщина слоёв пола шаблона 40.
    assert zone.wall_height_mm == pytest.approx(2760.0)
    assert zone.wall_height_source == "levels"
    assert zone.wall_area_m2 == pytest.approx(18.0 * 2.76)

    floor, walls, ceiling = zone.layers
    assert (floor.surface, floor.work, floor.area_m2) == ("floor", "Стяжка", 20.0)
    # Расход на мм: 20 м² x 2 кг/(м²·мм) x 40 мм x 1 слой.
    assert floor.material_qty == pytest.approx(1600.0) and floor.material_unit == "кг"
    # Два слоя грунтовки: 49.68 м² x 0.2 л x 2.
    assert walls.surface == "walls" and walls.coats == 2
    assert walls.material_qty == pytest.approx(18.0 * 2.76 * 0.2 * 2)
    assert walls.material_unit == "л"
    assert ceiling.surface == "ceiling" and ceiling.material_qty == pytest.approx(20 * 0.15 * 2)

    assert [(t.surface, t.work, t.zone_count) for t in sheet.totals] == [
        ("floor", "Стяжка", 1),
        ("walls", "Грунтовка", 1),
        ("ceiling", "Окраска", 1),
    ]
    (room_type,) = sheet.by_room_type
    assert room_type.room_type == "living" and room_type.zone_count == 1
    assert room_type.floor_area_m2 == 20.0
    assert room_type.wall_area_m2 == pytest.approx(18.0 * 2.76)
    # Привязки рёбер нет: стены - периметр x высота, предупреждение `edges_unlinked`.
    assert not zone.walls_breakdown.linked and zone.walls_breakdown.door_m is None
    codes = [warning.code for warning in sheet.warnings]
    assert codes == ["edges_unlinked"]
    assert sheet.warnings[0].zone_ids == [zone.zone_id]


def test_sheet_wall_height_from_template_wins_and_skips_floor_layers() -> None:
    template = _template(room_types=["living"], wall_height_mm=2500, floor=[SCREED], walls=[PRIMER])
    (zone,) = _sheet([_zone()], [template]).zones
    assert zone.wall_height_mm == 2500.0 and zone.wall_height_source == "template"
    assert zone.wall_area_m2 == pytest.approx(45.0)
    # Высота из шаблона не зависит от уровней: работает и без результата конструкций.
    (no_levels,) = _sheet([_zone()], [template], height=None).zones
    assert no_levels.wall_height_mm == 2500.0


def test_sheet_totals_sum_zones_by_work_material_and_unit() -> None:
    template = _template(room_types=["living", "kitchen"], walls=[PRIMER], ceiling=[PAINT])
    zones = [_zone(), _zone(room_type="kitchen", area=10.0, perimeter=13.0)]
    sheet = _sheet(zones, [template])
    walls = next(total for total in sheet.totals if total.surface == "walls")
    assert walls.zone_count == 2
    assert walls.area_m2 == pytest.approx((18.0 + 13.0) * 2.8)
    assert walls.material_qty == pytest.approx((18.0 + 13.0) * 2.8 * 0.2 * 2)
    ceiling = next(total for total in sheet.totals if total.surface == "ceiling")
    assert ceiling.area_m2 == 30.0 and ceiling.material_qty == pytest.approx(30 * 0.15 * 2)
    assert [(row.room_type, row.zone_count) for row in sheet.by_room_type] == [
        ("living", 1),
        ("kitchen", 1),
    ]


def test_sheet_explicit_template_wins_over_type() -> None:
    by_type = _template("По типу", room_types=["living"], ceiling=[PAINT])
    explicit = _template("Явный", ceiling=[{"work": "Шпаклёвка"}])
    sheet = _sheet([_zone(template_id=explicit.id)], [by_type, explicit])
    (zone,) = sheet.zones
    assert zone.template_id == explicit.id and zone.template_source == "explicit"
    assert [layer.work for layer in zone.layers] == ["Шпаклёвка"]


def test_sheet_without_calibration_has_null_not_zero() -> None:
    template = _template(room_types=["living"], floor=[SCREED], walls=[PRIMER], ceiling=[PAINT])
    zone_in = _zone(area=None, perimeter=None, calibration_missing=True)
    sheet = _sheet([zone_in], [template])
    (zone,) = sheet.zones
    assert zone.floor_area_m2 is None and zone.wall_area_m2 is None
    assert zone.wall_height_mm == pytest.approx(2760.0)
    assert all(layer.area_m2 is None and layer.material_qty is None for layer in zone.layers)
    # Единица остаётся: она свойство слоя, а не результата.
    assert zone.layers[0].material_unit == "кг"
    assert sheet.totals[0].area_m2 is None and sheet.totals[0].material_qty is None
    assert sheet.by_room_type[0].floor_area_m2 is None
    assert {w.code: w.zone_ids for w in sheet.warnings}["calibration_missing"] == [zone_in.id]


def test_sheet_geometry_issue_is_reported_separately() -> None:
    zone_in = _zone(area=None, perimeter=None, geometry_issue="self_intersection")
    sheet = _sheet([zone_in], [])
    codes = {warning.code: warning.zone_ids for warning in sheet.warnings}
    assert codes["geometry_issue"] == [zone_in.id] and "calibration_missing" not in codes


def test_sheet_without_levels_template_or_consumption() -> None:
    bare = _template(room_types=["living"], walls=[{"work": "Шпаклёвка"}, PRIMER])
    zone_in = _zone()
    other = _zone(room_type="kitchen")
    sheet = _sheet([zone_in, other], [bare], height=None)
    first, second = sheet.zones
    assert first.wall_height_mm is None and first.wall_height_source is None
    assert first.wall_area_m2 is None
    putty = first.layers[0]
    assert putty.work == "Шпаклёвка" and putty.material_qty is None and putty.material_unit is None
    assert second.template_id is None and second.template_source is None and second.layers == []
    warnings = {warning.code: warning.zone_ids for warning in sheet.warnings}
    assert warnings["wall_height_missing"] == [zone_in.id, other.id]
    assert warnings["no_template"] == [other.id]
    assert "edges_unlinked" in warnings


def test_sheet_wall_height_not_positive_after_floor_layers_is_missing() -> None:
    thick = {"work": "Стяжка", "thickness_mm": 200.0}
    template = _template(room_types=["living"], floor=[thick], walls=[PRIMER])
    (zone,) = _sheet([_zone()], [template], height=200).zones
    assert zone.wall_height_mm is None and zone.wall_area_m2 is None


def test_sheet_skips_doors_and_parking_and_warns_edges_unlinked_without_rooms() -> None:
    sheet = _sheet([_zone(kind="door", area=None, perimeter=None), _zone(kind="parking_space")], [])
    assert sheet.zones == [] and sheet.totals == [] and sheet.by_room_type == []
    assert [(w.code, w.zone_ids) for w in sheet.warnings] == [("edges_unlinked", [])]


# ------------------------------------------------------------------ тип помещения в API зон


async def _zones_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/zones"


async def test_zone_room_type_derived_manual_and_validated(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = await _zones_url(project_id)

        mop = (
            await api.post(
                url, json=_room(revision_id, kind="room_mop", apartment_no=None, name="Тамбур-шлюз")
            )
        ).json()
        assert (mop["room_type"], mop["room_type_source"]) == ("airlock", "derived")
        assert mop["finish_template_id"] is None
        flat = (await api.post(url, json=_room(revision_id, name="Кухня-ниша"))).json()
        assert (flat["room_type"], flat["room_type_source"]) == ("kitchen", "derived")
        stored = (await db_session.scalars(select(CadZone).where(CadZone.id == flat["id"]))).one()
        assert stored.room_type is None  # выведенный тип не записывается

        manual = await api.post(
            url,
            json=_room(revision_id, kind="room_mop", apartment_no=None, room_type="stair"),
        )
        assert manual.status_code == 201, manual.text
        assert (manual.json()["room_type"], manual.json()["room_type_source"]) == (
            "stair",
            "manual",
        )

        # Правка названия не трогает заданный тип; явный null возвращает выведенный.
        zone_url = f"/api/v1/cad/zones/{manual.json()['id']}"
        renamed = (await api.patch(zone_url, json={"name": "Лифтовой холл"})).json()
        assert (renamed["room_type"], renamed["room_type_source"]) == ("stair", "manual")
        cleared = (await api.patch(zone_url, json={"room_type": None})).json()
        assert (cleared["room_type"], cleared["room_type_source"]) == ("lift_hall", "derived")

        # Смена вида сбрасывает заданный тип прежнего вида.
        fixed = (await api.patch(zone_url, json={"room_type": "corridor"})).json()
        assert fixed["room_type_source"] == "manual"
        switched = await api.patch(zone_url, json={"kind": "room_apartment", "apartment_no": "7"})
        assert switched.status_code == 200, switched.text
        assert switched.json()["room_type_source"] == "derived"
        assert switched.json()["room_type"] == "hall"  # название «Лифтовой холл»

        door = (await api.post(url, json=_door(revision_id))).json()
        assert door["room_type"] is None and door["room_type_source"] is None


async def test_zone_room_type_must_match_the_kind(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        url = await _zones_url(project_id)
        bad: list[dict[str, Any]] = [
            _room(revision_id, room_type="lift_hall"),  # МОП-тип квартире
            _room(revision_id, kind="room_mop", apartment_no=None, room_type="kitchen"),
            _door(revision_id, room_type="corridor"),  # дверь без типа
            _door(revision_id, finish_template_id=str(uuid.uuid4())),
            _room(revision_id, room_type="bedroom"),  # нет в справочнике
            _room(revision_id, finish_template_id=str(uuid.uuid4())),  # шаблона нет
        ]
        for body in bad:
            response = await api.post(url, json=body)
            assert response.status_code == 422, (body, response.text)
        assert (await api.get(f"{url}?revision_id={revision_id}")).json() == []

        room = (await api.post(url, json=_room(revision_id))).json()
        for patch in ({"room_type": "stair"}, {"kind": "door", "room_type": "hall"}):
            response = await api.patch(f"/api/v1/cad/zones/{room['id']}", json=patch)
            assert response.status_code == 422, (patch, response.text)


# ------------------------------------------------------------------ шаблоны: CRUD и доступ


def _templates_url(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/cad/finish-templates"


def _body(name: str = "Черновая", **patch: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": name,
        "room_types": ["living", "hall"],
        "wall_height_mm": None,
        "floor_layers": [SCREED],
        "wall_layers": [PRIMER, {"work": "Штукатурка", "thickness_mm": 20}],
        "ceiling_layers": [PAINT],
    }
    body.update(patch)
    return body


async def test_template_crud(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, _revision = await _upload(api, BROKEN_PDF)
        url = _templates_url(project_id)
        assert (await api.get(url)).json() == []

        created = await api.post(url, json=_body())
        assert created.status_code == 201, created.text
        template = created.json()
        assert template["name"] == "Черновая" and template["project_id"] == project_id
        assert template["room_types"] == ["living", "hall"]
        assert [layer["work"] for layer in template["wall_layers"]] == ["Грунтовка", "Штукатурка"]
        assert template["wall_layers"][0]["coats"] == 2
        stored = (await db_session.scalars(select(CadFinishTemplate))).one()
        assert stored.created_by is not None and stored.wall_height_mm is None

        listed = (await api.get(url)).json()
        assert [row["id"] for row in listed] == [template["id"]]

        item = f"{url}/{template['id']}"
        patched = await api.patch(
            item, json={"name": "Черновая v2", "wall_height_mm": 2600, "ceiling_layers": []}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "Черновая v2"
        assert patched.json()["wall_height_mm"] == 2600
        assert patched.json()["ceiling_layers"] == []
        assert patched.json()["room_types"] == ["living", "hall"]  # не передано - не тронуто
        cleared = await api.patch(item, json={"wall_height_mm": None})
        assert cleared.json()["wall_height_mm"] is None

        # Откосы и основания слоёв стен (ADR-0042, п. 6): по умолчанию откосов нет, основания - все.
        assert template["walls_include_reveals"] is False
        assert all(layer["bases"] is None for layer in template["wall_layers"])
        staged = await api.patch(
            item,
            json={
                "walls_include_reveals": True,
                "wall_layers": [{"work": "Обеспыливание", "bases": ["monolith"]}],
            },
        )
        assert staged.status_code == 200, staged.text
        assert staged.json()["walls_include_reveals"] is True
        assert staged.json()["wall_layers"][0]["bases"] == ["monolith"]
        stored_after = (await db_session.scalars(select(CadFinishTemplate))).one()
        await db_session.refresh(stored_after)
        assert stored_after.walls_include_reveals is True
        bad_bases = await api.patch(
            item, json={"floor_layers": [{"work": "Стяжка", "bases": ["gkl"]}]}
        )
        assert bad_bases.status_code == 422
        assert (await api.patch(item, json={"walls_include_reveals": None})).status_code == 422

        for bad in (
            {"name": None},
            {"room_types": None},
            {"wall_height_mm": 500},
            {"wall_layers": [{"work": ""}]},
        ):
            assert (await api.patch(item, json=bad)).status_code == 422, bad

        assert (await api.delete(item)).status_code == 204
        assert (await api.delete(item)).status_code == 404
        assert (await api.patch(item, json={"name": "x"})).status_code == 404
        assert (await api.get(url)).json() == []


async def test_template_name_and_room_types_are_unique_in_project(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, _revision = await _upload(api, BROKEN_PDF)
        other_project, _other = await _upload(api, b"%PDF-1.7\n" + b"1" * 512, "Другой.pdf")
        url = _templates_url(project_id)
        first = (await api.post(url, json=_body("А", room_types=["living", "hall"]))).json()

        same_name = await api.post(url, json=_body("А", room_types=["kitchen"]))
        assert same_name.status_code == 409
        assert same_name.json()["detail"]["code"] == "CAD_FINISH_TEMPLATE_NAME_TAKEN"

        overlap = await api.post(url, json=_body("Б", room_types=["kitchen", "hall"]))
        assert overlap.status_code == 409
        detail = overlap.json()["detail"]
        assert detail["code"] == "CAD_FINISH_ROOM_TYPE_TAKEN"
        assert detail["issue"] == {"room_type": "hall", "template_id": first["id"]}

        second = await api.post(url, json=_body("Б", room_types=["kitchen"]))
        assert second.status_code == 201, second.text
        # Правка: тип, занятый другим шаблоном, нельзя; свои типы и своё название - можно.
        item = f"{url}/{second.json()['id']}"
        clash = await api.patch(item, json={"room_types": ["kitchen", "living"]})
        assert clash.status_code == 409
        assert clash.json()["detail"]["code"] == "CAD_FINISH_ROOM_TYPE_TAKEN"
        assert (await api.patch(item, json={"name": "А"})).status_code == 409
        assert (
            await api.patch(item, json={"name": "Б", "room_types": ["kitchen", "wc"]})
        ).status_code == 200
        # Освободить тип можно удалением; в другом проекте те же название и типы допустимы.
        assert (await api.delete(f"{url}/{first['id']}")).status_code == 204
        assert (await api.patch(item, json={"room_types": ["living"]})).status_code == 200
        copy = await api.post(_templates_url(other_project), json=_body("Б", room_types=["living"]))
        assert copy.status_code == 201, copy.text


async def test_template_routes_are_closed_by_flag_role_and_workspace(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
    tmp_path: Path,
) -> None:
    settings = cad_settings(tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        template = (await api.post(_templates_url(project_id), json=_body())).json()
        zone = (await api.post(await _zones_url(project_id), json=_room(revision_id))).json()
    url = _templates_url(project_id)
    item = f"{url}/{template['id']}"
    assign = f"/api/v1/projects/{project_id}/cad/zones/finish-assign"
    sheet = f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/finishes?page_index=0"
    assign_body = {"zone_ids": [zone["id"]], "template_id": template["id"]}
    calls: list[tuple[str, str, dict[str, Any] | None]] = [
        ("get", url, None),
        ("post", url, _body("Новый", room_types=[])),
        ("patch", item, {"name": "Другое"}),
        ("delete", item, None),
        ("post", assign, assign_body),
        ("get", sheet, None),
    ]

    async with build_api(make_context(), settings=cad_settings(tmp_path, flag=False)) as closed:
        for method, path, body in calls:
            response = await closed.request(method, path, json=body)
            assert response.status_code == 403, path
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", path

    viewer = make_context(Role.VIEWER, platform_admin=False)
    async with build_api(viewer, settings=settings) as reader:
        assert (await reader.get(url)).status_code == 200
        assert (await reader.get(sheet)).status_code == 200
        for method, path, body in calls:
            if method == "get":
                continue
            assert (await reader.request(method, path, json=body)).status_code == 403, path

    stranger = make_context(platform_admin=False, workspace_id=second_workspace.id)
    async with build_api(stranger, settings=settings) as foreign:
        for method, path, body in calls:
            assert (await foreign.request(method, path, json=body)).status_code == 404, path

    stored = (await db_session.scalars(select(CadFinishTemplate))).one()
    assert stored.name == "Черновая"


# ------------------------------------------------------------------ назначение зонам


async def test_assign_template_to_zones_and_delete_clears_it(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        other_project, other_revision = await _upload(api, b"%PDF-1.7\n" + b"1" * 512, "Другой.pdf")
        zones_url = await _zones_url(project_id)
        template = (await api.post(_templates_url(project_id), json=_body())).json()
        foreign_template = (
            await api.post(_templates_url(other_project), json=_body("Чужой"))
        ).json()
        room = (await api.post(zones_url, json=_room(revision_id))).json()
        mop = (
            await api.post(zones_url, json=_room(revision_id, kind="room_mop", apartment_no=None))
        ).json()
        door = (await api.post(zones_url, json=_door(revision_id))).json()
        parking = (
            await api.post(
                zones_url,
                json={
                    "revision_id": revision_id,
                    "page_index": 0,
                    "kind": "parking_space",
                    "parking_type": "permanent",
                    "points": RECT,
                },
            )
        ).json()
        foreign_zone = (
            await api.post(await _zones_url(other_project), json=_room(other_revision))
        ).json()
        missing = str(uuid.uuid4())

        assign = f"/api/v1/projects/{project_id}/cad/zones/finish-assign"
        response = await api.post(
            assign,
            json={
                "zone_ids": [
                    room["id"],
                    mop["id"],
                    door["id"],
                    parking["id"],
                    foreign_zone["id"],
                    missing,
                    room["id"],
                ],
                "template_id": template["id"],
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["assigned"] == 2 and result["skipped_count"] == 4
        reasons = {row["zone_id"]: row["reason"] for row in result["skipped"]}
        assert reasons == {
            door["id"]: "door",
            parking["id"]: "parking_space",
            foreign_zone["id"]: "not_found",
            missing: "not_found",
        }
        listed = {
            zone["id"]: zone
            for zone in (await api.get(f"{zones_url}?revision_id={revision_id}")).json()
        }
        assert listed[room["id"]]["finish_template_id"] == template["id"]
        assert listed[mop["id"]]["finish_template_id"] == template["id"]
        assert listed[door["id"]]["finish_template_id"] is None
        stored_foreign = await db_session.get(CadZone, uuid.UUID(foreign_zone["id"]))
        assert stored_foreign is not None
        await db_session.refresh(stored_foreign)
        assert stored_foreign.finish_template_id is None

        # Шаблон другого проекта и несуществующий не назначаются.
        for template_id in (foreign_template["id"], missing):
            bad = await api.post(
                assign, json={"zone_ids": [room["id"]], "template_id": template_id}
            )
            assert bad.status_code == 404, bad.text
        # Валидация тела.
        for body in (
            {"zone_ids": [], "template_id": None},
            {"zone_ids": [str(uuid.uuid4()) for _ in range(501)], "template_id": None},
            {"zone_ids": [room["id"]]},
        ):
            assert (await api.post(assign, json=body)).status_code == 422, body

        # null снимает назначение.
        cleared = await api.post(assign, json={"zone_ids": [mop["id"]], "template_id": None})
        assert cleared.json()["assigned"] == 1
        # Через зону явное назначение другого проекта не ставится.
        via_zone = await api.patch(
            f"/api/v1/cad/zones/{room['id']}", json={"finish_template_id": foreign_template["id"]}
        )
        assert via_zone.status_code == 422
        same = await api.patch(
            f"/api/v1/cad/zones/{mop['id']}", json={"finish_template_id": template["id"]}
        )
        assert same.status_code == 200 and same.json()["finish_template_id"] == template["id"]
        unset = await api.patch(f"/api/v1/cad/zones/{mop['id']}", json={"finish_template_id": None})
        assert unset.json()["finish_template_id"] is None

        # Удаление шаблона снимает назначение, зона остаётся.
        assert (
            await api.delete(f"{_templates_url(project_id)}/{template['id']}")
        ).status_code == 204
        after = (await api.get(f"{zones_url}?revision_id={revision_id}")).json()
        assert len(after) == 4
        assert all(zone["finish_template_id"] is None for zone in after)


# ------------------------------------------------------------------ ведомость по API


def _sheet_url(project_id: str, revision_id: str, page: int = 0) -> str:
    return f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/finishes?page_index={page}"


async def test_sheet_without_calibration_and_without_walls_is_null_with_warnings(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload(api, BROKEN_PDF)
        template = (
            await api.post(_templates_url(project_id), json=_body(room_types=["living"]))
        ).json()
        zone = (
            await api.post(await _zones_url(project_id), json=_room(revision_id, name="Спальня"))
        ).json()
        assert zone["calibration_missing"] is True

        response = await api.get(_sheet_url(project_id, revision_id))
        assert response.status_code == 200, response.text
        sheet = response.json()
        (row,) = sheet["zones"]
        assert row["template_id"] == template["id"] and row["template_source"] == "by_type"
        assert row["floor_area_m2"] is None and row["wall_area_m2"] is None
        assert row["wall_height_mm"] is None and row["wall_height_source"] is None
        assert all(layer["material_qty"] is None for layer in row["layers"])
        codes = {warning["code"]: warning["zone_ids"] for warning in sheet["warnings"]}
        assert codes["calibration_missing"] == [zone["id"]]
        assert codes["wall_height_missing"] == [zone["id"]]
        assert "no_template" not in codes and "edges_unlinked" in codes

        assert (await api.get(_sheet_url(project_id, revision_id, page=3))).json()["zones"] == []
        assert (await api.get(_sheet_url(project_id, str(uuid.uuid4())))).status_code == 404
        assert (await api.get(_sheet_url(str(uuid.uuid4()), revision_id))).status_code == 404
        assert (
            await api.get(f"/api/v1/projects/{project_id}/revisions/{revision_id}/cad/finishes")
        ).status_code == 422


async def test_sheet_uses_sheet_levels_and_template_height(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        template = (
            await api.post(_templates_url(project_id), json=_body(room_types=["living"]))
        ).json()
        zone = (
            await api.post(await _zones_url(project_id), json=_room(revision_id, name="Спальня"))
        ).json()
        assert zone["area_m2"] is not None and zone["perimeter_m"] is not None

        # Заглушка cad_walls: этаж 3000, плита 200 -> стены 2800; слои пола шаблона 40 мм.
        sheet = (await api.get(_sheet_url(project_id, revision_id))).json()
        (row,) = sheet["zones"]
        assert row["wall_height_source"] == "levels"
        assert row["wall_height_mm"] == pytest.approx(2760.0)
        assert row["wall_area_m2"] == pytest.approx(zone["perimeter_m"] * 2.76)
        floor, wall, *_rest = row["layers"]
        assert floor["material_qty"] == pytest.approx(zone["area_m2"] * 2.0 * 40)
        assert wall["work"] == "Грунтовка"
        assert wall["material_qty"] == pytest.approx(row["wall_area_m2"] * 0.2 * 2)
        codes = {warning["code"] for warning in sheet["warnings"]}
        # Заглушка cad_walls без перемычек и кадра: привязки рёбер нет.
        assert codes == {"edges_unlinked"}

        # Уровни листа от человека: этаж 3500 -> стены 3300 - 40.
        levels = await api.put(_url(project_id, job_id, "levels"), json={"floor_height_mm": 3500})
        assert levels.status_code == 200, levels.text
        raised = (await api.get(_sheet_url(project_id, revision_id))).json()["zones"][0]
        assert raised["wall_height_mm"] == pytest.approx(3260.0)

        # Высота шаблона главнее уровней.
        patched = await api.patch(
            f"{_templates_url(project_id)}/{template['id']}", json={"wall_height_mm": 2500}
        )
        assert patched.status_code == 200
        fixed = (await api.get(_sheet_url(project_id, revision_id))).json()
        assert fixed["zones"][0]["wall_height_source"] == "template"
        assert fixed["zones"][0]["wall_height_mm"] == 2500
        assert fixed["zones"][0]["wall_area_m2"] == pytest.approx(zone["perimeter_m"] * 2.5)
        assert [(t["surface"], t["work"]) for t in fixed["totals"]] == [
            ("floor", "Стяжка"),
            ("walls", "Грунтовка"),
            ("walls", "Штукатурка"),
            ("ceiling", "Окраска"),
        ]
        assert fixed["by_room_type"][0]["room_type"] == "living"


# Лист без зон-помещений не ломает ведомость: двери в ней не выводятся.
async def test_sheet_hides_doors(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient], tmp_path: Path
) -> None:
    async with build_api(make_context(), settings=cad_settings(tmp_path)) as api:
        project_id, revision_id = await _upload_calibrated(api, db_session, BROKEN_PDF)
        await api.post(await _zones_url(project_id), json=_door(revision_id))
        sheet = (await api.get(_sheet_url(project_id, revision_id))).json()
        assert sheet["zones"] == [] and sheet["totals"] == []
        assert [w["code"] for w in sheet["warnings"]] == ["edges_unlinked"]
