"""Разбор XLSX с ВОР Заказчика для контура «Конструкции CAD» (ADR-0038 п. 5).

ВОР здесь - только объект сверки: строки и количества читаются для показа и поиска, на расчёт
конструкций не влияют, во внешние сервисы не уходят. Файл пользовательский и недоверенный, поэтому:

- до открытия проверяется суммарный несжатый размер архива (защита от zip-бомбы);
- читается только `read_only=True, data_only=True`: формулы не вычисляются, внешние связи не
  загружаются;
- число строк и размер файла ограничены, скрытые листы пропускаются.

Модуль - чистые функции без базы и хранилища. Любая причина, по которой файл нельзя принять как
ВОР, - `VorParseError` с понятным текстом; API превращает его в 422 `CAD_VOR_PARSE_FAILED`.
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import chain, islice
from math import isfinite
from typing import IO, Final, Literal

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

MAX_FILE_BYTES: Final = 20 * 1024 * 1024
MAX_ROWS: Final = 20_000
MAX_UNCOMPRESSED_BYTES: Final = 200 * 1024 * 1024
# Сколько первых строк листа просматривается в поисках заголовка таблицы.
HEADER_SCAN_ROWS: Final = 30
# Сколько строк листа вообще просматривается: пустые «хвосты» листа не должны зацикливать разбор.
MAX_SCAN_ROWS: Final = 100_000
MAX_ZIP_ENTRIES: Final = 10_000

KindHint = Literal["masonry", "monolith"]
ColumnRole = Literal["code", "name", "unit", "quantity"]

_QUANTITY_RE: Final = re.compile(r"кол-?во|колич|кол\.|объ[её]м")
_NUMBER_RE: Final = re.compile(r"-?\d+(?:\.\d+)?")
_MAX_ABS_QUANTITY: Final = Decimal(10) ** 15

# Размеры блока «200х300х600» - не толщина: вырезаются до поиска «NNN мм».
# Старт только на границе числа (?<!\d): иначе длинные цифровые строки дают ReDoS (перебор O(n²)).
_DIMENSIONS_RE: Final = re.compile(r"(?<!\d)\d+(?:[.,]\d+)?(?:\s*[хx×*]\s*\d+(?:[.,]\d+)?)+")
# Сколько первых символов наименования анализируется на толщину; полное имя хранится как есть.
THICKNESS_HINT_MAX_CHARS: Final = 1000
_THICKNESS_RES: Final = (
    re.compile(r"толщ\w*\.?\s*[:=]?\s*(\d{2,3})(?!\d)"),
    re.compile(r"δ\s*=?\s*(\d{2,3})(?!\d)"),
    re.compile(r"(?<![\d.,])(\d{2,3})\s*мм"),
)
_MASONRY_RE: Final = re.compile(r"кладк|перегород|блок|кирпич|газобетон|\bпгп\b")
_MONOLITH_RE: Final = re.compile(
    r"монолит|железобетон|ж\s*[/.]\s*б\b|(?<!газо)(?<!пено)бетон\w*\s+(?:\w+\s+)?(?:стен|пилон|колонн)"
)


class VorParseError(Exception):
    """Файл нельзя принять как ВОР; текст безопасен для показа пользователю."""


@dataclass(frozen=True, slots=True)
class ParsedItem:
    """Строка ВОР после разбора."""

    sheet: str
    row_no: int
    code: str | None
    name: str
    unit: str | None
    quantity: Decimal | None
    section: str | None
    name_norm: str
    thickness_hint_mm: int | None
    kind_hint: KindHint | None


@dataclass(frozen=True, slots=True)
class ParsedSheet:
    """Лист с найденной таблицей: строка заголовка, колонки и строки."""

    sheet: str
    header_row: int
    # Роль колонки -> номер колонки, с единицы.
    columns: dict[ColumnRole, int]
    items: list[ParsedItem]


@dataclass(frozen=True, slots=True)
class ParsedWorkbook:
    sheets: list[ParsedSheet]

    @property
    def items_count(self) -> int:
        return sum(len(sheet.items) for sheet in self.sheets)


@dataclass(slots=True)
class _Budget:
    """Сколько непустых строк ещё можно прочитать из книги."""

    remaining: int = MAX_ROWS

    def take(self) -> None:
        self.remaining -= 1
        if self.remaining < 0:
            raise VorParseError(f"В файле больше {MAX_ROWS} строк: разбейте ВОР на части")


# --------------------------------------------------------------------------- тексты и числа


def normalize_text(value: str) -> str:
    """Для поиска: нижний регистр, «ё» как «е», пробелы схлопнуты."""
    return " ".join(value.lower().replace("ё", "е").split())


def cell_text(value: object) -> str | None:
    """Ячейка как текст без лишних пробелов; целое число без «.0»; пусто - None."""
    if value is None:
        return None
    text = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
    return " ".join(text.split()) or None


def parse_number(value: object) -> Decimal | None:
    """Количество из ячейки: число, либо текст с запятой и пробелами. Не число - None."""
    parsed: Decimal
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, float):
        if not isfinite(value):
            return None
        parsed = Decimal(repr(value))
    elif isinstance(value, Decimal):
        if not value.is_finite():
            return None
        parsed = value
    elif isinstance(value, str):
        compact = "".join(value.split()).replace(",", ".")
        if not _NUMBER_RE.fullmatch(compact):
            return None
        parsed = Decimal(compact)
    else:
        return None
    if abs(parsed) >= _MAX_ABS_QUANTITY:
        return None
    return round(parsed, 4)


def thickness_hint(name_norm: str) -> int | None:
    """Толщина в мм из наименования: «толщиной 100», «δ=100», «100 мм»; не нашлась - None."""
    cleaned = _DIMENSIONS_RE.sub(" ", name_norm[:THICKNESS_HINT_MAX_CHARS])
    for pattern in _THICKNESS_RES:
        found = pattern.search(cleaned)
        if found is not None:
            return int(found.group(1))
    return None


def kind_hint(name_norm: str) -> KindHint | None:
    """Вид конструкции по словам; слова обоих видов сразу - неоднозначно, подсказки нет."""
    masonry = _MASONRY_RE.search(name_norm) is not None
    monolith = _MONOLITH_RE.search(name_norm) is not None
    if masonry == monolith:
        return None
    return "masonry" if masonry else "monolith"


# --------------------------------------------------------------------------- заголовок таблицы


def _role_of(header: str) -> ColumnRole | None:
    if _QUANTITY_RE.search(header):
        return "quantity"
    if header.startswith("ед"):
        return "unit"
    if header.startswith(("№", "шифр", "код")) or "п/п" in header:
        return "code"
    if "наименован" in header or "работ" in header:
        return "name"
    return None


def find_header(rows: Sequence[Sequence[object]]) -> tuple[int, dict[ColumnRole, int]] | None:
    """Строка заголовка среди первых строк листа: (номер строки с единицы, роль -> колонка).

    Заголовком считается строка, где есть и наименование, и количество; единица и шифр
    необязательны. Роль колонки - по первой подходящей ячейке.
    """
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS], start=1):
        columns: dict[ColumnRole, int] = {}
        for position, value in enumerate(row, start=1):
            text = cell_text(value)
            if text is None:
                continue
            role = _role_of(normalize_text(text))
            if role is not None and role not in columns:
                columns[role] = position
        if "name" in columns and "quantity" in columns:
            return index, columns
    return None


# --------------------------------------------------------------------------- разбор листа


def _at(row: Sequence[object], column: int | None) -> object:
    if column is None or column > len(row):
        return None
    return row[column - 1]


def _parse_body(
    sheet: str,
    header_row: int,
    columns: dict[ColumnRole, int],
    rows: Iterable[Sequence[object]],
    budget: _Budget,
) -> list[ParsedItem]:
    """Строки под заголовком; `rows` начинается со строки с номером `header_row + 1`."""
    items: list[ParsedItem] = []
    section: str | None = None
    for row_no, row in enumerate(rows, start=header_row + 1):
        if all(cell_text(value) is None for value in row):
            continue
        budget.take()
        name = cell_text(_at(row, columns.get("name")))
        unit = cell_text(_at(row, columns.get("unit")))
        quantity = parse_number(_at(row, columns.get("quantity")))
        if name is None and quantity is None and unit is None:
            # Заголовок раздела часто стоит в объединённой ячейке не под «Наименованием».
            heading = next((text for text in map(cell_text, row) if text is not None), None)
            if heading is not None and any(char.isalpha() for char in heading):
                section = heading
            continue
        if name is None or name.isdigit():
            # Нет наименования (итоги, подписи) или строка нумерации колонок «1 2 3 4».
            continue
        if quantity is None and unit is None:
            # Без количества и единицы, но с текстом - заголовок раздела.
            section = name
            continue
        name_norm = normalize_text(name)
        code = cell_text(_at(row, columns.get("code")))
        items.append(
            ParsedItem(
                sheet=sheet[:255],
                row_no=row_no,
                code=code[:128] if code else None,
                name=name,
                unit=unit[:64] if unit else None,
                quantity=quantity,
                section=section,
                name_norm=name_norm,
                thickness_hint_mm=thickness_hint(name_norm),
                kind_hint=kind_hint(name_norm),
            )
        )
    return items


def parse_sheet(
    sheet: str, rows: Iterable[Sequence[object]], budget: _Budget | None = None
) -> ParsedSheet | None:
    """Таблица листа или None, если заголовок среди первых строк не найден."""
    iterator = iter(rows)
    head = list(islice(iterator, HEADER_SCAN_ROWS))
    header = find_header(head)
    if header is None:
        return None
    header_row, columns = header
    body = chain(head[header_row:], iterator)
    items = _parse_body(sheet, header_row, columns, body, budget or _Budget())
    return ParsedSheet(sheet=sheet, header_row=header_row, columns=columns, items=items)


# --------------------------------------------------------------------------- книга


def check_archive(source: IO[bytes]) -> None:
    """Суммарный несжатый размер архива и число частей - до того, как книгу откроет openpyxl."""
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as error:
        raise VorParseError("Файл не является книгой XLSX") from error
    if len(entries) > MAX_ZIP_ENTRIES:
        raise VorParseError("Архив XLSX содержит слишком много частей")
    if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
        raise VorParseError(
            f"Содержимое XLSX после распаковки больше {MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} МБ"
        )
    source.seek(0)


def parse_workbook(source: IO[bytes]) -> ParsedWorkbook:
    """Разбирает книгу: все видимые листы, на которых нашлась таблица ВОР.

    `source` - файл с указателем в начале. Ошибки формата и лимитов - `VorParseError`.
    """
    check_archive(source)
    budget = _Budget()
    sheets: list[ParsedSheet] = []
    try:
        workbook = load_workbook(source, read_only=True, data_only=True, keep_links=False)
    except (
        zipfile.BadZipFile,
        InvalidFileException,
        KeyError,
        ValueError,
        OSError,
        SyntaxError,
        TypeError,
        AttributeError,
        IndexError,
    ) as error:
        raise VorParseError("Файл не читается как книга XLSX") from error
    try:
        for worksheet in workbook.worksheets:
            if worksheet.sheet_state != "visible":
                continue
            rows = worksheet.iter_rows(values_only=True, max_row=MAX_SCAN_ROWS)
            parsed = parse_sheet(worksheet.title, rows, budget)
            if parsed is not None:
                sheets.append(parsed)
    except (
        zipfile.BadZipFile,
        KeyError,
        ValueError,
        OSError,
        SyntaxError,
        TypeError,
        AttributeError,
        IndexError,
    ) as error:
        raise VorParseError("Файл повреждён: листы книги не читаются") from error
    finally:
        workbook.close()
    if not sheets:
        raise VorParseError(
            "Не найдена строка заголовка таблицы ВОР: в первых "
            f"{HEADER_SCAN_ROWS} строках листа нужны колонки «Наименование» и «Количество»"
        )
    if sum(len(sheet.items) for sheet in sheets) == 0:
        raise VorParseError("Под заголовком таблицы нет строк с наименованием и количеством")
    return ParsedWorkbook(sheets=sheets)
