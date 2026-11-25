"""Элементы IFC по этажам, их тип и свойства (раздел 6).

Элемент - `IfcElement`, кроме проёмов и прочих `IfcFeatureElement` и `IfcVirtualElement`.
Этаж элемента: прямое вхождение в этаж (или в помещение этажа) главнее; затем составные
части (агрегаты, вложение, заполнения проёмов) получают этаж родителя. Обход детерминирован.
"""

from __future__ import annotations

import math
from collections import Counter, deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import ifcopenshell.util.element

MAX_PROPS = 24
MAX_PROP_STR = 120
MAX_NAME = 300


@dataclass(frozen=True, slots=True)
class StoreyElements:
    storey_step_id: int
    elements: list[Any]


def is_element(entity: Any) -> bool:
    return bool(
        entity.is_a("IfcElement")
        and not entity.is_a("IfcFeatureElement")
        and not entity.is_a("IfcVirtualElement")
    )


def _contained(spatial: Any) -> Iterator[Any]:
    for rel in getattr(spatial, "ContainsElements", None) or ():
        yield from rel.RelatedElements
    for rel in getattr(spatial, "IsDecomposedBy", None) or ():
        for child in rel.RelatedObjects:
            if child.is_a("IfcSpace"):
                yield from _contained(child)


def _children(entity: Any) -> Iterator[Any]:
    for rel in getattr(entity, "IsDecomposedBy", None) or ():
        yield from rel.RelatedObjects
    for rel in getattr(entity, "IsNestedBy", None) or ():
        yield from rel.RelatedObjects
    for rel in getattr(entity, "HasOpenings", None) or ():
        for fill in getattr(rel.RelatedOpeningElement, "HasFillings", None) or ():
            yield fill.RelatedBuildingElement


def collect_by_storey(model: Any) -> tuple[list[StoreyElements], Counter[str]]:
    """Элементы каждого этажа и счётчик классов элементов вне этажей."""
    storeys = sorted(model.by_type("IfcBuildingStorey"), key=lambda s: s.id())
    assigned: dict[int, int] = {}
    lists: dict[int, list[Any]] = {s.id(): [] for s in storeys}
    for storey in storeys:
        for e in _contained(storey):
            if is_element(e) and e.id() not in assigned:
                assigned[e.id()] = storey.id()
                lists[storey.id()].append(e)
    for storey in storeys:
        queue = deque(lists[storey.id()])
        while queue:
            for child in _children(queue.popleft()):
                if is_element(child) and child.id() not in assigned:
                    assigned[child.id()] = storey.id()
                    lists[storey.id()].append(child)
                    queue.append(child)
    orphans: Counter[str] = Counter(
        e.is_a() for e in model.by_type("IfcElement") if is_element(e) and e.id() not in assigned
    )
    return [StoreyElements(s.id(), lists[s.id()]) for s in storeys], orphans


def type_of(element: Any) -> Any:
    return ifcopenshell.util.element.get_type(element)


def type_name(element: Any, type_obj: Any) -> str | None:
    name = getattr(type_obj, "Name", None) if type_obj is not None else None
    return _clip(name or getattr(element, "ObjectType", None))


def _clip(value: Any, limit: int = MAX_NAME) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit] if text else None


def _scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:MAX_PROP_STR] if value.strip() else None
    if (
        isinstance(value, (list, tuple))
        and value
        and all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value)
    ):
        return "; ".join(str(v) for v in value)[:MAX_PROP_STR]
    return None


def flatten_psets(psets: dict[str, dict[str, Any]]) -> dict[str, str | int | float | bool]:
    """Плоский словарь «набор.параметр → значение», не больше 24 ключей.

    Сначала стандартные `Pset_*`, затем прочие наборы; внутри - порядок источника.
    Пустые, составные и нечисловые (NaN) значения пропускаются, строки режутся до 120 знаков.
    """
    order = sorted(psets, key=lambda n: (not n.startswith("Pset_"),))
    out: dict[str, str | int | float | bool] = {}
    for pset in order:
        for prop, raw in psets[pset].items():
            if prop == "id":
                continue
            value = _scalar(raw)
            if value is None:
                continue
            out[f"{pset}.{prop}"] = value
            if len(out) >= MAX_PROPS:
                return out
    return out


def element_props(element: Any) -> dict[str, str | int | float | bool]:
    try:
        psets = ifcopenshell.util.element.get_psets(element, psets_only=True)
    except Exception:  # битые наборы свойств не должны ронять выгрузку
        return {}
    return flatten_psets(psets)
