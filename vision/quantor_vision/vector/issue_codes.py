"""Коды недействительного контура — те же строки, что `GeometryIssueCode` в `apps/api`.

`vision` не импортирует `apps/api`: это разные окружения (ADR-0021). Совпадение значений и текста
`validity.py` с оригиналом проверяет `tests/test_vector.py`, поэтому кандидат из векторизации
отвергается ровно по тем же правилам, по которым его отвергнет портал.
"""

from __future__ import annotations

from enum import StrEnum


class GeometryIssueCode(StrEnum):
    TOO_FEW_VERTICES = "too_few_vertices"
    DUPLICATE_VERTEX = "duplicate_vertex"
    DEGENERATE_RING = "degenerate_ring"
    SELF_INTERSECTION = "self_intersection"
    RING_INTERSECTION = "ring_intersection"
    HOLE_OUTSIDE_OUTER = "hole_outside_outer"
    HOLE_INSIDE_HOLE = "hole_inside_hole"
    TOO_COMPLEX = "too_complex"
