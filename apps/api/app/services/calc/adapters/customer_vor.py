"""ВОР Заказчика: только качественное знание «Заказчик ожидает систему В1» — и ничего больше.

ВОР — не эталон и не вход расчёта (ADR-0030, решение владельца 2026-09-28). Из него берутся
только упоминания систем ВК; количества, диаметры и типоразмеры не превращаются ни в какой
факт — они лишь подсчитываются в сводке сбора, чтобы было видно, что их намеренно не взяли.
Утверждения из ВОР хранятся с `calculation_eligible = false` (это держит ограничение базы) и в
снимок для ядра не попадают.
"""

from __future__ import annotations

import re
from typing import Final

from app.contracts.calc.enums import (
    CalcConfidence,
    CalcDiscipline,
    CalcFactMethod,
    CalcInspectionIssueCode,
    CalcSourceClass,
)
from app.contracts.calc.facts import CalcRegionTableLocator, CalcRegionTextLocator
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcBooleanValue
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
from app.services.calc.adapters.normalize import normalize_text, parse_decimal_ru
from app.services.calc.adapters.parsed import ParsedRegion, table_title
from app.services.calc.adapters.recognized import RecognizedRegion, is_metadata_line
from app.services.calc.adapters.text_values import VK_KEYWORDS, vk_codes

VOR_EXTRACTOR: Final = "customer_vor"

_DIAMETER = re.compile(r"(?:ø|⌀|\bdn\s?|\bду\s?|д\.у\.\s?|\bd\s?=?\s?)\d{2,3}", re.IGNORECASE)
_QUANTITY_HEADER = re.compile(r"кол|количеств|объ[её]м")
_TRUBO = re.compile(r"труб|стояк|магистрал")


def _present(
    declaration: CollectionDeclaration,
    code: str,
    evidence: CandidateEvidence,
    method: CalcFactMethod,
) -> CalcCandidate:
    return CalcCandidate(
        extractor=VOR_EXTRACTOR,
        source_class=CalcSourceClass.CUSTOMER_VOR,
        fact_type="system.present",
        subject=CalcFactSubject(
            building=declaration.building, discipline=CalcDiscipline.VK, system_code=code
        ),
        value=CalcBooleanValue(value=True),
        method=method,
        confidence=CalcConfidence.MEDIUM,
        note="Система упомянута в ВОР Заказчика — только для сверки, в расчёт не идёт.",
        evidence=(evidence,),
    )


def _vk_context(text: str) -> bool:
    return bool(VK_KEYWORDS.search(text) or _TRUBO.search(normalize_text(text)))


def extract_customer_vor(
    parsed: tuple[ParsedRegion, ...], declaration: CollectionDeclaration
) -> Extraction:
    result = Extraction()
    quantities = 0
    diameters = 0
    for parsed_region in parsed:
        region: RecognizedRegion = parsed_region.region
        for parsed_table in parsed_region.tables:
            table = parsed_table.table
            context = " ".join(part for part in (table.title, *table.context) if part)
            header = [normalize_text(cell) for cell in table.header]
            quantity_columns = [i for i, cell in enumerate(header) if _QUANTITY_HEADER.search(cell)]
            for row_index, row in enumerate(table.rows):
                text = " ".join(row)
                diameters += len(_DIAMETER.findall(text))
                quantities += sum(
                    1
                    for column in quantity_columns
                    if column < len(row) and parse_decimal_ru(row[column]) is not None
                )
                codes = vk_codes(text)
                if not codes or not (_vk_context(text) or _vk_context(context)):
                    continue
                evidence = CandidateEvidence(
                    region=region,
                    locator=CalcRegionTableLocator(table_index=table.index, rows=[row_index]),
                    label=clip(f"«{table_title(table)}», позиция ВОР", LABEL_LIMIT),
                    excerpt=clip(" | ".join(row), EXCERPT_LIMIT),
                )
                for code in codes:
                    result.candidates.append(
                        _present(declaration, code, evidence, CalcFactMethod.TABLE_EXPLICIT)
                    )
        offset = 0
        for line in region.text.splitlines(keepends=True):
            stripped = line.rstrip("\r\n")
            start = offset
            offset += len(line)
            if is_metadata_line(stripped) or stripped.lstrip().startswith("|"):
                continue
            diameters += len(_DIAMETER.findall(stripped))
            codes = vk_codes(stripped)
            if not codes or not _vk_context(stripped):
                continue
            evidence = CandidateEvidence(
                region=region,
                locator=CalcRegionTextLocator(start=start, end=start + len(stripped)),
                label="Строка ВОР Заказчика",
                excerpt=clip(stripped, EXCERPT_LIMIT),
            )
            for code in codes:
                result.candidates.append(
                    _present(declaration, code, evidence, CalcFactMethod.DOCUMENT_EXPLICIT)
                )
    if quantities:
        result.issues.append(
            CandidateIssue(
                CalcInspectionIssueCode.VOR_QUANTITY_IGNORED,
                "Количества из ВОР Заказчика не приняты: ВОР не вход расчёта",
                count=quantities,
            )
        )
    if diameters:
        result.issues.append(
            CandidateIssue(
                CalcInspectionIssueCode.VOR_DIAMETER_IGNORED,
                "Диаметры из ВОР Заказчика не приняты: ВОР не определяет решения расчёта",
                count=diameters,
            )
        )
    return result
