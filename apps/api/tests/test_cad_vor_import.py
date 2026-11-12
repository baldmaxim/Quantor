"""Разбор XLSX с ВОР Заказчика (ADR-0038 п. 5): заголовок, разделы, числа, подсказки, лимиты.

Все книги синтетические, собираются здесь же openpyxl; реальных ВОР в репозитории нет.
"""

from __future__ import annotations

import io
import time
import zipfile
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.services import cad_vor_import as vor
from app.services.cad_vor_import import VorParseError

HEADER = ["№ п/п", "Наименование работ", "Ед. изм.", "Кол-во"]


def workbook_bytes(sheets: dict[str, list[list[object]]], *, hidden: tuple[str, ...] = ()) -> bytes:
    """Книга Excel из строк листов; `hidden` - имена скрытых листов."""
    book = Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
        if title in hidden:
            sheet.sheet_state = "hidden"
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def parse(
    sheets: dict[str, list[list[object]]], *, hidden: tuple[str, ...] = ()
) -> vor.ParsedWorkbook:
    return vor.parse_workbook(io.BytesIO(workbook_bytes(sheets, hidden=hidden)))


# ------------------------------------------------------------------ заголовок, разделы, числа


def test_header_sections_numbers_and_row_numbers() -> None:
    parsed = parse(
        {
            "ВОР": [
                ["Ведомость объёмов работ"],
                [],
                HEADER,
                [1, 2, 3, 4],
                ["Раздел 1. Кладка"],
                [1, "Кладка перегородок из газобетона 100 мм", "м2", "1 234,5"],
                [],
                ["1.1", "Кладка стен из кирпича\nтолщиной 120 мм", "м2", 56.0],
                ["Раздел 2. Монолит"],
                [2, "Устройство монолитных стен", "м3", "12,25"],
                [3, "Позиция без количества", "шт", None],
                [None, "Подпись без цифр"],
                [None, None, None, 99],
            ]
        }
    )
    assert len(parsed.sheets) == 1
    sheet = parsed.sheets[0]
    assert sheet.header_row == 3
    assert sheet.columns == {"code": 1, "name": 2, "unit": 3, "quantity": 4}
    # Строка нумерации колонок, пустая строка, итог без наименования пропущены; «Подпись без цифр»
    # без количества и единицы - заголовок раздела, а не позиция.
    assert [(i.row_no, i.code, i.quantity, i.section) for i in sheet.items] == [
        (6, "1", Decimal("1234.5"), "Раздел 1. Кладка"),
        (8, "1.1", Decimal("56"), "Раздел 1. Кладка"),
        (10, "2", Decimal("12.25"), "Раздел 2. Монолит"),
        (11, "3", None, "Раздел 2. Монолит"),
    ]
    assert sheet.items[1].name == "Кладка стен из кирпича толщиной 120 мм"
    assert sheet.items[0].thickness_hint_mm == 100 and sheet.items[0].kind_hint == "masonry"
    assert sheet.items[2].kind_hint == "monolith" and sheet.items[2].thickness_hint_mm is None


def test_hidden_sheets_are_skipped_and_all_visible_sheets_are_read() -> None:
    row = [1, "Кладка перегородок 100 мм", "м2", 10]
    parsed = parse(
        {
            "Один": [HEADER, row],
            "Скрытый": [HEADER, row],
            "Два": [["x"], HEADER, row],
            "Пустой": [["-"]],
        },
        hidden=("Скрытый",),
    )
    assert [s.sheet for s in parsed.sheets] == ["Один", "Два"]
    assert [s.header_row for s in parsed.sheets] == [1, 2]
    assert parsed.items_count == 2


def test_header_without_unit_and_code_columns_is_enough() -> None:
    parsed = parse({"ВОР": [["Наименование", "Объём"], ["Монолитные колонны", 5]]})
    assert parsed.sheets[0].columns == {"name": 1, "quantity": 2}
    assert parsed.sheets[0].items[0].unit is None


@pytest.mark.parametrize(
    "sheets",
    [
        {"ВОР": [["Что-то", "Другое"], ["a", "b"]]},
        {"ВОР": [[None] * 3] * 40 + [HEADER, [1, "Кладка", "м2", 1]]},
        {"ВОР": [HEADER]},
    ],
)
def test_no_header_or_no_rows_is_a_clear_error(sheets: dict[str, list[list[object]]]) -> None:
    with pytest.raises(VorParseError) as error:
        parse(sheets)
    assert str(error.value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12, Decimal("12")),
        (0.1 + 0.2, Decimal("0.3")),
        ("1 234,56", Decimal("1234.56")),
        ("1 000", Decimal("1000")),
        ("-5,5", Decimal("-5.5")),
        ("12 м2", None),
        ("", None),
        (None, None),
        (True, None),
        (float("nan"), None),
        (10**16, None),
    ],
)
def test_parse_number(value: object, expected: Decimal | None) -> None:
    assert vor.parse_number(value) == expected


# ------------------------------------------------------------------ подсказки


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Кладка перегородок из газобетона 100 мм", 100),
        ("Кладка толщиной 120", 120),
        ("Перегородки толщ. 80 из ПГП", 80),
        ("Стена δ=200, бетон B30", 200),
        ("Кладка блоками 200х300х600 мм", None),
        ("Кладка блоками 600 х 300 х 200 мм, толщина 300 мм", 300),
        ("Стена толщиной 1200 мм", None),
        ("Окна ПВХ", None),
    ],
)
def test_thickness_hint(text: str, expected: int | None) -> None:
    assert vor.thickness_hint(vor.normalize_text(text)) == expected


@pytest.mark.parametrize(
    "text",
    ["1" * 32_000, "1х" * 16_000, "1х " * 11_000, "1 " * 16_000, "1х" + " " * 32_000],
)
def test_thickness_hint_is_not_redos_prone(text: str) -> None:
    started = time.perf_counter()
    vor.thickness_hint(vor.normalize_text(text))
    vor.thickness_hint(text)
    assert time.perf_counter() - started < 0.5


def test_thickness_hint_looks_only_at_name_head() -> None:
    tail = " " * vor.THICKNESS_HINT_MAX_CHARS + "толщиной 100"
    assert vor.thickness_hint("Кладка" + tail) is None
    assert vor.thickness_hint("Кладка толщиной 100") == 100


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Кладка перегородок из газобетона", "masonry"),
        ("Кладка из ПГП", "masonry"),
        ("Кирпич керамический", "masonry"),
        ("Устройство монолитных стен", "monolith"),
        ("Бетон стен и пилонов B30", "monolith"),
        ("Ж/Б колонны", "monolith"),
        ("Железобетонные пилоны", "monolith"),
        ("Газобетонные перегородки", "masonry"),
        ("Кладка перегородок и монолитные пилоны", None),
        ("Окна ПВХ", None),
    ],
)
def test_kind_hint(text: str, expected: str | None) -> None:
    assert vor.kind_hint(vor.normalize_text(text)) == expected


# ------------------------------------------------------------------ лимиты и защита


def test_row_limit_is_enforced_on_a_real_workbook() -> None:
    rows: list[list[object]] = [HEADER] + [
        [i, f"Позиция {i}", "шт", i] for i in range(vor.MAX_ROWS + 1)
    ]
    with pytest.raises(VorParseError, match="больше"):
        vor.parse_workbook(io.BytesIO(workbook_bytes({"ВОР": rows})))
    # Ровно предельное число строк принимается.
    ok = vor.parse_workbook(io.BytesIO(workbook_bytes({"ВОР": rows[: vor.MAX_ROWS + 1]})))
    assert ok.items_count == vor.MAX_ROWS


def test_zip_bomb_is_rejected_before_opening() -> None:
    buffer = io.BytesIO()
    chunk = b"\x00" * (1024 * 1024)
    with (
        zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive,
        archive.open("xl/worksheets/sheet1.xml", "w", force_zip64=True) as member,
    ):
        for _ in range(vor.MAX_UNCOMPRESSED_BYTES // len(chunk) + 1):
            member.write(chunk)
    assert buffer.tell() < vor.MAX_FILE_BYTES, "архив-бомба должен быть маленьким"
    buffer.seek(0)
    with pytest.raises(VorParseError, match="после распаковки"):
        vor.parse_workbook(buffer)


def test_not_a_zip_and_broken_archive_are_clear_errors() -> None:
    with pytest.raises(VorParseError):
        vor.parse_workbook(io.BytesIO("это не книга".encode()))
    broken = workbook_bytes({"ВОР": [HEADER, [1, "Кладка", "м2", 1]]})
    with pytest.raises(VorParseError):
        vor.parse_workbook(io.BytesIO(broken[: len(broken) // 2]))
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as archive:
        archive.writestr("readme.txt", "нет книги")
    plain_zip.seek(0)
    with pytest.raises(VorParseError):
        vor.parse_workbook(plain_zip)
