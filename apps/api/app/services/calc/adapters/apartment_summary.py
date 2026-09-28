"""Квартирография: квартиры по типам и по этажам, итог по корпусу — значения прямо из ячеек.

Поддерживаются два вида сводки: строки по типам квартир («1 ККВ | 96») и строки по этажам
(«2-24 | 9»). Итоговая строка («Итого», «Всего») даёт число квартир корпуса. Тип квартиры
сопоставляется с перечнем по подписи; евроформаты («2Е») неоднозначны и не сопоставляются —
это видно в сводке сбора, а не угадывается.
"""

from __future__ import annotations

import re
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
from app.services.calc.adapters.normalize import (
    apartment_type,
    building_in_text,
    floor_code,
    normalize_text,
    parse_count,
)
from app.services.calc.adapters.parsed import ParsedRegion, ParsedTable, table_title

SUMMARY_EXTRACTOR: Final = "apartment_summary"

_TOTAL = re.compile(r"^(итого|всего)")
_FLOOR_LABEL = re.compile(r"^(-?\d{1,3})(?:\s*[-–—]\s*(-?\d{1,3}))?(?:\s*этаж\w*)?$")


def _column(header: list[str], pattern: str, exclude: str | None = None) -> int | None:
    for index, cell in enumerate(header):
        if re.search(pattern, cell) and not (exclude and re.search(exclude, cell)):
            return index
    return None


def _floor_label(label: str) -> str | None:
    match = _FLOOR_LABEL.match(normalize_text(label).replace("эт.", "этаж"))
    if not match:
        return None
    high = match.group(2)
    return floor_code(int(match.group(1)), None if high is None else int(high))


def _extract_table(
    parsed_region: ParsedRegion, parsed_table: ParsedTable, declaration: CollectionDeclaration
) -> Extraction:
    result = Extraction()
    table = parsed_table.table
    header = [normalize_text(cell) for cell in table.header]
    count_column = _column(header, r"кол|количеств|шт|число", exclude=r"%")
    floor_column = _column(header, r"этаж")
    type_column = _column(header, r"тип|наименовани")
    label_column = floor_column if floor_column is not None else type_column
    fact_type = (
        "floor.apartments_count" if floor_column is not None else "building.apartments_by_type"
    )
    if count_column is None or label_column is None:
        result.issues.append(
            CandidateIssue(
                CalcInspectionIssueCode.ROW_NOT_UNDERSTOOD,
                f"Квартирография без столбцов типа или этажа и количества: «{table_title(table)}»",
                fact_type,
            )
        )
        return result

    def evidence(row_index: int, row: tuple[str, ...]) -> CandidateEvidence:
        return CandidateEvidence(
            region=parsed_region.region,
            locator=CalcRegionTableLocator(
                table_index=table.index, rows=[row_index], column=count_column
            ),
            label=clip(f"«{table_title(table)}», строка «{row[label_column]}»", LABEL_LIMIT),
            excerpt=clip(" | ".join(row), EXCERPT_LIMIT),
        )

    for row_index, row in enumerate(table.rows):
        if len(row) <= max(count_column, label_column):
            continue
        label = row[label_column]
        if not label:
            continue
        count = parse_count(row[count_column])
        is_total = bool(_TOTAL.match(normalize_text(label)))
        target = "building.apartments_total" if is_total else fact_type
        if count is None:
            result.issues.append(
                CandidateIssue(
                    CalcInspectionIssueCode.VALUE_INVALID,
                    f"Не число в столбце количества: «{clip(row[count_column], 40)}»",
                    target,
                )
            )
            continue
        subject: CalcFactSubject | None
        if is_total:
            subject = CalcFactSubject(building=declaration.building)
        elif floor_column is not None:
            floor = _floor_label(label)
            if floor is None:
                result.issues.append(
                    CandidateIssue(
                        CalcInspectionIssueCode.UNSCOPED,
                        f"Этаж не распознан: «{clip(label, 40)}»",
                        target,
                    )
                )
                continue
            subject = CalcFactSubject(building=declaration.building, floor=floor)
        else:
            kind = apartment_type(label)
            if kind is None:
                result.issues.append(
                    CandidateIssue(
                        CalcInspectionIssueCode.UNMAPPED_LABEL,
                        f"Тип квартиры не сопоставлен: «{clip(label, 40)}»",
                        target,
                    )
                )
                continue
            subject = CalcFactSubject(building=declaration.building, qualifier=kind)
        result.candidates.append(
            CalcCandidate(
                extractor=SUMMARY_EXTRACTOR,
                source_class=CalcSourceClass.APARTMENT_SCHEDULE,
                fact_type=target,
                subject=subject,
                value=CalcCountValue(value=count),
                method=CalcFactMethod.TABLE_EXPLICIT,
                confidence=CalcConfidence.HIGH,
                note=f"Ячейка столбца «{table.header[count_column]}» квартирографии.",
                evidence=(evidence(row_index, row),),
            )
        )
    return result


def extract_apartment_summary(
    parsed: tuple[ParsedRegion, ...], declaration: CollectionDeclaration
) -> Extraction:
    result = Extraction()
    building = declaration.building.upper()
    for parsed_region in parsed:
        for parsed_table in parsed_region.tables:
            if parsed_table.classification.kind is not CalcTableKind.APARTMENT_SUMMARY:
                continue
            table = parsed_table.table
            scope_text = " ".join(part for part in (table.title, *table.context) if part)
            mention = building_in_text(scope_text)
            if mention is not None and mention != building:
                result.issues.append(
                    CandidateIssue(
                        CalcInspectionIssueCode.SCOPE_MISMATCH,
                        f"Квартирография корпуса {mention}, а документ — корпуса {building}",
                        "building.apartments_total",
                    )
                )
                continue
            result.extend(_extract_table(parsed_region, parsed_table, declaration))
    return result
