"""Explicit whole-building water demand rows from a design summary table.

Zone and fire-water rows are deliberately excluded: they cannot be assigned to
the four stage-P calculators from a heading alone.
"""

from __future__ import annotations

import re

from app.contracts.calc.enums import CalcConfidence, CalcDiscipline, CalcFactMethod, CalcSourceClass
from app.contracts.calc.facts import CalcRegionTableLocator
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcNumberValue
from app.services.calc.adapters.candidates import (
    EXCERPT_LIMIT,
    LABEL_LIMIT,
    CalcCandidate,
    CandidateEvidence,
    CollectionDeclaration,
    Extraction,
    clip,
)
from app.services.calc.adapters.normalize import normalize_text, parse_decimal_ru, stated_text
from app.services.calc.adapters.parsed import ParsedRegion, table_title

EXTRACTOR = "water_system_summary"
_WHOLE_BUILDING = re.compile(r"^корпус\s+(\d+(?:[.,]\d+)?)\s+общий\s+расход$")
_ALIAS = re.compile(
    r"корпус\s+(\d+)\s*\(\s*рекламное\s+название\s+(?:жк\s+)?событие\s+(\d+[.,]\d+)",
    re.IGNORECASE,
)
_SYSTEM = {"хвс": "В1", "гвс": "Т3"}
_FLOW = (
    ("system.flow_daily", "m3_day", "м3/сут"),
    ("system.flow_hourly_max", "m3_h", "м3/ч"),
    ("system.flow_second_max", "l_s", "л/с"),
)


def _aliases(parsed: tuple[ParsedRegion, ...], building: str) -> set[str]:
    names = {building.replace(",", ".")}
    for item in parsed:
        for match in _ALIAS.finditer(item.region.text):
            if match.group(1) == building:
                names.add(match.group(2).replace(",", "."))
    return names


def extract_water_summary(
    parsed: tuple[ParsedRegion, ...], declaration: CollectionDeclaration
) -> Extraction:
    result = Extraction()
    if (
        declaration.source_class is not CalcSourceClass.MEP_DESIGN
        or declaration.discipline is not CalcDiscipline.VK
    ):
        return result
    names = _aliases(parsed, declaration.building)
    for item in parsed:
        for parsed_table in item.tables:
            table = parsed_table.table
            if len(table.header) < 5 or normalize_text(table.header[0]) != "наименование системы":
                continue
            if not table.rows or len(table.rows[0]) < 5:
                continue
            units = tuple(normalize_text(cell).replace("³", "3") for cell in table.rows[0][2:5])
            if units != tuple(unit for _, _, unit in _FLOW):
                continue
            in_scope = False
            for row_index, row in enumerate(table.rows[1:], start=1):
                if not row:
                    continue
                label = normalize_text(row[0])
                group = _WHOLE_BUILDING.match(label)
                if group:
                    in_scope = group.group(1).replace(",", ".") in names
                    continue
                if label.startswith("корпус "):
                    in_scope = False
                    continue
                if not in_scope or label not in _SYSTEM or len(row) < 5:
                    continue
                subject = CalcFactSubject(
                    building=declaration.building,
                    discipline=CalcDiscipline.VK,
                    system_code=_SYSTEM[label],
                )
                for column, (fact_type, unit, _) in enumerate(_FLOW, start=2):
                    value = parse_decimal_ru(row[column])
                    if value is None:
                        continue
                    evidence = CandidateEvidence(
                        region=item.region,
                        locator=CalcRegionTableLocator(
                            table_index=table.index, rows=[row_index], column=column
                        ),
                        label=clip(
                            f"{table_title(table)}: общий расход корпуса, {row[0]}", LABEL_LIMIT
                        ),
                        excerpt=clip(" | ".join(row), EXCERPT_LIMIT),
                    )
                    result.candidates.append(
                        CalcCandidate(
                            extractor=EXTRACTOR,
                            source_class=declaration.source_class,
                            fact_type=fact_type,
                            subject=subject,
                            value=CalcNumberValue(value=stated_text(value), unit=unit),
                            method=CalcFactMethod.TABLE_EXPLICIT,
                            confidence=CalcConfidence.HIGH,
                            note=(
                                "Явный расход ХВС или ГВС всего корпуса; "
                                "зональные и пожарные строки исключены."
                            ),
                            evidence=(evidence,),
                        )
                    )
    return result
