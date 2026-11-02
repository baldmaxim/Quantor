"""Внутренние неизменяемые записи нормализатора (в системе координат модели)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from building_model.geometry import Pt

OpeningKind = Literal["door", "window", "opening"]
HingeEnd = Literal["a", "b"]
OpensTo = Literal["left", "right"]
HostStatus = Literal["hosted", "no_host", "ambiguous"]
AxisSource = Literal["segments", "outline", "mixed"]


def natural_key(identifier: str) -> tuple[str, int, str]:
    """Порядок id вида W12 < W100: буквы, затем число; детерминирован и не зависит от входа."""
    m = re.fullmatch(r"([^\d]*)(\d+)(.*)", identifier)
    if m is None:
        return (identifier, -1, "")
    return (m.group(1), int(m.group(2)), m.group(3))


@dataclass(frozen=True)
class Piece:
    """Один участок осевой линии стены plangeom (walls[].segments[])."""

    a: Pt
    b: Pt
    thickness: float
    role: str
    wall_id: str
    # True: ось выведена из контура стены без осевых линий, а не прочитана из segments.
    outline: bool = False

    @property
    def length(self) -> float:
        return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])


@dataclass(frozen=True)
class Rejected:
    code: str
    piece: Piece


@dataclass(frozen=True)
class OutlineOutcome:
    """Судьба стены plangeom без осевых участков: не пропадает молча."""

    wall_id: str
    area_m2: float
    # used | filtered | duplicate | compact | not_rectangle
    outcome: str
    length_mm: float
    a: Pt | None
    b: Pt | None


@dataclass(frozen=True)
class Column:
    wall_id: str
    polygon: tuple[Pt, ...]
    thickness: float


@dataclass(frozen=True)
class MergedWall:
    a: Pt
    b: Pt
    thickness: float
    role: str
    wall_ids: tuple[str, ...]
    pieces: int
    bridged_openings: tuple[str, ...]
    axis_source: AxisSource

    @property
    def length(self) -> float:
        return math.hypot(self.b[0] - self.a[0], self.b[1] - self.a[1])


@dataclass(frozen=True)
class DanglingEnd:
    wall_index: int
    end: str
    point: Pt
    near_opening: bool
    # Расстояние от конца до грани ближайшей другой стены; None, если дальше зоны отчёта.
    gap_to_face_mm: float | None


@dataclass(frozen=True)
class LeafDraft:
    hinge: Pt
    end_a: Pt
    end_b: Pt
    plangeom_host: str | None


@dataclass(frozen=True)
class OpeningDraft:
    """Дверь (одна или пара полотен), окно или пустой проём до поиска хозяина."""

    kind: OpeningKind
    ids: tuple[str, ...]
    width: float
    a: Pt | None
    b: Pt | None
    leaves: tuple[LeafDraft, ...]
    gap_mm: float | None
    pair_missing: bool


@dataclass(frozen=True)
class Swing:
    hinge_at: HingeEnd  # конец оси стены, у которого петля
    opens_to: OpensTo  # сторона относительно оси a -> b


@dataclass(frozen=True)
class HostResult:
    draft: OpeningDraft
    status: HostStatus
    wall_index: int | None
    midpoint: Pt
    span: tuple[Pt, Pt]
    offset_mm: float | None
    swings: tuple[Swing, ...]
    candidates: int
