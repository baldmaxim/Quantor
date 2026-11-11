"""Распознанный документ глазами адаптеров: блоки текста в порядке документа и штамп листа.

Текст блока — ровно то, что импорт legacy-v1 положил в `Region.raw_content_md`. В начале тела
стоят строки метаданных распознавалки (`> **Created:**`, `> **Crop:**`, `> **Stamp:**`), в конце
иногда — разделитель следующей страницы (`## Page N`). Метаданные — не содержание: из штампа
берутся только шифр, стадия и название листа; объект, организация и изменения не читаются.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from app.contracts.calc.enums import CalcDiscipline, CalcDocumentStage, CalcSourceClass
from app.services.consistency.dictionaries import match_section_mark, normalize_mark

TEXT_BLOCK: Final = "text"
IMAGE_BLOCK: Final = "image"


@dataclass(frozen=True, slots=True)
class RecognizedRegion:
    """Блок распознанного пакета: только то, что нужно адаптерам."""

    id: uuid.UUID
    sheet_id: uuid.UUID
    page_index: int
    block_type: str
    text: str
    bbox: tuple[float, float, float, float] | None

    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RecognizedDocument:
    revision_id: uuid.UUID
    regions: tuple[RecognizedRegion, ...]
    """В порядке документа: страница, затем номер блока."""

    def text_regions(self) -> Iterator[RecognizedRegion]:
        return (region for region in self.regions if region.block_type == TEXT_BLOCK)


_METADATA = re.compile(r"^\s*>")
_PAGE_SEPARATOR = re.compile(r"^\s*##\s*Page\s+\d+\s*$", re.IGNORECASE)


def is_metadata_line(line: str) -> bool:
    """Строка метаданных распознавалки или разделитель страницы — не содержание документа."""
    return bool(_METADATA.match(line) or _PAGE_SEPARATOR.match(line))


# ------------------------------------------------------------------------------------ штамп

_STAMP_LINE = re.compile(r"^\s*>\s*\*\*Stamp:\*\*(?P<body>.*)$", re.MULTILINE)
_STAMP_KEYS = "Code|Stage|Sheet|Object|Name|Organization|Revisions"
_STAMP_FIELD = re.compile(
    rf"(?P<key>{_STAMP_KEYS}):\s*(?P<value>.*?)\s*(?=\|\s*(?:{_STAMP_KEYS}):|$)"
)
_READ_KEYS: Final = frozenset({"Code", "Stage", "Sheet", "Name"})


@dataclass(frozen=True, slots=True)
class StampField:
    value: str
    start: int
    end: int
    """Смещения значения в тексте блока — для свидетельства."""


@dataclass(frozen=True, slots=True)
class Stamp:
    code: StampField | None
    stage: StampField | None
    name: StampField | None


def parse_stamp(text: str) -> Stamp | None:
    """Шифр, стадия и название листа из строки штампа. Остальные поля не читаются вовсе."""
    line = _STAMP_LINE.search(text)
    if line is None:
        return None
    base = line.start("body")
    found: dict[str, StampField] = {}
    for match in _STAMP_FIELD.finditer(line.group("body")):
        key = match.group("key")
        value = match.group("value").strip()
        if key in _READ_KEYS and value and key not in found:
            found[key] = StampField(
                value, base + match.start("value"), base + match.start("value") + len(value)
            )
    return Stamp(code=found.get("Code"), stage=found.get("Stage"), name=found.get("Name"))


def stage_from_mark(mark: str) -> CalcDocumentStage | None:
    """«П», «ПД» — проектная стадия; «Р», «РД» — рабочая. Прочее стадией не считается."""
    cleaned = re.sub(r"[\s.]", "", normalize_mark(mark))
    if cleaned in {"П", "ПД"}:
        return CalcDocumentStage.P
    if cleaned in {"Р", "РД"}:
        return CalcDocumentStage.RD
    return None


# Марки разделов по шифру. Порядок важен: сначала длинные («ИОС2» раньше «ИОС»).
_SECTION_MARKS: Final[tuple[tuple[str, CalcSourceClass, CalcDiscipline | None], ...]] = (
    ("ИОС1", CalcSourceClass.MEP_DESIGN, CalcDiscipline.EOM),
    ("ИОС2", CalcSourceClass.MEP_DESIGN, CalcDiscipline.VK),
    ("ИОС3", CalcSourceClass.MEP_DESIGN, CalcDiscipline.VK),
    ("ИОС4", CalcSourceClass.MEP_DESIGN, CalcDiscipline.OV),
    ("ИОС5", CalcSourceClass.MEP_DESIGN, CalcDiscipline.SS),
    ("НВК", CalcSourceClass.MEP_DESIGN, CalcDiscipline.VK),
    ("ЭОМ", CalcSourceClass.MEP_DESIGN, CalcDiscipline.EOM),
    ("АР", CalcSourceClass.ARCHITECTURE, None),
    ("ВК", CalcSourceClass.MEP_DESIGN, CalcDiscipline.VK),
    ("ОВ", CalcSourceClass.MEP_DESIGN, CalcDiscipline.OV),
    ("ЭС", CalcSourceClass.MEP_DESIGN, CalcDiscipline.EOM),
    ("ЭМ", CalcSourceClass.MEP_DESIGN, CalcDiscipline.EOM),
    ("СС", CalcSourceClass.MEP_DESIGN, CalcDiscipline.SS),
    ("ПЗ", CalcSourceClass.EXPLANATORY_NOTE, None),
    ("СП", CalcSourceClass.PROJECT_COMPOSITION, None),
)


_ALLOWED_MARKS: Final = frozenset(mark for mark, _, _ in _SECTION_MARKS)


def section_from_code(code: str) -> str | None:
    """Марка раздела из шифра «ПД-00000000-АР.С-КОР1» → «АР»; «…-ОВ0-1» → «ОВ».

    Сопоставление — общий словарь контура согласованности; набор марок — политика calc.
    Алиасы словаря («ОВиК») calc не использует: поведение не меняется.
    """
    return match_section_mark(code, allowed=_ALLOWED_MARKS, with_aliases=False)


def class_for_section(mark: str) -> tuple[CalcSourceClass, CalcDiscipline | None] | None:
    for known, source_class, discipline in _SECTION_MARKS:
        if known == mark:
            return source_class, discipline
    return None


@dataclass(frozen=True, slots=True)
class StampSummary:
    stage: CalcDocumentStage | None
    """Стадия, если штампы документа единодушны."""
    section: str | None
    """Марка раздела, если её дают не меньше 80 % штампов."""


def summarize_stamps(stamps: list[Stamp]) -> StampSummary:
    stages = {
        stage
        for stamp in stamps
        if stamp.stage is not None and (stage := stage_from_mark(stamp.stage.value)) is not None
    }
    stage = next(iter(stages)) if len(stages) == 1 else None
    marks = Counter(
        mark
        for stamp in stamps
        if stamp.code is not None and (mark := section_from_code(stamp.code.value)) is not None
    )
    section: str | None = None
    if marks:
        mark, count = marks.most_common(1)[0]
        if count * 5 >= 4 * sum(marks.values()):
            section = mark
    return StampSummary(stage=stage, section=section)
