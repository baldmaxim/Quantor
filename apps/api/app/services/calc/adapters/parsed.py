"""Документ, разобранный один раз для всех извлекателей: таблицы с их смыслом и штамп блока."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.calc.adapters.markdown_tables import MarkdownTable, parse_tables
from app.services.calc.adapters.recognized import (
    RecognizedDocument,
    RecognizedRegion,
    Stamp,
    parse_stamp,
)
from app.services.calc.adapters.table_kinds import TableClassification, classify


@dataclass(frozen=True, slots=True)
class ParsedTable:
    table: MarkdownTable
    classification: TableClassification


@dataclass(frozen=True, slots=True)
class ParsedRegion:
    region: RecognizedRegion
    tables: tuple[ParsedTable, ...]
    stamp: Stamp | None


def parse_document(document: RecognizedDocument) -> tuple[ParsedRegion, ...]:
    """Только текстовые блоки: описание изображения написала модель распознавалки."""
    return tuple(
        ParsedRegion(
            region=region,
            tables=tuple(
                ParsedTable(table, classify(table)) for table in parse_tables(region.text)
            ),
            stamp=parse_stamp(region.text),
        )
        for region in document.text_regions()
    )


def table_title(table: MarkdownTable) -> str:
    """Название таблицы для подписи свидетельства: своё или ближайший заголовок перед ней."""
    return table.title or (table.context[-1] if table.context else "таблица без названия")
