"""Синтетический проект PlanSwift для тестов.

Создан с нуля по наблюдаемой структуре формата; ни одного фрагмента реальных проектов. Воспроизводит
то, на чём ломается наивный разбор: объявление UTF-8 при байтах cp1251, усечённые имена каталогов,
вычитаемая секция без `PageGUID`, секция счёта с несколькими точками, заглушки `(-1, -1)`,
точка за краем растра, пустая секция, файл с DOCTYPE.

Растр — TIFF 4 бита PackBits, как у листов PlanSwift, собранный здесь же: на нём нарисована ровно
принятая геометрия, поэтому проверка совмещения обязана найти пик в нулевом сдвиге. Бинарные файлы
в git не хранятся.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from itertools import pairwise
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
    duplicate: str = "{00000000-0000-0000-0000-000000000012}"


GUIDS = Guids()

LINE = [(100.0, 100.0), (500.5, 100.0), (900.0, 300.0)]
SLAB = [(200.0, 200.0), (1800.0, 200.0), (1800.0, 800.0), (200.0, 800.0)]
HOLE = [(400.0, 400.0), (600.0, 400.0), (600.0, 600.0), (400.0, 600.0)]
DRAWN: list[tuple[list[tuple[float, float]], bool]] = [(LINE, False), (SLAB, True), (HOLE, True)]


def tiff_bytes(width: int, height: int, *, big_endian: bool = False) -> bytes:
    order = ">" if big_endian else "<"
    header = (b"MM" if big_endian else b"II") + struct.pack(order + "HI", 42, 8)
    entries = [
        struct.pack(order + "HHI", 256, 3, 1) + struct.pack(order + "H", width) + b"\0\0",
        struct.pack(order + "HHI", 257, 4, 1) + struct.pack(order + "I", height),
    ]
    return header + struct.pack(order + "H", len(entries)) + b"".join(entries) + b"\0\0\0\0"


def packbits(data: bytes) -> bytes:
    """Кодировщик PackBits: повторы от трёх байт — серией, остальное — литералами."""
    out = bytearray()
    index = 0
    while index < len(data):
        run = 1
        while index + run < len(data) and run < 128 and data[index + run] == data[index]:
            run += 1
        if run >= 3:
            out += bytes((257 - run,)) + data[index : index + 1]
            index += run
            continue
        start = index
        while index < len(data) and index - start < 128:
            if index + 2 < len(data) and data[index] == data[index + 1] == data[index + 2]:
                break
            index += 1
        out += bytes((index - start - 1,)) + data[start:index]
    return bytes(out)


def tiff_image(
    width: int,
    height: int,
    luminance: bytes | bytearray,
    *,
    bits: int = 4,
    compress: bool = True,
    rows_per_strip: int | None = None,
) -> bytes:
    """Одноканальный TIFF BlackIsZero из яркостей 0..255 (одна на пиксель)."""
    maximum = (1 << bits) - 1
    to_level = bytes(round(value * maximum / 255) for value in range(256))
    high = bytes(round(value * maximum / 255) << 4 for value in range(256)) if bits == 4 else b""
    rows: list[bytes] = []
    for y in range(height):
        line = bytes(luminance[y * width : (y + 1) * width])
        if bits == 8:
            rows.append(line)
        else:
            left = line[0::2].translate(high)
            right = line[1::2].translate(to_level).ljust(len(left), bytes((0,)))
            rows.append(bytes(map(int.__or__, left, right)))
    per_strip = rows_per_strip or height
    strips = [b"".join(rows[start : start + per_strip]) for start in range(0, height, per_strip)]
    if compress:
        strips = [
            b"".join(packbits(row) for row in rows[start : start + per_strip])
            for start in range(0, height, per_strip)
        ]
    count = len(strips)
    tags = 10
    ifd_offset = 8
    arrays_offset = ifd_offset + 2 + tags * 12 + 4
    offsets_start = arrays_offset + 8 * count
    data_offsets: list[int] = []
    cursor = offsets_start
    for strip in strips:
        data_offsets.append(cursor)
        cursor += len(strip)

    def entry(tag: int, kind: int, items: int, value: int) -> bytes:
        body = struct.pack("<H", value) + b"\0\0" if kind == 3 else struct.pack("<I", value)
        return struct.pack("<HHI", tag, kind, items) + body

    offsets_value = data_offsets[0] if count == 1 else arrays_offset
    counts_value = len(strips[0]) if count == 1 else arrays_offset + 4 * count
    ifd = b"".join(
        [
            entry(256, 4, 1, width),
            entry(257, 4, 1, height),
            entry(258, 3, 1, bits),
            entry(259, 3, 1, 32773 if compress else 1),
            entry(262, 3, 1, 1),
            entry(273, 4, count, offsets_value),
            entry(277, 3, 1, 1),
            entry(278, 4, 1, per_strip),
            entry(279, 4, count, counts_value),
            entry(284, 3, 1, 1),
        ]
    )
    arrays = b""
    if count > 1:
        arrays = struct.pack(f"<{count}I", *data_offsets) + struct.pack(
            f"<{count}I", *(len(strip) for strip in strips)
        )
    arrays = arrays.ljust(8 * count, b"\0")
    header = b"II" + struct.pack("<HI", 42, ifd_offset)
    return header + struct.pack("<H", tags) + ifd + b"\0\0\0\0" + arrays + b"".join(strips)


def draw_segments(
    luminance: bytearray, width: int, height: int, points: list[tuple[float, float]], closed: bool
) -> None:
    """Чёрные отрезки толщиной 3 px: то, что на настоящем листе рисует чертёжник."""
    ring = [*points, points[0]] if closed else points
    for (x0, y0), (x1, y1) in pairwise(ring):
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) or 1
        for index in range(steps + 1):
            t = index / steps
            cx, cy = round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if 0 <= cx + dx < width and 0 <= cy + dy < height:
                        luminance[(cy + dy) * width + cx + dx] = 0


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
    luminance = bytearray(b"\xff" * (WIDTH * HEIGHT))
    for shape, closed in DRAWN:
        draw_segments(luminance, WIDTH, HEIGHT, shape, closed)
    (page_dir / f"{IMAGE_GUID}.tiff").write_bytes(tiff_image(WIDTH, HEIGHT, luminance))

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
        walls / "Section2",
        _section(
            "Linear Section",
            GUIDS.duplicate,
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
