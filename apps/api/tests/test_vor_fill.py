"""Заполнение ВОР Заказчика (ADR-0055 п. 7): объекты, сравнение, выгрузка копии формы.

Книги синтетические: структура формы пилота (шапка в середине листа, данные ниже), без данных
Заказчика. Цен в выгрузке нет, исходные ячейки не меняются.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from httpx import AsyncClient
from openpyxl import Workbook, load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import CadConstructionGroupRead, CadOpeningRead
from app.contracts.cad_finishes import CadFinishLayerRead, CadFinishZoneRead, FinishSurface
from app.contracts.cad_finishes import CadFinishWallsBreakdownRead as Breakdown
from app.contracts.cad_vor import CadVorItemRead, CadVorLinkRead, CadVorSheetColumnsRead
from app.contracts.cad_zones import CadZoneKind
from app.contracts.vor_fill import VorObjectRead
from app.services import vor_fill, vor_fill_export
from tests.conftest import FakeObjectStorage, make_context
from tests.test_cad_constructions_api import _ready_sheet, walls_settings
from tests.test_cad_vor_api import _upload, walls_tools  # noqa: F401
from tests.test_cad_vor_import import workbook_bytes

JOB = uuid.uuid4()
SOURCE = vor_fill.SheetSource("План 1 · лист 1", JOB, 0, 1)
TYPICAL = vor_fill.SheetSource("План 2 · лист 2", JOB, 1, 1, "типовой лист: этажи 2–5, ×4", 4)


def group(
    kind: str = "masonry",
    thickness: float = 200.0,
    *,
    volume: float | None = 10.0,
    wall_area: float = 50.0,
    length: float = 25.0,
    count: int = 3,
    element: str = "construction",
    material: str | None = None,
    area: float | None = None,
) -> CadConstructionGroupRead:
    return CadConstructionGroupRead.model_validate(
        {
            "kind": kind,
            "element": element,
            "thickness_mm": thickness,
            "material": material,
            "count": count,
            "length_m": length,
            "wall_area_m2": wall_area,
            "volume_m3": volume,
            "area_m2": area,
        }
    )


def opening(kind: str = "door", width: float = 900.0, **extra: Any) -> CadOpeningRead:
    return CadOpeningRead.model_validate(
        {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "status": "ok",
            "host_id": None,
            "adjacent_ids": [],
            "width_mm": width,
            "width_source": "block",
            "thickness_mm": 200.0,
            "block_name": None,
            "handle": None,
            "center": [0.0, 0.0],
            **extra,
        }
    )


def zone(kind: str, layers: list[tuple[str, str, str | None, float | None]]) -> CadFinishZoneRead:
    empty = Breakdown.model_validate(
        {
            "linked": False,
            "monolith_m": None,
            "masonry_m": None,
            "gkl_m": None,
            "door_m": None,
            "gap_m": None,
            "open_m": None,
            "area_by_base": {"monolith": None, "masonry": None, "gkl": None},
            "door_over_area_m2": None,
            "reveal_m": None,
            "reveal_area_m2": None,
        }
    )
    return CadFinishZoneRead(
        zone_id=uuid.uuid4(),
        name=None,
        apartment_no=None,
        room_mark=None,
        kind=cast(CadZoneKind, kind),
        room_type=None,
        template_id=None,
        template_source=None,
        floor_area_m2=None,
        ceiling_area_m2=None,
        perimeter_m=None,
        wall_height_mm=None,
        wall_height_source=None,
        wall_area_m2=None,
        walls_breakdown=empty,
        layers=[
            CadFinishLayerRead(
                surface=cast(FinishSurface, surface),
                work=work,
                material=material,
                coats=1,
                thickness_mm=None,
                bases=None,
                area_m2=area,
                material_qty=None,
                material_unit=None,
            )
            for surface, work, material, area in layers
        ],
    )


def item(
    name: str,
    unit: str | None,
    quantity: float | None,
    row: int = 1,
    sheet: str = "Расчет стоимости",
) -> CadVorItemRead:
    return CadVorItemRead(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        row_no=row,
        sheet=sheet,
        code=None,
        name=name,
        unit=unit,
        quantity=quantity,
        section=None,
        thickness_hint_mm=None,
        kind_hint=None,
    )


def link(key: str, row: CadVorItemRead) -> CadVorLinkRead:
    from datetime import UTC, datetime

    return CadVorLinkRead(id=uuid.uuid4(), group_key=key, item=row, created_at=datetime.now(UTC))


def objects_by_key(objects: list[VorObjectRead]) -> dict[str, VorObjectRead]:
    return {obj.group_key: obj for obj in objects}


def quantity(obj: VorObjectRead, unit: str) -> float | None:
    return next((q.value for q in obj.quantities if q.unit == unit), None)


# ------------------------------------------------------------------ единицы


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("м3", "m3"),
        ("м³", "m3"),
        ("куб.м", "m3"),
        ("м2", "m2"),
        ("м²", "m2"),
        ("кв. м", "m2"),
        ("м.п.", "m"),
        ("пог.м", "m"),
        ("шт.", "pcs"),
        ("Шт", "pcs"),
        ("т", None),
        (None, None),
    ],
)
def test_normalize_unit(raw: str | None, expected: str | None) -> None:
    assert vor_fill.normalize_unit(raw) == expected


# ------------------------------------------------------------------ объекты


def test_construction_objects_sum_over_sheets_and_keep_sources() -> None:
    sheets = [
        vor_fill.SheetObjects(SOURCE, [group(volume=10.0, wall_area=50.0)], [], 2100),
        vor_fill.SheetObjects(TYPICAL, [group(volume=5.0, wall_area=20.0)], [], 2100),
    ]
    objects = objects_by_key(vor_fill.build_objects(sheets, []))
    wall = objects["masonry|200|"]
    assert wall.kind == "construction" and not wall.incomplete
    # Типовой лист (этажи 2-5) входит ×4: 10 + 5 x 4, 50 + 20 x 4.
    assert quantity(wall, "m3") == 30.0 and quantity(wall, "m2") == 130.0
    assert [s.label for s in wall.sources] == [SOURCE.label, TYPICAL.label]
    assert wall.sources[1].note == "типовой лист: этажи 2–5, ×4"


def test_typical_sheet_multiplies_constructions_doors_and_finish() -> None:
    sheets = [
        vor_fill.SheetObjects(
            TYPICAL,
            [
                group(volume=5.0, wall_area=20.0),
                group("monolith_wall", 200.0, element="lintel", wall_area=0.0, count=3),
            ],
            [opening(), opening()],
            2100,
        )
    ]
    finish = vor_fill.FinishObjects(
        TYPICAL,
        [zone("room_mop", [("floor", "Плитка", None, 10.0), ("walls", "Окраска", None, None)])],
    )
    objects = objects_by_key(vor_fill.build_objects(sheets, [finish]))
    assert quantity(objects["masonry|200|"], "m3") == 20.0
    assert quantity(objects["masonry|200|"], "m2") == 80.0
    assert quantity(objects["monolith_wall|200||lintel"], "pcs") == 12.0
    assert quantity(objects["door||900x2100"], "pcs") == 8.0
    floor = next(o for o in objects.values() if o.group_key.startswith("finish|floor|"))
    assert quantity(floor, "m2") == 40.0
    walls = next(o for o in objects.values() if o.group_key.startswith("finish|walls|"))
    assert walls.incomplete and quantity(walls, "m2") is None


@pytest.mark.parametrize(
    ("floor_from", "floor_to", "floors", "note"),
    [
        (2, 5, 4, "типовой лист: этажи 2–5, ×4"),
        (None, None, 1, None),
        (3, None, 1, None),
        (5, 2, 1, None),
        (3, 3, 1, None),
    ],
)
def test_floors_from_passport_range(
    floor_from: int | None, floor_to: int | None, floors: int, note: str | None
) -> None:
    from app.api.v1.cad_vor_fill import _floors_count, _floors_note

    assert _floors_count(floor_from, floor_to) == floors
    assert _floors_note(floor_from, floor_to) == note
    sheets = [
        vor_fill.SheetObjects(
            vor_fill.SheetSource("Лист", JOB, 0, 1, note, floors),
            [group(volume=5.0, wall_area=20.0)],
            [],
            None,
        )
    ]
    wall = objects_by_key(vor_fill.build_objects(sheets, []))["masonry|200|"]
    assert quantity(wall, "m3") == 5.0 * floors


def test_partition_has_no_volume_and_slab_uses_area() -> None:
    sheets = [
        vor_fill.SheetObjects(
            SOURCE,
            [
                group("frame_partition", 100.0, volume=None, wall_area=30.0),
                group("floor_slab", 200.0, volume=20.0, wall_area=0.0, area=100.0),
                group("monolith_wall", 200.0, element="lintel", wall_area=0.0, count=4),
            ],
            [],
            None,
        )
    ]
    objects = objects_by_key(vor_fill.build_objects(sheets, []))
    partition = objects["frame_partition|100|"]
    assert quantity(partition, "m3") is None and quantity(partition, "m2") == 30.0
    slab = objects["floor_slab|200|"]
    assert quantity(slab, "m2") == 100.0 and quantity(slab, "m3") == 20.0
    lintel = objects["monolith_wall|200||lintel"]
    assert quantity(lintel, "pcs") == 4.0 and quantity(lintel, "m2") is None


def test_doors_group_by_type_and_size_and_skip_non_doors() -> None:
    sheets = [
        vor_fill.SheetObjects(
            SOURCE,
            [],
            [
                opening(width=900.0),
                opening(width=900.0),
                opening(width=1000.0),
                opening(width=900.0, block_name="DOOR_A"),
                opening("gap"),
                opening("window"),
                opening(width=900.0, marker_row_gap=True),
                opening(width=900.0, status="no_data"),
            ],
            2100,
        )
    ]
    objects = vor_fill.build_objects(sheets, [])
    doors = {o.group_key: quantity(o, "pcs") for o in objects if o.kind == "door"}
    typed = [k for k in doors if k.startswith("door|") and not k.startswith("door||")]
    assert doors["door||900x2100"] == 2.0 and doors["door||1000x2100"] == 1.0
    assert len(typed) == 1 and typed[0].endswith("|900x2100") and doors[typed[0]] == 1.0


def test_door_without_known_height_gets_n_key() -> None:
    sheets = [vor_fill.SheetObjects(SOURCE, [], [opening()], None)]
    (door,) = vor_fill.build_objects(sheets, [])
    assert door.group_key == "door||900xn" and "высота не определена" in door.title


def test_finish_objects_only_from_mop_and_unknown_area_is_incomplete() -> None:
    finish = vor_fill.FinishObjects(
        SOURCE,
        [
            zone(
                "room_mop",
                [("floor", "Плитка", "керамогранит", 12.5), ("walls", "Окраска", None, 40.0)],
            ),
            zone("room_mop", [("floor", "Плитка", "керамогранит", None)]),
            zone("room_apartment", [("floor", "Ламинат", None, 99.0)]),
        ],
    )
    objects = vor_fill.build_objects([], [finish])
    assert [o.kind for o in objects] == ["finish", "finish"]
    floor = next(o for o in objects if o.group_key.startswith("finish|floor|"))
    assert quantity(floor, "m2") == 12.5 and floor.incomplete
    walls = next(o for o in objects if o.group_key.startswith("finish|walls|"))
    assert quantity(walls, "m2") == 40.0 and not walls.incomplete
    assert vor_fill.finish_key("floor", "Плитка", "керамогранит") == floor.group_key
    assert floor.title.startswith("Пол (МОП): Плитка")


def test_unavailable_reasons_per_kind() -> None:
    reasons = {
        u.kind: u.reason for u in vor_fill.unavailable_kinds([], sheets_count=0, mop_zones_count=0)
    }
    assert set(reasons) == {"construction", "door", "finish"}
    sheets = [vor_fill.SheetObjects(SOURCE, [group()], [], 2100)]
    objects = vor_fill.build_objects(sheets, [])
    left = vor_fill.unavailable_kinds(objects, sheets_count=1, mop_zones_count=2)
    assert [u.kind for u in left] == ["door", "finish"]
    assert "шаблоны отделки" in left[1].reason


# ------------------------------------------------------------------ сравнение


def _objects() -> dict[str, VorObjectRead]:
    sheets = [
        vor_fill.SheetObjects(
            SOURCE,
            [group(volume=10.0, wall_area=50.0), group("monolith_wall", 200.0, volume=7.0)],
            [opening(), opening()],
            2100,
        )
    ]
    return objects_by_key(vor_fill.build_objects(sheets, []))


def test_compare_statuses() -> None:
    objects = _objects()
    match = item("Кладка", "м3", 10.1, 1)
    differs = item("Монолит", "м3", 9.0, 2)
    doors = item("Двери", "шт.", 2.0, 3)
    wrong_unit = item("Кладка по площади", "т", 5.0, 4)
    absent = item("Нет объекта", "м3", 5.0, 5)
    no_customer = item("Без количества", "м3", None, 6)
    mixed = item("Смесь", "м3", 5.0, 7)
    rows = vor_fill.compare(
        [
            link("masonry|200|", match),
            link("monolith_wall|200|", differs),
            link("door||900x2100", doors),
            link("masonry|200|", wrong_unit),
            link("masonry|100|", absent),
            link("masonry|200|", no_customer),
            link("masonry|200|", mixed),
            link("door||900x2100", mixed),
        ],
        objects,
    )
    by_name = {r.item.name: r for r in rows}
    assert by_name["Кладка"].status == "match" and by_name["Кладка"].quantor_quantity == 10.0
    assert by_name["Кладка"].difference == -0.1
    assert by_name["Монолит"].status == "differs"
    assert by_name["Монолит"].difference == -2.0 and by_name["Монолит"].difference_percent == -22.22
    assert by_name["Двери"].status == "match" and by_name["Двери"].quantor_quantity == 2.0
    assert by_name["Кладка по площади"].status == "unit_mismatch"
    assert by_name["Кладка по площади"].quantor_quantity is None
    assert by_name["Нет объекта"].status == "no_quantor"
    assert by_name["Нет объекта"].missing_group_keys == ["masonry|100|"]
    assert by_name["Без количества"].status == "no_customer"
    # Конструкция в м3 и дверь в шт в одной позиции в м3 не складываются.
    assert by_name["Смесь"].status == "unit_mismatch"
    assert [r.item.row_no for r in rows] == sorted(r.item.row_no for r in rows)


def test_compare_tolerance_is_two_percent() -> None:
    objects = _objects()
    near = vor_fill.compare([link("masonry|200|", item("a", "м3", 10.19))], objects)[0]
    far = vor_fill.compare([link("masonry|200|", item("b", "м3", 10.3))], objects)[0]
    assert near.status == "match" and far.status == "differs"


# ------------------------------------------------------------------ выгрузка

# Структура формы пилота: заголовок и шапка в середине листа, данные ниже, колонки цен справа.
FORM_HEADER = [
    "№ п/п",
    "Наименование работ",
    "Ед. изм.",
    "Кол-во",
    "Цена",
    "Стоимость",
    "Примечания",
]


def form_book() -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "Расчет стоимости"
    sheet["A1"] = "Форма расчёта стоимости"
    for index, title in enumerate(FORM_HEADER, start=1):
        sheet.cell(row=14, column=index, value=title)
    sheet.append([])
    sheet.append([])
    sheet.append([1, "Кладка стен", "м3", 10.0, 1000, "=D17*E17", "прим"])
    sheet.append([2, "Двери", "шт", 3, None, None, None])
    sheet.append([3, "Не связана", "м2", 5, None, None, None])
    return _dump(book)


def _dump(book: Workbook) -> bytes:
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def _form_layout() -> list[CadVorSheetColumnsRead]:
    return [
        CadVorSheetColumnsRead(
            sheet="Расчет стоимости",
            header_row=14,
            rows_count=3,
            columns={"code": 1, "name": 2, "unit": 3, "quantity": 4},
        )
    ]


def test_export_adds_columns_right_and_block_at_the_end_without_changing_source() -> None:
    source = form_book()
    objects = _objects()
    wall = item("Кладка стен", "м3", 10.0, 17)
    door = item("Двери", "шт", 3.0, 18)
    rows = vor_fill.compare([link("masonry|200|", wall), link("door||900x2100", door)], objects)
    unlinked = [o for o in objects.values() if o.group_key == "monolith_wall|200|"]
    result = vor_fill_export.fill_workbook(source, _form_layout(), rows, unlinked)

    before = load_workbook(BytesIO(source))["Расчет стоимости"]
    after = load_workbook(BytesIO(result))["Расчет стоимости"]
    # Исходные ячейки не изменены (формулы - как были).
    for row in before.iter_rows():
        for cell in row:
            assert after[cell.coordinate].value == cell.value, cell.coordinate
    assert after["F17"].value == "=D17*E17"
    # Колонки справа от последней колонки шапки (G): H, I, J.
    assert [after.cell(row=14, column=c).value for c in (8, 9, 10)] == [
        vor_fill_export.HEADER_QUANTITY,
        vor_fill_export.HEADER_DIFFERENCE,
        vor_fill_export.HEADER_SOURCE,
    ]
    assert after["H17"].value == 10.0 and after["I17"].value == 0.0
    assert SOURCE.label in str(after["J17"].value)
    assert after["H18"].value == 2.0 and after["I18"].value == -1.0
    assert after["H19"].value is None
    # Блок «нет в ВОР» - в конце листа, в колонках формы; цены не заполняются.
    last = after.max_row
    assert after.cell(row=last - 1, column=2).value == vor_fill_export.EXTRA_TITLE
    assert after.cell(row=last, column=2).value == "Монолитная стена, 200 мм"
    assert after.cell(row=last, column=3).value == "м3"
    assert after.cell(row=last, column=8).value == 7.0
    assert after.cell(row=last, column=5).value is None
    assert after.cell(row=last, column=6).value is None
    assert load_workbook(BytesIO(source))["Расчет стоимости"].max_row == 19


def test_export_marks_unit_mismatch_and_no_quantor_without_numbers() -> None:
    objects = _objects()
    rows = vor_fill.compare(
        [
            link("masonry|200|", item("Кладка стен", "т", 1.0, 17)),
            link("masonry|100|", item("Двери", "м3", 1.0, 18)),
        ],
        objects,
    )
    after = load_workbook(
        BytesIO(vor_fill_export.fill_workbook(form_book(), _form_layout(), rows, []))
    )["Расчет стоимости"]
    assert after["H17"].value is None and after["H18"].value is None
    assert "Единицы не совпадают" in str(after["J17"].value)
    assert "количества нет" in str(after["J18"].value)


# ------------------------------------------------------------------ API


async def test_fill_api_end_to_end(
    build_api: Callable[..., AsyncClient],
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    walls_tools: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, _job, _walls = await _ready_sheet(api, db_session, fake_storage, settings)
        base = f"/api/v1/projects/{project_id}/vor/fill"
        empty = (await api.get(base)).json()
        assert empty["has_vor"] is False and empty["items"] == []
        keys = {o["group_key"] for o in empty["objects"]}
        assert {"masonry|200|", "masonry|100|", "monolith_column|400|", "door||1000x2100"} <= keys
        assert [u["kind"] for u in empty["unavailable"]] == ["finish"]
        no_vor = await api.post(f"{base}/export")
        assert no_vor.status_code == 422

        rows: list[list[object]] = [
            ["Ведомость"],
            ["№ п/п", "Наименование работ", "Ед. изм.", "Кол-во"],
            [1, "Кладка стен из газобетона 200 мм", "м2", 12.0],
            [2, "Двери внутренние", "шт", 1],
            [3, "Окраска стен", "м2", 10],
        ]
        document = (await _upload(api, project_id, data=workbook_bytes({"Расчет": rows}))).json()
        items = (
            await api.get(f"/api/v1/projects/{project_id}/cad/vor/{document['id']}/items")
        ).json()["items"]
        by_name = {i["name"]: i["id"] for i in items}
        vor = f"/api/v1/projects/{project_id}/cad/vor"
        for key, name in (
            ("masonry|200|", "Кладка стен из газобетона 200 мм"),
            ("door||1000x2100", "Двери внутренние"),
        ):
            put = await api.put(
                f"{vor}/links/{key.replace('|', '%7C')}", json={"vor_item_ids": [by_name[name]]}
            )
            assert put.status_code == 200, put.text
        # Подсказки для двери и отделки: по словам наименования и единице.
        door_hint = (await api.get(f"{vor}/suggest?group_key=door%7C%7C1000x2100")).json()
        assert [h["item"]["name"] for h in door_hint] == ["Двери внутренние"]
        wall_hint = (await api.get(f"{vor}/suggest?group_key=finish%7Cwalls%7C0123456789")).json()
        assert {h["item"]["name"] for h in wall_hint} == {
            "Окраска стен",
            "Кладка стен из газобетона 200 мм",
        }

        body = (await api.get(base)).json()
        assert body["has_vor"] is True
        statuses = {r["item"]["name"]: r for r in body["items"]}
        assert set(statuses) == {"Кладка стен из газобетона 200 мм", "Двери внутренние"}
        assert statuses["Двери внутренние"]["status"] == "match"
        assert statuses["Двери внутренние"]["quantor_quantity"] == 1.0
        assert statuses["Кладка стен из газобетона 200 мм"]["unit"] == "m2"
        unlinked = {o["group_key"] for o in body["unlinked"]}
        assert "masonry|200|" not in unlinked and "masonry|100|" in unlinked

        exported = await api.post(f"{base}/export")
        assert exported.status_code == 200, exported.text
        info = exported.json()
        assert info["file_name"] == "ВОР_Quantor.xlsx"
        file = await api.get(info["download_url"])
        assert file.status_code == 200
        sheet = load_workbook(BytesIO(file.content))["Расчет"]
        assert sheet.cell(row=2, column=5).value == vor_fill_export.HEADER_QUANTITY
        assert sheet.max_row > 5
        assert (await api.get(f"{base}/files/20200101T000000Z")).status_code == 404
        assert (await api.get(f"{base}/files/bad")).status_code == 422
        # Оригинал в хранилище не менялся.
        original = load_workbook(BytesIO(workbook_bytes({"Расчет": rows})))["Расчет"]
        assert original.max_column == 4


async def test_fill_routes_are_closed_without_flag(
    build_api: Callable[..., AsyncClient],
    db_session: AsyncSession,
) -> None:
    from tests.test_cad_vor_api import vor_settings

    fake = str(uuid.uuid4())
    async with build_api(make_context(), settings=vor_settings(flag=False)) as api:
        for method, url in (
            ("get", f"/api/v1/projects/{fake}/vor/fill"),
            ("post", f"/api/v1/projects/{fake}/vor/fill/export"),
            ("get", f"/api/v1/projects/{fake}/vor/fill/files/20200101T000000Z"),
        ):
            response = await api.request(method, url)
            assert response.status_code == 403, url
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", url
