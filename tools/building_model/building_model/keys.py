"""Устойчивые ключи элементов: хеш вида, уровня и геометрии в системе модели.

Ключ не зависит ни от порядка записей plangeom, ни от их id (W0, D0 меняются от прогона к
прогону), ни от направления a/b у стены. Он зависит от геометрии, округлённой до key_round_mm.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from building_model.geometry import Pt, canonical_polygon


def quantize(value: float, step: float) -> int:
    return math.floor(value / step + 0.5)


def _q_pt(p: Pt, step: float) -> tuple[int, int]:
    return (quantize(p[0], step), quantize(p[1], step))


def wall_geometry(a: Pt, b: Pt, step: float) -> str:
    """Концы стены по возрастанию: перестановка a/b даёт ту же строку."""
    first, second = sorted((_q_pt(a, step), _q_pt(b, step)))
    return f"{first[0]},{first[1]};{second[0]},{second[1]}"


def point_geometry(p: Pt, width: float, step: float) -> str:
    x, y = _q_pt(p, step)
    return f"{x},{y};w{quantize(width, step)}"


def polygon_geometry(poly: Sequence[Pt], step: float) -> str:
    quantized = [(float(x), float(y)) for x, y in (_q_pt(p, step) for p in poly)]
    return ";".join(f"{int(x)},{int(y)}" for x, y in canonical_polygon(quantized))


@dataclass(frozen=True)
class KeyRequest:
    prefix: str
    kind: str
    level: str
    geometry: str
    # Детерминированный порядок внутри группы совпавших ключей (полная точность, не округление).
    tiebreak: str


def _digest(request: KeyRequest) -> str:
    raw = f"{request.kind}|{request.level}|{request.geometry}".encode()
    return hashlib.sha256(raw).hexdigest()[:8]


def allocate_keys(requests: Sequence[KeyRequest]) -> list[str]:
    """Ключи в порядке запросов; при коллизии первому по tiebreak — чистый, остальным суффикс."""
    base = [f"{r.prefix}_{_digest(r)}" for r in requests]
    groups: dict[str, list[int]] = defaultdict(list)
    for i, key in enumerate(base):
        groups[key].append(i)
    result = list(base)
    for key, members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda i: (requests[i].tiebreak, i))
        for rank, i in enumerate(members):
            if rank:
                result[i] = f"{key}-{rank}"
    return result
