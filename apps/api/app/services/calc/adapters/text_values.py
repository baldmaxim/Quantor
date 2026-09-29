"""Значения из текста блоков: названия листов в штампе, отметка ±0,000, явные фразы записок.

Каждый шаблон узкий и требует явной формулировки с единицей: «высота этажа — 3,3 м», а не
«3,3» рядом со словом «высота». Число без единицы не принимается, пока правило не задаёт
единицу; таких правил два — отметки («отм. +27.900», «±0,000=162,050») в метрах по ГОСТ 21.101
и напор «25 м» в метрах водяного столба. Приблизительные значения («≈», «около») в реестр не
идут: у них нет точности, которую можно сохранить.

Обозначения систем ВК («В1», «Т3», «К1») принимаются только из документа, заявленного как ВК или
пояснительная записка, и только рядом со словами водопровода или канализации: «В1» в разделе ОВ
— вытяжная система.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
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
from app.contracts.calc.values import (
    CalcBooleanValue,
    CalcCountValue,
    CalcNumberValue,
)
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
    floor_code,
    floors_in,
    parse_count,
    parse_decimal_ru,
    parse_floor_scope,
    parse_unit,
    stated_text,
)
from app.services.calc.adapters.parsed import ParsedRegion
from app.services.calc.adapters.recognized import RecognizedRegion, is_metadata_line

SHEET_EXTRACTOR: Final = "sheet_titles"
TEXT_EXTRACTOR: Final = "document_text"

_LEVEL = r"[+\-−]?\s?\d{1,3}[.,]\d{3}"
_PLAN = re.compile(
    rf"план\s+(?P<low>-?\d{{1,3}})\s*(?:[-–]\s*(?P<high>-?\d{{1,3}}))?\s*(?:-?(?:го|й))?\s*этаж\w*"
    rf"\s+на\s+отм\.?\s*(?P<levels>{_LEVEL}(?:\s*[,;и]\s*{_LEVEL})*)",
    re.IGNORECASE,
)
_PLAN_TYPICAL = re.compile(
    rf"план\s+типов\w*\s+этаж\w*\s+на\s+отм\.?\s*(?P<levels>{_LEVEL}(?:\s*[,;и]\s*{_LEVEL})*)"
    r"\s*\(\s*(?P<low>-?\d{1,3})\s*[-–]\s*(?P<high>-?\d{1,3})\s*этаж\w*\s*\)",
    re.IGNORECASE,
)
_ZERO_ABS = re.compile(
    r"(?:±|\+-|\+/-)\s*0[.,]000\s*=\s*(?P<v>[+\-−]?\d{1,3}[.,]\d{1,3})"
    r"|отметк\w*\s+[±]?\s*0[.,]000\s+соответству\w*\s+абсолютн\w*\s+отметк\w*\s+"
    r"(?P<v2>[+\-−]?\d{1,3}[.,]\d{1,3})",
    re.IGNORECASE,
)
_APPROX = r"(?P<approx>≈|~|около|порядка|примерно)?\s*"
_SEP = r"\s*(?:[—–:\-]|составляет|равн\w*)?\s*"
_COUNTS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "building.floors_above_ground",
        re.compile(
            rf"(?:этажност\w*(?:\s+(?:здания|корпуса|жилого\s+дома|дома))?"
            rf"|количеств\w*\s+надземн\w*\s+этаж\w*){_SEP}{_APPROX}"
            r"(?P<v>\d{1,3})(?!\d|[.,]\d|\s*[-–]\s*\d)",
            re.IGNORECASE,
        ),
    ),
    (
        "building.floors_below_ground",
        re.compile(
            rf"количеств\w*\s+подземн\w*\s+этаж\w*{_SEP}{_APPROX}(?P<v>\d{{1,2}})(?!\d|[.,]\d)",
            re.IGNORECASE,
        ),
    ),
    (
        "building.apartments_total",
        re.compile(
            rf"(?:общее\s+)?(?:количеств\w*|число)\s+квартир\w*"
            rf"(?:\s+в\s+(?:доме|корпусе|здании))?{_SEP}{_APPROX}(?P<v>\d{{1,5}})(?!\d|[.,]\d)",
            re.IGNORECASE,
        ),
    ),
    (
        "building.sections_count",
        re.compile(
            rf"количеств\w*\s+секций{_SEP}{_APPROX}(?P<v>\d{{1,2}})(?!\d|[.,]\d)", re.IGNORECASE
        ),
    ),
    (
        "building.residents_count",
        re.compile(
            rf"(?:расч[её]тн\w*\s+)?(?:количеств\w*|число)\s+(?:жителей|проживающих)"
            rf"{_SEP}{_APPROX}(?P<v>\d{{1,5}})(?!\d|[.,]\d)",
            re.IGNORECASE,
        ),
    ),
)
_SECTION_WORD_COUNT = re.compile(
    r"(?:здани[ея]|комплекс)\s+состоит\s+из\s+(?P<v>двух|тр[её]х|четыр[её]х)\s+"
    r"(?:жилых\s+)?секций",
    re.IGNORECASE,
)
_SECTION_WORD_VALUES: Final = {"двух": 2, "трех": 3, "четырех": 4}
_FLOOR_HEIGHT = re.compile(
    rf"высот\w*\s+(?P<scope>[^—–:\n]{{0,40}}?)этаж\w*(?P<scope2>[^—–:\d\n]{{0,6}}"
    r"(?:\(?\s*(?:с\s+)?-?\d{1,3}\s*(?:[-–]|по)\s*-?\d{1,3}\s*(?:этаж\w*)?\s*\)?)?)"
    rf"{_SEP}{_APPROX}(?P<v>\d+(?:[.,]\d+)?)\s*(?P<u>мм|м(?![\wа-я²2³3/]))?",
    re.IGNORECASE,
)
_HEAD = re.compile(
    rf"гарантированн\w*\s+напор\w*[^\d\n≈~]{{0,60}}?{_APPROX}(?P<v>\d+(?:[.,]\d+)?)\s*"
    r"(?P<u>м\.?\s*вод\.?\s*ст\.?|мпа|кпа|бар|м(?![\wа-я²2³3/]))?",
    re.IGNORECASE,
)
_HOT_WATER = re.compile(
    r"температур\w*\s+горяч\w*\s+вод\w*[^\d\n]{0,40}?(?P<approx>≈|~|около|не\s+ниже|не\s+выше)?"
    r"\s*(?P<v>\d{2}(?:[.,]\d)?)\s*°\s*[сc]",
    re.IGNORECASE,
)
VK_CODE = re.compile(
    r"(?<![0-9A-Za-zА-Яа-я])(?P<code>[ВBТTКK])\s?(?P<num>[1-4])(?![0-9A-Za-zА-Яа-я])"
)
VK_KEYWORDS = re.compile(
    r"водопровод|водоснабжен|канализац|водоотвед|горяч\w*\s+вод|циркуляц|хоз\w*[-.\s]*питьев",
    re.IGNORECASE,
)
_CODES: Final = frozenset({"В1", "В2", "Т3", "Т4", "К1", "К2", "К3"})
_LATIN: Final = str.maketrans("BTK", "ВТК")


def vk_codes(text: str) -> list[str]:
    found: list[str] = []
    for match in VK_CODE.finditer(text):
        code = (match.group("code") + match.group("num")).translate(_LATIN)
        if code in _CODES and code not in found:
            found.append(code)
    return found


@dataclass(frozen=True, slots=True)
class _Line:
    text: str
    start: int


def _content_lines(text: str, *, with_tables: bool = False) -> Iterator[_Line]:
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if not is_metadata_line(stripped) and (
            with_tables or not stripped.lstrip().startswith("|")
        ):
            yield _Line(stripped, offset)
        offset += len(line)


def _text_evidence(region: RecognizedRegion, start: int, end: int, label: str) -> CandidateEvidence:
    return CandidateEvidence(
        region=region,
        locator=CalcRegionTextLocator(start=start, end=end),
        label=clip(label, LABEL_LIMIT),
        excerpt=clip(region.text[start:end], EXCERPT_LIMIT),
    )


def _meters(text: str) -> Decimal | None:
    return parse_decimal_ru(text.replace(" ", ""))


# ------------------------------------------------------------------------ названия листов


def extract_sheet_titles(
    parsed: tuple[ParsedRegion, ...], declaration: CollectionDeclaration
) -> Extraction:
    """Отметки этажей из названия листа в штампе: «План 9 этажа на отм. +27.900».

    Штамп повторяется в каждом блоке листа — лист читается один раз.
    """
    result = Extraction()
    seen_sheets: set[str] = set()
    for parsed_region in parsed:
        stamp = parsed_region.stamp
        region = parsed_region.region
        if stamp is None or stamp.name is None or str(region.sheet_id) in seen_sheets:
            continue
        seen_sheets.add(str(region.sheet_id))
        name = stamp.name.value
        match = _PLAN_TYPICAL.search(name) or _PLAN.search(name)
        if match is None:
            continue
        levels = [_meters(level) for level in re.split(r"\s*[,;и]\s*", match.group("levels"))]
        high = match.group("high")
        scope = floor_code(int(match.group("low")), None if high is None else int(high))
        if scope is None or any(level is None for level in levels):
            continue
        floors = floors_in(scope)
        if len(levels) != len(floors):
            result.issues.append(
                CandidateIssue(
                    CalcInspectionIssueCode.UNSCOPED,
                    f"В названии листа {len(levels)} отметок на {len(floors)} этажей: "
                    f"«{clip(name, 80)}»",
                    "floor.elevation",
                )
            )
            continue
        evidence = _text_evidence(
            region, stamp.name.start, stamp.name.end, "Название листа в штампе"
        )
        for floor, level in zip(floors, levels, strict=True):
            if level is None:
                continue
            result.candidates.append(
                CalcCandidate(
                    extractor=SHEET_EXTRACTOR,
                    source_class=declaration.source_class,
                    fact_type="floor.elevation",
                    subject=CalcFactSubject(building=declaration.building, floor=str(floor)),
                    value=CalcNumberValue(value=stated_text(level), unit="m"),
                    method=CalcFactMethod.DOCUMENT_EXPLICIT,
                    confidence=CalcConfidence.HIGH,
                    note="Отметка из названия плана в штампе; «отм.» — метры по ГОСТ 21.101.",
                    evidence=(evidence,),
                )
            )
    return result


def extract_contents_sheet_titles(
    parsed: tuple[ParsedRegion, ...], declaration: CollectionDeclaration
) -> Extraction:
    """Floor elevations from the architecture volume's sheet list.

    Only the explicit «Содержание раздела АР» table is used. Revision comparison
    tables elsewhere in the volume contain obsolete elevations as well.
    """
    result = Extraction()
    if declaration.source_class is not CalcSourceClass.ARCHITECTURE:
        return result
    for item in parsed:
        for parsed_table in item.tables:
            table = parsed_table.table
            if not any("содержание раздела ар" in part.lower() for part in table.context):
                continue
            column = next(
                (index for index, cell in enumerate(table.header) if "имя листа" in cell.lower()),
                None,
            )
            if column is None:
                continue
            for row_index, row in enumerate(table.rows):
                if len(row) <= column:
                    continue
                name = row[column]
                match = _PLAN_TYPICAL.search(name) or _PLAN.search(name)
                if match is None:
                    continue
                levels = [
                    _meters(level) for level in re.split(r"\s*[,;и]\s*", match.group("levels"))
                ]
                high = match.group("high")
                scope = floor_code(int(match.group("low")), None if high is None else int(high))
                if scope is None or any(level is None for level in levels):
                    continue
                floors = floors_in(scope)
                if len(levels) != len(floors):
                    continue
                evidence = CandidateEvidence(
                    region=item.region,
                    locator=CalcRegionTableLocator(
                        table_index=table.index, rows=[row_index], column=column
                    ),
                    label=clip("Название листа в содержании раздела АР", LABEL_LIMIT),
                    excerpt=clip(" | ".join(row), EXCERPT_LIMIT),
                )
                for floor, level in zip(floors, levels, strict=True):
                    if level is None:
                        continue
                    result.candidates.append(
                        CalcCandidate(
                            extractor=SHEET_EXTRACTOR,
                            source_class=declaration.source_class,
                            fact_type="floor.elevation",
                            subject=CalcFactSubject(
                                building=declaration.building, floor=str(floor)
                            ),
                            value=CalcNumberValue(value=stated_text(level), unit="m"),
                            method=CalcFactMethod.DOCUMENT_EXPLICIT,
                            confidence=CalcConfidence.HIGH,
                            note="Отметка из названия листа в содержании раздела АР.",
                            evidence=(evidence,),
                        )
                    )
    return result


# ------------------------------------------------------------------------- текст записок


def _approximate(result: Extraction, match: re.Match[str], fact_type: str) -> bool:
    if match.groupdict().get("approx"):
        result.issues.append(
            CandidateIssue(
                CalcInspectionIssueCode.APPROXIMATE,
                f"Приблизительное значение: «{clip(match.group(0), 80)}»",
                fact_type,
            )
        )
        return True
    return False


def _text_candidate(
    declaration: CollectionDeclaration,
    fact_type: str,
    subject: CalcFactSubject,
    value: CalcCountValue | CalcNumberValue | CalcBooleanValue,
    evidence: CandidateEvidence,
    note: str,
    confidence: CalcConfidence = CalcConfidence.HIGH,
) -> CalcCandidate:
    return CalcCandidate(
        extractor=TEXT_EXTRACTOR,
        source_class=declaration.source_class,
        fact_type=fact_type,
        subject=subject,
        value=value,
        method=CalcFactMethod.DOCUMENT_EXPLICIT,
        confidence=confidence,
        note=note,
        evidence=(evidence,),
    )


def vk_allowed(declaration: CollectionDeclaration) -> bool:
    if declaration.source_class is CalcSourceClass.MEP_DESIGN:
        return declaration.discipline is CalcDiscipline.VK
    return declaration.source_class in (
        CalcSourceClass.EXPLANATORY_NOTE,
        CalcSourceClass.TECHNICAL_CONDITIONS,
    )


def extract_text_values(
    parsed: tuple[ParsedRegion, ...], declaration: CollectionDeclaration
) -> Extraction:
    result = Extraction()
    building = CalcFactSubject(building=declaration.building)
    for parsed_region in parsed:
        region = parsed_region.region
        for line in _content_lines(region.text, with_tables=True):
            for match in _ZERO_ABS.finditer(line.text):
                group = "v" if match.group("v") else "v2"
                level = _meters(match.group(group))
                if level is None:
                    continue
                start, end = line.start + match.start(), line.start + match.end()
                result.candidates.append(
                    _text_candidate(
                        declaration,
                        "building.elevation_zero_abs",
                        building,
                        CalcNumberValue(value=stated_text(level), unit="m"),
                        _text_evidence(region, start, end, "Отметка ±0,000"),
                        "Абсолютная отметка ±0,000; отметки — метры по ГОСТ 21.101.",
                    )
                )
        for line in _content_lines(region.text):
            _counts(result, region, line, declaration, building)
            _floor_height(result, region, line, declaration)
            _head(result, region, line, declaration)
            _hot_water(result, region, line, declaration)
            _systems(result, region, line, declaration)
    return result


def _counts(
    result: Extraction,
    region: RecognizedRegion,
    line: _Line,
    declaration: CollectionDeclaration,
    building: CalcFactSubject,
) -> None:
    for match in _SECTION_WORD_COUNT.finditer(line.text):
        count = _SECTION_WORD_VALUES[match.group("v").lower().replace("ё", "е")]
        start, end = line.start + match.start(), line.start + match.end()
        result.candidates.append(
            _text_candidate(
                declaration,
                "building.sections_count",
                building,
                CalcCountValue(value=count),
                _text_evidence(region, start, end, "Число секций в тексте документа"),
                "Явно указано, из скольких жилых секций состоит здание.",
            )
        )
    for fact_type, pattern in _COUNTS:
        for match in pattern.finditer(line.text):
            if _approximate(result, match, fact_type):
                continue
            count = parse_count(match.group("v"))
            if count is None:
                continue
            start, end = line.start + match.start(), line.start + match.end()
            result.candidates.append(
                _text_candidate(
                    declaration,
                    fact_type,
                    building,
                    CalcCountValue(value=count),
                    _text_evidence(region, start, end, "Фраза в тексте документа"),
                    "Явная фраза в тексте документа.",
                )
            )


def _floor_height(
    result: Extraction, region: RecognizedRegion, line: _Line, declaration: CollectionDeclaration
) -> None:
    for match in _FLOOR_HEIGHT.finditer(line.text):
        fact_type = "floor.height"
        if _approximate(result, match, fact_type):
            continue
        fragment = line.text[match.start() : match.end()]
        unit_text = match.group("u")
        if not unit_text:
            result.issues.append(
                CandidateIssue(
                    CalcInspectionIssueCode.UNIT_MISSING,
                    f"Высота без единицы: «{clip(fragment, 80)}»",
                    fact_type,
                )
            )
            continue
        scope_text = f"{match.group('scope')} этаж {match.group('scope2') or ''}"
        floor = parse_floor_scope(scope_text) or parse_floor_scope(
            re.sub(r"\(|\)", " ", match.group("scope2") or "") + " этаж"
        )
        if floor is None:
            result.issues.append(
                CandidateIssue(
                    CalcInspectionIssueCode.UNSCOPED,
                    f"Высота без номеров этажей: «{clip(fragment, 80)}»",
                    fact_type,
                )
            )
            continue
        unit = parse_unit(unit_text)
        value = parse_decimal_ru(match.group("v"))
        if unit is None or value is None:
            continue
        start, end = line.start + match.start(), line.start + match.end()
        result.candidates.append(
            _text_candidate(
                declaration,
                fact_type,
                CalcFactSubject(building=declaration.building, floor=floor),
                CalcNumberValue(value=stated_text(value), unit=unit),
                _text_evidence(region, start, end, "Фраза в тексте документа"),
                "Явная фраза о высоте этажей в тексте документа.",
            )
        )


def _head(
    result: Extraction, region: RecognizedRegion, line: _Line, declaration: CollectionDeclaration
) -> None:
    for match in _HEAD.finditer(line.text):
        fact_type = "system.inlet_pressure"
        if _approximate(result, match, fact_type):
            continue
        unit_text = match.group("u")
        if not unit_text:
            result.issues.append(
                CandidateIssue(
                    CalcInspectionIssueCode.UNIT_MISSING,
                    f"Напор без единицы: «{clip(line.text[match.start() : match.end()], 80)}»",
                    fact_type,
                )
            )
            continue
        # Напор в метрах — метры водяного столба: это правило, а не догадка.
        unit = "m_h2o" if parse_unit(unit_text) == "m" else parse_unit(unit_text)
        value = parse_decimal_ru(match.group("v"))
        if unit is None or value is None:
            continue
        start, end = line.start + match.start(), line.start + match.end()
        result.candidates.append(
            _text_candidate(
                declaration,
                fact_type,
                CalcFactSubject(
                    building=declaration.building, discipline=CalcDiscipline.VK, system_code="В1"
                ),
                CalcNumberValue(value=stated_text(value), unit=unit),
                _text_evidence(region, start, end, "Гарантированный напор в тексте"),
                "Гарантированный напор из текста; «м» напора — метры водяного столба.",
            )
        )


def _hot_water(
    result: Extraction, region: RecognizedRegion, line: _Line, declaration: CollectionDeclaration
) -> None:
    for match in _HOT_WATER.finditer(line.text):
        fact_type = "system.supply_temperature"
        if _approximate(result, match, fact_type):
            continue
        value = parse_decimal_ru(match.group("v"))
        if value is None:
            continue
        start, end = line.start + match.start(), line.start + match.end()
        result.candidates.append(
            _text_candidate(
                declaration,
                fact_type,
                CalcFactSubject(
                    building=declaration.building, discipline=CalcDiscipline.VK, system_code="Т3"
                ),
                CalcNumberValue(value=stated_text(value), unit="degC"),
                _text_evidence(region, start, end, "Температура горячей воды в тексте"),
                "Температура горячей воды из текста документа.",
            )
        )


def _systems(
    result: Extraction, region: RecognizedRegion, line: _Line, declaration: CollectionDeclaration
) -> None:
    codes = vk_codes(line.text)
    if not codes or not VK_KEYWORDS.search(line.text):
        return
    if not vk_allowed(declaration):
        if (
            declaration.source_class is CalcSourceClass.MEP_DESIGN
            and declaration.discipline is None
        ):
            result.issues.append(
                CandidateIssue(
                    CalcInspectionIssueCode.DISCIPLINE_MISSING,
                    "Обозначения систем найдены, но раздел документа не заявлен",
                    "system.present",
                )
            )
        return
    evidence = _text_evidence(
        region, line.start, line.start + len(line.text), "Упоминание системы в тексте"
    )
    for code in codes:
        result.candidates.append(
            _text_candidate(
                declaration,
                "system.present",
                CalcFactSubject(
                    building=declaration.building, discipline=CalcDiscipline.VK, system_code=code
                ),
                CalcBooleanValue(value=True),
                evidence,
                "Система названа в тексте рядом со словами водопровода или канализации.",
                CalcConfidence.MEDIUM,
            )
        )
