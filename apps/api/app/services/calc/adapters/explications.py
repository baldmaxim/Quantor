"""Экспликации квартир и помещений → квартиры, кухни, санузлы и помещения с водой по этажам.

Экспликация перечисляет квартиры этажа строками «Квартира № …», а под ними — помещения. Число
квартир, кухонь и санузлов — подсчёт явно перечисленных строк (метод TABLE_COUNTED): каждая
строка — свидетельство, самого числа в ячейке нет.

Экспликация одного этажа разбита на несколько таблиц: на листе это колонки одной длинной
таблицы, и порядок блоков распознавалки не совпадает с порядком чтения. Поэтому счёт ведётся
по этажу целиком: квартира узнаётся по номеру, и повторённая на двух страницах считается один
раз. Разбивка по секциям не делается: хвост секции в соседней колонке нельзя надёжно отнести к
своей секции, а неверная секция хуже отсутствующей. Секции остаются в тексте свидетельства.

Таблица без своего этажа в названии не считается: этаж не угадывается по соседям.

В таблице на группу этажей («4-5 этажа») строка «Квартира № 24, 35» — одна позиция на каждом
этаже группы, поэтому число строк — квартир на каждом этаже группы.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Final

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcFactMethod,
    CalcInspectionIssueCode,
    CalcSourceClass,
    CalcTableKind,
)
from app.contracts.calc.facts import CalcRegionTableLocator
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcCountValue
from app.services.calc.adapters.candidates import (
    EXCERPT_LIMIT,
    LABEL_LIMIT,
    CalcCandidate,
    CandidateEvidence,
    CandidateIssue,
    CollectionDeclaration,
    Extraction,
    clip,
)
from app.services.calc.adapters.markdown_tables import MarkdownTable
from app.services.calc.adapters.normalize import (
    building_in_text,
    is_kitchen,
    is_sanitary_room,
    is_wet_nonresidential,
    normalize_text,
    parse_apartment_label,
    parse_decimal_ru,
    parse_floor_scope,
    parse_section,
)
from app.services.calc.adapters.parsed import ParsedRegion, table_title
from app.services.calc.adapters.recognized import RecognizedRegion

APARTMENT_EXTRACTOR: Final = "apartment_explication"
ROOM_EXTRACTOR: Final = "room_explication"

_FACTS_BY_KIND: Final[dict[CalcTableKind, tuple[str, ...]]] = {
    CalcTableKind.APARTMENT_EXPLICATION: (
        "floor.apartments_count",
        "floor.kitchens_count",
        "floor.bathrooms_count",
    ),
    CalcTableKind.ROOM_EXPLICATION: ("floor.nonresidential_wet_rooms_count",),
}


@dataclass(frozen=True, slots=True)
class _Row:
    region: RecognizedRegion
    table: MarkdownTable
    row_index: int
    text: str


@dataclass(slots=True)
class _Floor:
    apartments: dict[str, _Row] = field(default_factory=dict)
    kitchens: dict[tuple[str, ...], _Row] = field(default_factory=dict)
    bathrooms: dict[tuple[str, ...], _Row] = field(default_factory=dict)
    rooms: dict[tuple[str | None, str, str], _Row] = field(default_factory=dict)
    wet: dict[tuple[str | None, str, str], _Row] = field(default_factory=dict)
    sections: set[str] = field(default_factory=set)


def _name_column(header: tuple[str, ...]) -> int:
    for index, cell in enumerate(header):
        text = normalize_text(cell)
        if ("имя" in text or "наименован" in text or text.startswith("помещени")) and (
            "номер" not in text
        ):
            return index
    return 1


def _evidence(rows: list[_Row], what: str) -> tuple[CandidateEvidence, ...]:
    """Одно свидетельство на таблицу: её строки, которые посчитаны."""
    by_table: dict[tuple[str, int], list[_Row]] = defaultdict(list)
    for row in rows:
        by_table[(str(row.region.id), row.table.index)].append(row)
    evidence: list[CandidateEvidence] = []
    for group in by_table.values():
        first = group[0]
        indexes = sorted({row.row_index for row in group})[:500]
        evidence.append(
            CandidateEvidence(
                region=first.region,
                locator=CalcRegionTableLocator(table_index=first.table.index, rows=indexes),
                label=clip(f"«{table_title(first.table)}»: {len(group)} {what}", LABEL_LIMIT),
                excerpt=clip("; ".join(row.text for row in group), EXCERPT_LIMIT),
            )
        )
    return tuple(evidence)


def _scan_table(
    table: MarkdownTable, kind: CalcTableKind, region: RecognizedRegion, floor: _Floor
) -> None:
    name_column = _name_column(table.header)
    section: str | None = None
    apartment: str | None = None
    for row_index, row in enumerate(table.rows):
        first = row[0] if row else ""
        if (found := parse_section(first)) is not None:
            section, apartment = found, None
            floor.sections.add(found)
            continue
        if kind is CalcTableKind.APARTMENT_EXPLICATION and (label := parse_apartment_label(first)):
            apartment = label
            floor.apartments.setdefault(label, _Row(region, table, row_index, first))
            continue
        name = row[name_column] if name_column < len(row) else ""
        if not name or parse_decimal_ru(name) is not None:
            continue
        number = row[0] if row else ""
        entry = _Row(region, table, row_index, f"{number} {name}".strip())
        if kind is CalcTableKind.APARTMENT_EXPLICATION:
            if apartment is None:
                continue
            key = (apartment, number, normalize_text(name))
            if is_kitchen(name):
                floor.kitchens.setdefault(key, entry)
            elif is_sanitary_room(name):
                floor.bathrooms.setdefault(key, entry)
        else:
            room_key = (section, number, normalize_text(name))
            floor.rooms.setdefault(room_key, entry)
            if is_wet_nonresidential(name):
                floor.wet.setdefault(room_key, entry)


def _candidate(
    extractor: str,
    source_class: CalcSourceClass,
    fact_type: str,
    subject: CalcFactSubject,
    rows: list[_Row],
    value: int,
    what: str,
    note: str,
) -> CalcCandidate:
    return CalcCandidate(
        extractor=extractor,
        source_class=source_class,
        fact_type=fact_type,
        subject=subject,
        value=CalcCountValue(value=value),
        method=CalcFactMethod.TABLE_COUNTED,
        confidence=CalcConfidence.MEDIUM,
        note=note,
        evidence=_evidence(rows, what),
    )


def extract_explications(
    parsed: tuple[ParsedRegion, ...], declaration: CollectionDeclaration
) -> Extraction:
    result = Extraction()
    floors: dict[tuple[CalcTableKind, str], _Floor] = {}
    building = declaration.building.upper()

    for parsed_region in parsed:
        for parsed_table in parsed_region.tables:
            kind = parsed_table.classification.kind
            if kind not in _FACTS_BY_KIND:
                continue
            table = parsed_table.table
            scope_text = " ".join(part for part in (table.title, *table.context) if part)
            scope = parse_floor_scope(scope_text)
            if scope is None:
                shown = clip(scope_text or "без названия", 80)
                for fact_type in _FACTS_BY_KIND[kind]:
                    result.issues.append(
                        CandidateIssue(
                            CalcInspectionIssueCode.UNSCOPED,
                            f"Экспликация без этажа: «{shown}»",
                            fact_type,
                        )
                    )
                continue
            mention = building_in_text(scope_text)
            if mention is not None and mention != building:
                for fact_type in _FACTS_BY_KIND[kind]:
                    result.issues.append(
                        CandidateIssue(
                            CalcInspectionIssueCode.SCOPE_MISMATCH,
                            f"Таблица корпуса {mention}, документ заявлен для корпуса {building}",
                            fact_type,
                        )
                    )
                continue
            _scan_table(
                table, kind, parsed_region.region, floors.setdefault((kind, scope), _Floor())
            )

    for (kind, floor_code), floor in floors.items():
        subject = CalcFactSubject(building=declaration.building, floor=floor_code)
        sections = (
            f"; секции в таблицах: {', '.join(sorted(floor.sections))}" if floor.sections else ""
        )
        if kind is CalcTableKind.APARTMENT_EXPLICATION:
            if not floor.apartments:
                continue
            result.candidates.append(
                _candidate(
                    APARTMENT_EXTRACTOR,
                    CalcSourceClass.APARTMENT_SCHEDULE,
                    "floor.apartments_count",
                    subject,
                    list(floor.apartments.values()),
                    len(floor.apartments),
                    "строк «Квартира №»",
                    "Подсчитаны строки «Квартира №» экспликации квартир этажа "
                    f"{floor_code}; повторы номеров не учтены{sections}.",
                )
            )
            for fact_type, rooms, what in (
                ("floor.kitchens_count", floor.kitchens, "кухонь"),
                ("floor.bathrooms_count", floor.bathrooms, "санузлов и ванных"),
            ):
                if rooms:
                    result.candidates.append(
                        _candidate(
                            APARTMENT_EXTRACTOR,
                            CalcSourceClass.APARTMENT_SCHEDULE,
                            fact_type,
                            subject,
                            list(rooms.values()),
                            len(rooms),
                            what,
                            f"Подсчитаны помещения квартир в экспликации этажа {floor_code}.",
                        )
                    )
        elif floor.rooms:
            wet = list(floor.wet.values())
            result.candidates.append(
                _candidate(
                    ROOM_EXTRACTOR,
                    CalcSourceClass.ROOM_SCHEDULE,
                    "floor.nonresidential_wet_rooms_count",
                    subject,
                    wet or list(floor.rooms.values()),
                    len(wet),
                    "помещений с водой" if wet else "помещений, с водой нет",
                    "Подсчитаны ПУИ, санузлы, душевые и моечные в экспликации помещений этажа "
                    f"{floor_code}; проверено помещений: {len(floor.rooms)}.",
                )
            )
    return result
