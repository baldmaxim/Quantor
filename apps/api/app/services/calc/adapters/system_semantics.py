"""Назначение систем ВК из легенды и записки: «Т3 — водопровод горячей воды подающий» (PROMPT 06).

Обозначение само по себе ничего не значит: в одном проекте Т3 — подающий трубопровод горячей
воды, в другом легенда может сказать иное. Назначение принимается только оттуда, где названа
ровно одна система и её назначение сказано словами:

- строка легенды «Т3 — водопровод горячей воды подающий»;
- строка таблицы условных обозначений «| Т3 | Водопровод горячей воды подающий |».

Строка «Т3, Т4 — горячее водоснабжение» назначения каждой системы не определяет и пропускается.
Если слова указывают на два назначения сразу, строка тоже пропускается: догадки нет.
"""

from __future__ import annotations

import re
from typing import Final

from app.contracts.calc.enums import CalcConfidence, CalcDiscipline, CalcFactMethod
from app.contracts.calc.facts import CalcRegionTextLocator
from app.contracts.calc.subjects import CalcFactSubject
from app.contracts.calc.values import CalcEnumValue
from app.services.calc.adapters.candidates import (
    EXCERPT_LIMIT,
    LABEL_LIMIT,
    CalcCandidate,
    CandidateEvidence,
    CollectionDeclaration,
    Extraction,
    clip,
)
from app.services.calc.adapters.parsed import ParsedRegion
from app.services.calc.adapters.recognized import is_metadata_line
from app.services.calc.adapters.text_values import TEXT_EXTRACTOR, vk_allowed, vk_codes

_LEGEND = re.compile(r"^\W{0,3}(?P<code>[ВBТTКK]\s?[1-4])\s*[—–\-:]\s*(?P<text>\S.{3,})$")
_FUNCTIONS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("HOT_WATER_CIRCULATION", re.compile(r"циркуляц", re.IGNORECASE)),
    ("HOT_WATER_SUPPLY", re.compile(r"горяч\w*\s+вод|горяч\w*\s+водоснабжен|\bгвс\b", re.I)),
    ("COLD_WATER", re.compile(r"хоз\w*[-.\s]*питьев|холодн\w*\s+вод", re.IGNORECASE)),
    ("DOMESTIC_SEWER", re.compile(r"бытов\w*\s+канализац|канализац\w*\s+бытов", re.IGNORECASE)),
)
_SUPPLY_WORD = re.compile(r"подающ|подач", re.IGNORECASE)


def function_of(text: str) -> tuple[str, CalcConfidence] | None:
    """Назначение по словам описания. Два назначения сразу — None: не угадываем."""
    found = [value for value, pattern in _FUNCTIONS if pattern.search(text)]
    if "HOT_WATER_CIRCULATION" in found:
        found = [item for item in found if item != "HOT_WATER_SUPPLY"]
    if len(found) != 1:
        return None
    value = found[0]
    if value == "HOT_WATER_SUPPLY" and not _SUPPLY_WORD.search(text):
        return value, CalcConfidence.MEDIUM
    return value, CalcConfidence.HIGH


def _pairs(line: str) -> list[tuple[str, str]]:
    """Пары «обозначение — описание» строки легенды или строки таблицы."""
    stripped = line.strip()
    if stripped.startswith("|"):
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        codes = [cell for cell in cells if vk_codes(cell) and len(cell) <= 4]
        texts = [cell for cell in cells if cell not in codes and len(cell) > 4]
        if len(codes) == 1 and len(texts) == 1:
            return [(codes[0], texts[0])]
        return []
    match = _LEGEND.match(stripped)
    if match is None or len(vk_codes(stripped)) != 1:
        return []
    return [(match.group("code"), match.group("text"))]


def extract_system_functions(
    parsed: tuple[ParsedRegion, ...], declaration: CollectionDeclaration
) -> Extraction:
    result = Extraction()
    if not vk_allowed(declaration):
        return result
    for parsed_region in parsed:
        region = parsed_region.region
        offset = 0
        for line in region.text.splitlines(keepends=True):
            text = line.rstrip("\r\n")
            start = offset
            offset += len(line)
            if is_metadata_line(text):
                continue
            for raw_code, description in _pairs(text):
                codes = vk_codes(raw_code)
                meaning = function_of(description)
                if len(codes) != 1 or meaning is None:
                    continue
                value, confidence = meaning
                result.candidates.append(
                    CalcCandidate(
                        extractor=TEXT_EXTRACTOR,
                        source_class=declaration.source_class,
                        fact_type="system.function",
                        subject=CalcFactSubject(
                            building=declaration.building,
                            discipline=CalcDiscipline.VK,
                            system_code=codes[0],
                        ),
                        value=CalcEnumValue(value=value),
                        method=CalcFactMethod.DOCUMENT_EXPLICIT,
                        confidence=confidence,
                        note="Назначение системы из легенды или записки: обозначение и слова.",
                        evidence=(
                            CandidateEvidence(
                                region=region,
                                locator=CalcRegionTextLocator(start=start, end=start + len(text)),
                                label=clip("Назначение системы в легенде", LABEL_LIMIT),
                                excerpt=clip(text, EXCERPT_LIMIT),
                            ),
                        ),
                    )
                )
    return result
