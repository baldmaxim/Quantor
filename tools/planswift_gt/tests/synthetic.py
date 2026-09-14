"""Синтетический проект PlanSwift для тестов.

Создан с нуля по наблюдаемой структуре формата; ни одного фрагмента реальных проектов. Воспроизводит
то, на чём ломается наивный разбор: объявление UTF-8 при байтах cp1251, усечённые имена каталогов,
вычитаемая секция без `PageGUID`, секция счёта с несколькими точками, заглушки `(-1, -1)`,
точка за краем растра, пустая секция, файл с DOCTYPE.

Растр — минимальный TIFF, собранный здесь же: бинарные файлы в git не хранятся.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

PAGE_GUID = "{11111111-2222-3333-4444-555555555555}"
IMAGE_GUID = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"
WIDTH = 2000
HEIGHT = 1000


@dataclass(frozen=True, slots=True)
class Guids:
    linear: str = "{00000000-0000-0000-0000-00000000000A}"
    area: str = "{00000000-0000-0000-0000-00000000000B}"
    hole: str = "{00000000-0000-0000-0000-00000000000C}"
    count: str = "{00000000-0000-0000-0000-00000000000D}"
    placeholder_area: str = "{00000000-0000-0000-0000-00000000000E}"
    orphan_hole: str = "{00000000-0000-0000-0000-00000000000F}"
    empty_count: str = "{00000000-0000-0000-0000-000000000010}"
    outside: str = "{00000000-0000-0000-0000-000000000011}"


GUIDS = Guids()


def tiff_bytes(width: int, height: int, *, big_endian: bool = False) -> bytes:
    order = ">" if big_endian else "<"
    header = (b"MM" if big_endian else b"II") + struct.pack(order + "HI", 42, 8)
    entries = [
        struct.pack(order + "HHI", 256, 3, 1) + struct.pack(order + "H", width) + b"\0\0",
        struct.pack(order + "HHI", 257, 4, 1) + struct.pack(order + "I", height),
    ]
    return header + struct.pack(order + "H", len(entries)) + b"".join(entries) + b"\0\0\0\0"


def _props(values: dict[str, str]) -> str:
    return "".join(
        f'<Property Class="Text" GUID="" Name="{name}">{value}</Property>'
        for name, value in values.items()
    )


def _item(item_class: str, guid: str, name: str, props: dict[str, str], extra: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Item Class="{item_class}" Name="{name}" GUID="{guid}"><Properties>'
        f"{_props({'Name': name, 'Type': item_class, **props})}{extra}</Properties></Item>"
    )


def _digitizer(points: list[tuple[str, str, str]]) -> str:
    inner = "".join(f'<Point X="{x}" Y="{y}" PointType="{kind}"/>' for x, y, kind in points)
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<Points>{inner}</Points>'
    return xml.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write(path: Path, text: str, *, encoding: str = "cp1251") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "Data.xml").write_bytes(text.encode(encoding))


def _section(
    item_class: str, guid: str, points: list[tuple[str, str, str]], *, page: str | None
) -> str:
    props = {"DigitizerData": _digitizer(points)}
    if page is not None:
        props = {"PageGUID": page, **props}
    return _item(item_class, guid, "Section", props)


def build(root: Path) -> Path:
    """Собирает проект и возвращает каталог, как его оставляет распаковка архива."""
    project = root / "Синтетика кладка"
    _write(project, _item("Item", "{00000000-0000-0000-0000-000000000001}", "Синтетика кладка", {}))

    # Каталог листа усечён, семантическое имя — в XML.
    page_dir = project / "Pages" / "Лист 1 — пла"
    _write(
        page_dir,
        _item(
            "Page",
            PAGE_GUID,
            "Лист 1 — план типового этажа",
            {"ScaleX": "102,381983542659", "ScaleY": "102,342626577818", "Scale Units": "M"},
            extra=f'<Property Class="Large Image" GUID="{IMAGE_GUID}" Name="Image"/>',
        ),
    )
    (page_dir / f"{IMAGE_GUID}.tiff").write_bytes(tiff_bytes(WIDTH, HEIGHT))

    takeoff = project / "Takeoff"
    # Папка в UTF-8: смешанные кодировки в одном проекте встречаются.
    _write(
        takeoff / "Кладка",
        _item("Folder", "{00000000-0000-0000-0000-000000000002}", "Кладка", {}),
        encoding="utf-8",
    )

    walls = takeoff / "Кладка" / "Стены [толщина 2"
    _write(
        walls, _item("Linear", "{00000000-0000-0000-0000-000000000003}", "Стены [толщина 250]", {})
    )
    _write(
        walls / "Section",
        _section(
            "Linear Section",
            GUIDS.linear,
            [("100", "100", "Normal"), ("500.5", "100", "ArcChild"), ("900", "300", "Arc")],
            page=PAGE_GUID,
        ),
    )
    _write(
        walls / "Section1",
        _section(
            "Linear Section",
            GUIDS.outside,
            [("100", "100", "Normal"), ("2100", "100", "Normal")],
            page=PAGE_GUID,
        ),
    )

    slab = takeoff / "Плита перекрытия"
    _write(slab, _item("Area", "{00000000-0000-0000-0000-000000000004}", "Плита перекрытия", {}))
    square = [
        ("200", "200", "Normal"),
        ("1800", "200", "Normal"),
        ("1800", "800", "Normal"),
        ("200", "800", "Normal"),
    ]
    _write(slab / "Section", _section("Area Section", GUIDS.area, square, page=PAGE_GUID))
    _write(
        slab / "Section" / "Subtract Section",
        _section(
            "Area Subtract Section",
            GUIDS.hole,
            [
                ("400", "400", "Normal"),
                ("600", "400", "Normal"),
                ("600", "600", "Normal"),
                ("400", "600", "Normal"),
            ],
            page=None,
        ),
    )
    placeholder = [("-1", "-1", "Normal")] * 4
    _write(
        slab / "Section1",
        _section("Area Section", GUIDS.placeholder_area, placeholder, page=PAGE_GUID),
    )
    _write(
        slab / "Section1" / "Subtract Section",
        _section(
            "Area Subtract Section",
            GUIDS.orphan_hole,
            [("400", "400", "Normal"), ("600", "400", "Normal"), ("600", "600", "Normal")],
            page=None,
        ),
    )

    doors = takeoff / "Двери"
    _write(doors, _item("Count", "{00000000-0000-0000-0000-000000000005}", "Двери", {}))
    _write(
        doors / "Section",
        _section(
            "Count Section",
            GUIDS.count,
            [("300", "900", "Normal"), ("700", "900", "Normal"), ("1100", "900", "Normal")],
            page=PAGE_GUID,
        ),
    )
    _write(doors / "Section1", _section("Count Section", GUIDS.empty_count, [], page=PAGE_GUID))

    hostile = takeoff / "Чужое"
    hostile.mkdir(parents=True)
    (hostile / "Data.xml").write_bytes(
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Item Class="Folder" GUID="{9}"/>'
    )
    return root
