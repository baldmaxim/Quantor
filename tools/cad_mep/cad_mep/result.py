"""Результат планировщика трасс: 3D-линии, узлы, сведения по квартирам и замечания."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import pairwise

from cad_mep.heatdev import HeatRoom
from cad_mep.issues import Issue

Pt = tuple[float, float]
Pt3 = tuple[float, float, float]


@dataclass
class Line3D:
    layer: str
    pts: list[Pt3]
    apt: int | None = None  # None — общий участок / стояк
    kind: str = "route"  # route | jumper | riser | leadin


@dataclass
class NodeMark:
    layer: str  # M-NODE | M-RISER
    kind: str  # collector | device | meter | riser | cabinet | pk
    xy: Pt
    z: float
    apt: int | None = None
    system: str | None = None
    room: str | None = None
    label: str | None = None  # подпись узла в DXF (марка и диаметр стояка из реестра)


@dataclass
class Result:
    lines: list[Line3D] = field(default_factory=list)
    nodes: list[NodeMark] = field(default_factory=list)
    per_apt: dict[int, dict[str, object]] = field(default_factory=dict)
    fire: dict[str, object] | None = None
    shaft_use: dict[str, list[str]] = field(default_factory=dict)
    # стояки шахты по местам: слой, система, марка, роль, Ø (марка и др. — только по реестру)
    shaft_risers: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    heat_rooms: list[HeatRoom] = field(default_factory=list)
    # осевые пути лучей по квартирам (узлы сетки): проверка «дерево без петель»
    beam_paths: dict[int, list[list[Pt]]] = field(default_factory=dict)


def len3(pts: list[Pt3]) -> float:
    return float(
        sum(
            math.sqrt(sum((a - b) ** 2 for a, b in zip(p, q, strict=True)))
            for p, q in pairwise(pts)
        )
    )


def plan_len(pts: list[Pt3]) -> float:
    return float(sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in pairwise(pts)))
