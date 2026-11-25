"""Сведение этажей нескольких источников по зданиям (раздел 4).

Здания. Здание файла привязывается к уже известному: тот же GlobalId; иначе то же имя; иначе,
если и в файле, и в пакете пока по одному зданию, - к нему (разделы одного дома АР, КР, ВК
выгружены из разных моделей, у их IfcBuilding разные GlobalId и имена). Иначе здание новое.

Этажи. Ключ этажа - IfcGlobalId первого встреченного этажа с заменой `$` на `-`. Этаж
следующего источника привязывается к уже известному этажу того же здания: тот же GlobalId;
иначе отметка в пределах 20 мм (при нескольких кандидатах - с тем же именем, затем ближайший).
Иначе этаж новый. Так же сводятся этажи с совпадающей отметкой внутри одного здания: отметки
этажей здания различны. Этаж вне здания сводится с этажом любого здания и получает его здание.

Пакет, где этажи лежат в одном здании, пишется как раньше: один список по отметке, без полей
здания. Если зданий с этажами два и больше, этажи идут по зданиям (в порядке их появления),
внутри здания по отметке, высота - до следующего этажа того же здания, у строк есть
`building_key` и `building_name`; этажи вне зданий - последними, без этих полей.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

MATCH_TOLERANCE_MM = 20.0
MAX_NAME = 200


def storey_key(global_id: str) -> str:
    """IfcGlobalId → storey_key (и building_key): `$` недопустим в пути части, меняется на `-`."""
    key = global_id.replace("$", "-")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
        raise ValueError(f"GlobalId {global_id!r} не годится для ключа этажа или здания")
    return key


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


@dataclass(slots=True)
class Building:
    key: str
    name: str
    global_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class BuildingIndex:
    """Сводный список зданий всех файлов пакета."""

    buildings: list[Building] = field(default_factory=list)

    def register_file(self, raw: Sequence[tuple[str, str]]) -> dict[str, str]:
        """Здания одного файла `(GlobalId, имя)` → ключ сводного здания по GlobalId."""
        single = len(raw) == 1 and len(self.buildings) == 1
        taken: set[str] = set()
        out: dict[str, str] = {}
        for global_id, name in raw:
            found = next((b for b in self.buildings if global_id in b.global_ids), None)
            if found is None and _norm(name):
                found = next(
                    (
                        b
                        for b in self.buildings
                        if b.key not in taken and _norm(b.name) == _norm(name)
                    ),
                    None,
                )
            if found is None and single:
                found = self.buildings[0]
            if found is None:
                found = Building(storey_key(global_id), name[:MAX_NAME])
                self.buildings.append(found)
            found.global_ids.add(global_id)
            taken.add(found.key)
            out[global_id] = found.key
        return out


@dataclass(slots=True)
class Storey:
    key: str
    name: str
    elevation_mm: float
    elevation_source: str
    global_ids: set[str] = field(default_factory=set)
    building: str | None = None


def _same_building(a: str | None, b: str | None) -> bool:
    """Этаж вне здания (`None`) сводится с этажом любого здания."""
    return a is None or b is None or a == b


@dataclass(slots=True)
class StoreyIndex:
    """Сводный список этажей; `register` возвращает ключ и предупреждения."""

    tolerance_mm: float = MATCH_TOLERANCE_MM
    storeys: list[Storey] = field(default_factory=list)

    def register(
        self,
        global_id: str,
        name: str,
        elevation_mm: float,
        source: str,
        origin: str,
        building: str | None = None,
    ) -> tuple[str, list[str]]:
        for st in self.storeys:
            if global_id in st.global_ids:
                return st.key, []
        pool = [s for s in self.storeys if _same_building(s.building, building)]
        near = [s for s in pool if abs(s.elevation_mm - elevation_mm) <= self.tolerance_mm]
        if near:
            same = [s for s in near if _norm(s.name) == _norm(name)]
            best = min(
                same or near, key=lambda s: (abs(s.elevation_mm - elevation_mm), s.elevation_mm)
            )
            best.global_ids.add(global_id)
            if best.building is None:
                best.building = building
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
            for s in pool
            if _norm(s.name) == _norm(name)
        ]
        st = Storey(
            storey_key(global_id), name[:MAX_NAME], elevation_mm, source, {global_id}, building
        )
        self.storeys.append(st)
        return st.key, warnings

    def ordered(self) -> list[Storey]:
        return sorted(self.storeys, key=lambda s: s.elevation_mm)


def _groups(
    storeys: list[Storey], buildings: Sequence[Building]
) -> list[tuple[Building | None, list[Storey]]]:
    """Этажи по зданиям: одно здание (или ни одного) - один общий список, как раньше."""
    used = {s.building for s in storeys if s.building is not None}
    by_elevation = sorted(storeys, key=lambda s: s.elevation_mm)
    if len(used) < 2:
        return [(None, by_elevation)]
    groups: list[tuple[Building | None, list[Storey]]] = [
        (b, [s for s in by_elevation if s.building == b.key]) for b in buildings if b.key in used
    ]
    known = {b.key for b in buildings}
    outside = [s for s in by_elevation if s.building not in known]
    if outside:
        groups.append((None, outside))
    return groups


def storey_rows(
    storeys: list[Storey],
    bboxes: dict[str, list[float] | None],
    keep: set[str] | None = None,
    buildings: Sequence[Building] = (),
) -> list[dict[str, Any]]:
    """Строки storeys.json по зданиям и по возрастанию отметки; высота - до следующего этажа
    того же здания."""
    rows: list[dict[str, Any]] = []
    for building, ordered in _groups(storeys, buildings):
        for i, st in enumerate(ordered):
            if keep is not None and st.key not in keep:
                continue
            nxt = ordered[i + 1].elevation_mm if i + 1 < len(ordered) else None
            row: dict[str, Any] = {
                "storey_key": st.key,
                "name": st.name,
                "elevation_mm": st.elevation_mm,
                "height_mm": round(nxt - st.elevation_mm, 1) if nxt is not None else None,
                "elevation_source": st.elevation_source,
                "bbox_mm": bboxes.get(st.key),
            }
            if building is not None:
                row["building_key"] = building.key
                row["building_name"] = building.name
            rows.append(row)
    return rows
