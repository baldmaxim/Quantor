"""Сведение этажей нескольких источников в один список (раздел 4).

Ключ этажа - IfcGlobalId первого встреченного этажа с заменой `$` на `-`. Этаж следующего
источника привязывается к уже известному: тот же GlobalId; иначе отметка в пределах 20 мм
(при нескольких кандидатах - с тем же именем, затем ближайший). Иначе этаж новый.
Так же сводятся этажи с совпадающей отметкой внутри одного файла: отметки в пакете различны.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MATCH_TOLERANCE_MM = 20.0
MAX_NAME = 200


def storey_key(global_id: str) -> str:
    """IfcGlobalId → storey_key: `$` недопустим в пути части, меняется на `-`."""
    key = global_id.replace("$", "-")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
        raise ValueError(f"GlobalId этажа {global_id!r} не годится для storey_key")
    return key


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


@dataclass(slots=True)
class Storey:
    key: str
    name: str
    elevation_mm: float
    elevation_source: str
    global_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class StoreyIndex:
    """Сводный список этажей; `register` возвращает ключ и предупреждения."""

    tolerance_mm: float = MATCH_TOLERANCE_MM
    storeys: list[Storey] = field(default_factory=list)

    def register(
        self, global_id: str, name: str, elevation_mm: float, source: str, origin: str
    ) -> tuple[str, list[str]]:
        for st in self.storeys:
            if global_id in st.global_ids:
                return st.key, []
        near = [s for s in self.storeys if abs(s.elevation_mm - elevation_mm) <= self.tolerance_mm]
        if near:
            same = [s for s in near if _norm(s.name) == _norm(name)]
            pool = same or near
            best = min(pool, key=lambda s: (abs(s.elevation_mm - elevation_mm), s.elevation_mm))
            best.global_ids.add(global_id)
            warnings = []
            if not same:
                warnings.append(
                    f"{origin}: этаж {name!r} ({elevation_mm:.0f}) сведён с {best.name!r} "
                    f"({best.elevation_mm:.0f}) по отметке"
                )
            return best.key, warnings
        warnings = [
            f"{origin}: этаж {name!r} с именем как у {s.name!r}, но отметка "
            f"{elevation_mm:.0f} ≠ {s.elevation_mm:.0f} - это другой этаж"
            for s in self.storeys
            if _norm(s.name) == _norm(name)
        ]
        st = Storey(storey_key(global_id), name[:MAX_NAME], elevation_mm, source, {global_id})
        self.storeys.append(st)
        return st.key, warnings

    def ordered(self) -> list[Storey]:
        return sorted(self.storeys, key=lambda s: s.elevation_mm)


def storey_rows(
    storeys: list[Storey],
    bboxes: dict[str, list[float] | None],
    keep: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Строки storeys.json по возрастанию отметки; высота - до следующего этажа модели."""
    ordered = sorted(storeys, key=lambda s: s.elevation_mm)
    rows: list[dict[str, Any]] = []
    for i, st in enumerate(ordered):
        if keep is not None and st.key not in keep:
            continue
        nxt = ordered[i + 1].elevation_mm if i + 1 < len(ordered) else None
        rows.append(
            {
                "storey_key": st.key,
                "name": st.name,
                "elevation_mm": st.elevation_mm,
                "height_mm": round(nxt - st.elevation_mm, 1) if nxt is not None else None,
                "elevation_source": st.elevation_source,
                "bbox_mm": bboxes.get(st.key),
            }
        )
    return rows
