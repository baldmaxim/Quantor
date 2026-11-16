"""Заголовки планов «План … на отм. ±N.NNN» и сопоставление с этажами QMP по отметке.

Отметка в заголовке - метры с тремя знаками после точки или запятой (`+10.540`, `-9.540`,
`+22,780`, `±0.000`). Несколько отметок подряд («на отм. +14.620, +18.700») - лист типовых
этажей. Этаж подбирается в пределах 300 мм; расхождение больше 20 мм - предупреждение;
два и больше кандидатов - неоднозначность, этаж не выбирается.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MATCH_TOLERANCE_MM = 300.0
WARN_TOLERANCE_MM = 20.0

_TITLE = re.compile(r"План[^\n]{0,150}?на\s*отм\.?", re.IGNORECASE)
_NUM = r"([+\-−–±]?)\s*(\d{1,3})[.,](\d{3})(?!\d)"
_FIRST = re.compile(r"\s*" + _NUM)
_NEXT = re.compile(r"\s*(?:[,;]|и)\s*" + _NUM)


@dataclass(frozen=True, slots=True)
class Title:
    text: str
    elevations_mm: tuple[float, ...]


@dataclass(slots=True)
class StoreyMatch:
    elevation_mm: float
    storey: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    delta_mm: float | None = None
    warnings: list[str] = field(default_factory=list)


def _elevation(sign: str, whole: str, frac: str) -> float:
    value = int(whole) * 1000 + int(frac)
    return float(-value if sign in ("-", "−", "–") else value)


def parse_titles(text: str) -> list[Title]:
    """Заголовки планов в тексте страницы (пробелы схлопываются)."""
    flat = re.sub(r"\s+", " ", text)
    titles: list[Title] = []
    for m in _TITLE.finditer(flat):
        pos = m.end()
        elevations: list[float] = []
        pattern = _FIRST
        while (e := pattern.match(flat, pos)) is not None:
            elevations.append(_elevation(*e.groups()))
            pos, pattern = e.end(), _NEXT
        if elevations:
            titles.append(Title(flat[m.start() : pos].strip(), tuple(elevations)))
    return titles


def page_elevations(titles: list[Title]) -> list[float]:
    """Различные отметки заголовков страницы в порядке появления."""
    return list(dict.fromkeys(e for t in titles for e in t.elevations_mm))


def match_storey(
    elevation_mm: float,
    storeys: list[dict[str, Any]],
    tolerance_mm: float = MATCH_TOLERANCE_MM,
    warn_mm: float = WARN_TOLERANCE_MM,
) -> StoreyMatch:
    """Этаж по отметке заголовка; при нескольких кандидатах - без выбора."""
    result = StoreyMatch(elevation_mm)
    near = [s for s in storeys if abs(float(s["elevation_mm"]) - elevation_mm) <= tolerance_mm]
    result.candidates = near
    if not near:
        result.warnings.append(
            f"отм. {elevation_mm / 1000:+.3f}: этажа в пределах {tolerance_mm:.0f} мм нет"
        )
        return result
    if len(near) > 1:
        names = ", ".join(f"{s['name']} ({float(s['elevation_mm']) / 1000:+.3f})" for s in near)
        result.warnings.append(f"отм. {elevation_mm / 1000:+.3f}: неоднозначно - {names}")
        return result
    result.storey = near[0]
    result.delta_mm = round(float(near[0]["elevation_mm"]) - elevation_mm, 1)
    if abs(result.delta_mm) > warn_mm:
        result.warnings.append(
            f"отм. {elevation_mm / 1000:+.3f}: этаж {near[0]['name']} на "
            f"{float(near[0]['elevation_mm']) / 1000:+.3f}, расхождение {result.delta_mm:+.0f} мм"
        )
    return result
