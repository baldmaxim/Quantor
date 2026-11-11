"""Явная (де)сериализация кандидатов паспорта листа между подпроцессом разбора и исполнителем.

JSON без pickle: подпроцесс пишет файл, родитель проверяет типы каждого поля и не доверяет
содержимому вслепую. Содержимое документов здесь не логируется.
"""

from __future__ import annotations

from typing import Any, Final

from app.services.consistency.dictionaries import SheetKind
from app.services.consistency.sheet_passport import (
    EvidenceSource,
    FieldEvidence,
    PassportCandidate,
)

_STR_FIELDS: Final = (
    "section_mark",
    "stage",
    "building",
    "section",
    "level_from",
    "level_to",
    "code",
    "sheet_number",
    "title",
)
_INT_FIELDS: Final = ("level_from_ordinal", "level_to_ordinal")


def candidate_to_json(candidate: PassportCandidate) -> dict[str, Any]:
    data: dict[str, Any] = {"page_index": candidate.page_index}
    for name in (*_STR_FIELDS, *_INT_FIELDS, "elevation_m"):
        data[name] = getattr(candidate, name)
    data["sheet_kind"] = candidate.sheet_kind.value if candidate.sheet_kind is not None else None
    data["evidence"] = {
        name: {"source": item.source.value, "snippet": item.snippet}
        for name, item in candidate.evidence.items()
    }
    return data


def _opt_str(raw: dict[str, Any], name: str) -> str | None:
    value = raw.get(name)
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"поле {name}: ожидалась строка")


def _opt_int(raw: dict[str, Any], name: str) -> int | None:
    value = raw.get(name)
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return value
    raise ValueError(f"поле {name}: ожидалось целое")


def _opt_float(raw: dict[str, Any], name: str) -> float | None:
    value = raw.get(name)
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise ValueError(f"поле {name}: ожидалось число")


def _evidence(raw: object) -> dict[str, FieldEvidence]:
    if not isinstance(raw, dict):
        raise ValueError("evidence: ожидался объект")
    result: dict[str, FieldEvidence] = {}
    for name, item in raw.items():
        if not isinstance(name, str) or not isinstance(item, dict):
            raise ValueError("evidence: неверная запись")
        source, snippet = item.get("source"), item.get("snippet")
        if not isinstance(source, str) or not isinstance(snippet, str):
            raise ValueError("evidence: неверные поля записи")
        result[name] = FieldEvidence(source=EvidenceSource(source), snippet=snippet)
    return result


def candidate_from_json(raw: object) -> PassportCandidate:
    """Восстанавливает кандидата; неверная форма - ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("кандидат: ожидался объект")
    page_index = _opt_int(raw, "page_index")
    if page_index is None:
        raise ValueError("кандидат: нет page_index")
    kind = _opt_str(raw, "sheet_kind")
    return PassportCandidate(
        page_index=page_index,
        section_mark=_opt_str(raw, "section_mark"),
        sheet_kind=SheetKind(kind) if kind is not None else None,
        stage=_opt_str(raw, "stage"),
        building=_opt_str(raw, "building"),
        section=_opt_str(raw, "section"),
        level_from=_opt_str(raw, "level_from"),
        level_to=_opt_str(raw, "level_to"),
        level_from_ordinal=_opt_int(raw, "level_from_ordinal"),
        level_to_ordinal=_opt_int(raw, "level_to_ordinal"),
        elevation_m=_opt_float(raw, "elevation_m"),
        code=_opt_str(raw, "code"),
        sheet_number=_opt_str(raw, "sheet_number"),
        title=_opt_str(raw, "title"),
        evidence=_evidence(raw.get("evidence")),
    )
