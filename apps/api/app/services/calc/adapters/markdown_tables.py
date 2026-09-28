"""Таблицы GFM в тексте блока распознанного пакета.

Распознавалка пишет таблицы строками `| a | b |` с разделителем `| :--- | :--- |` под шапкой.
Часто шапка — это название таблицы в одной ячейке («Экспликация квартир 3 этажа | | |»), а
настоящая шапка идёт первой строкой данных; бывают жирные строки групп, строки итогов,
литералы `\\n` внутри ячеек. Разбор строгий: без строки-разделителя таблицы нет.

Номера строк — с нуля после настоящей шапки. Вместе с отпечатком текста блока они однозначно
указывают на строку и служат свидетельством.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.calc.adapters.recognized import is_metadata_line

_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_SPLIT = re.compile(r"(?<!\\)\|")
_BOLD = re.compile(r"\*\*|__")
_BREAKS = re.compile(r"\\n|<br\s*/?>", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s*")
_NUMERIC = re.compile(r"^[+\-−]?[\d\s]+([.,]\d+)?$")


@dataclass(frozen=True, slots=True)
class MarkdownTable:
    index: int
    """Порядковый номер таблицы в тексте блока, с нуля."""
    title: str | None
    """Название из однострочной шапки, если оно было."""
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    context: tuple[str, ...]
    """До трёх строк текста перед таблицей: заголовок «### Экспликация…» и т. п."""


def clean_cell(cell: str) -> str:
    text = _BREAKS.sub(" ", cell.replace("\\|", "|"))
    text = _BOLD.sub("", text)
    return _SPACES.sub(" ", text).strip()


def split_row(line: str) -> tuple[str, ...]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return tuple(clean_cell(cell) for cell in _SPLIT.split(body))


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _looks_like_header(cells: tuple[str, ...]) -> bool:
    filled = [cell for cell in cells if cell]
    return (
        len(filled) >= 2
        and not any(_NUMERIC.match(cell) for cell in filled)
        and any(any(char.isalpha() for char in cell) for cell in filled)
    )


def _context(lines: list[str], start: int) -> tuple[str, ...]:
    found: list[str] = []
    index = start - 1
    while index >= 0 and len(found) < 3:
        line = lines[index]
        if _is_table_line(line):
            break
        if line.strip() and not is_metadata_line(line):
            found.append(_HEADING.sub("", line).strip())
        index -= 1
    return tuple(reversed(found))


def parse_tables(text: str) -> tuple[MarkdownTable, ...]:
    lines = text.splitlines()
    tables: list[MarkdownTable] = []
    index = 0
    while index < len(lines) - 1:
        if not (_is_table_line(lines[index]) and _SEPARATOR.match(lines[index + 1])):
            index += 1
            continue
        header = split_row(lines[index])
        body_start = index + 2
        end = body_start
        while end < len(lines) and _is_table_line(lines[end]):
            end += 1
        rows = [split_row(line) for line in lines[body_start:end]]

        title: str | None = None
        filled = [cell for cell in header if cell]
        if len(filled) <= 1:
            title = filled[0] if filled else None
            if rows and _looks_like_header(rows[0]):
                header, rows = rows[0], rows[1:]
            else:
                header = ()
        tables.append(
            MarkdownTable(
                index=len(tables),
                title=title,
                header=header,
                rows=tuple(rows),
                context=_context(lines, index),
            )
        )
        index = end
    return tuple(tables)
