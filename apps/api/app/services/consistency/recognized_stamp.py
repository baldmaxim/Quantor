"""Штамп распознавалки как источник паспорта листа (ADR-0043).

Слияние чистое, без БД: поля штампа распознавалки (шифр, стадия, номер листа, название)
перекрывают то, что нашёл текстовый разбор pypdf; пустое поле штампа оставляет прежнее значение.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Final

from app.contracts.calc.enums import CalcDocumentStage
from app.services.calc.adapters.recognized import Stamp, StampField, stage_from_mark
from app.services.consistency.sheet_passport import (
    SNIPPET_MAX,
    EvidenceSource,
    FieldEvidence,
    PassportCandidate,
)
from app.services.consistency.sheet_stamp import SPACES_RE, compact_code

_TITLE_MAX_LEN: Final = 200
_FIRST_INT_RE: Final = re.compile(r"\d+")
_STAGE_LABELS: Final = {CalcDocumentStage.P: "П", CalcDocumentStage.RD: "РД"}


def _evidence(field: StampField) -> FieldEvidence:
    snippet = SPACES_RE.sub(" ", field.value).strip()[:SNIPPET_MAX]
    return FieldEvidence(EvidenceSource.RECOGNIZED_STAMP, snippet)


def apply_recognized_stamp(candidate: PassportCandidate, stamp: Stamp) -> PassportCandidate:
    """Кандидат, где `code`, `stage`, `sheet_number`, `title` взяты из штампа распознавалки."""
    evidence = dict(candidate.evidence)

    def pick(
        name: str, value: str | None, field: StampField | None, current: str | None
    ) -> str | None:
        if not value or field is None:
            return current
        evidence[name] = _evidence(field)
        return value

    code = None if stamp.code is None else compact_code(stamp.code.value)
    stage = None if stamp.stage is None else stage_from_mark(stamp.stage.value)
    number = None if stamp.sheet is None else _FIRST_INT_RE.search(stamp.sheet.value)
    title = None if stamp.name is None else SPACES_RE.sub(" ", stamp.name.value).strip()
    return replace(
        candidate,
        code=pick("code", code, stamp.code, candidate.code),
        stage=pick("stage", stage and _STAGE_LABELS[stage], stamp.stage, candidate.stage),
        sheet_number=pick(
            "sheet_number", number and number.group(0), stamp.sheet, candidate.sheet_number
        ),
        title=pick("title", title and title[:_TITLE_MAX_LEN], stamp.name, candidate.title),
        evidence=evidence,
    )
