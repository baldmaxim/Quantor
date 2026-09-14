"""Валидность многоугольника с отверстиями (промт 05, ADR-0026).

Политика: самопересекающийся контур недействителен, площади у него нет — никогда не 0 м².
Геометрия не чинится молча. Здесь проверяется детерминированный валидатор: ровно те случаи,
которые перечисляет промт, и те, на которых ломаются наивные реализации, — касание вершиной,
наложение на одной прямой, почти касание.
"""

from __future__ import annotations

import math

import pytest

from app.domain import GeometryIssueCode
from app.services.geometry.validity import MAX_CANDIDATE_PAIRS, GeometryIssue, validate_polygon

SQUARE = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]


def _code(issue: GeometryIssue | None) -> GeometryIssueCode | None:
    return issue.code if issue is not None else None


class TestOuterRing:
    def test_convex_polygon_is_valid(self) -> None:
        assert validate_polygon(SQUARE) is None

    def test_concave_polygon_is_valid(self) -> None:
        # «Наконечник стрелы»: внутренний угол больше 180°, но рёбра не пересекаются.
        assert (
            validate_polygon([(0.1, 0.1), (0.9, 0.1), (0.5, 0.5), (0.9, 0.9), (0.1, 0.9)]) is None
        )

    def test_winding_direction_does_not_matter(self) -> None:
        assert validate_polygon(list(reversed(SQUARE))) is None

    def test_bow_tie_is_a_self_intersection(self) -> None:
        issue = validate_polygon([(0.1, 0.1), (0.9, 0.9), (0.9, 0.1), (0.1, 0.9)])

        assert issue == GeometryIssue(
            GeometryIssueCode.SELF_INTERSECTION, ring=0, edge=0, other_ring=0, other_edge=2
        )
        assert "пересекаются" in issue.message

    def test_duplicate_consecutive_vertex(self) -> None:
        issue = validate_polygon([(0.1, 0.1), (0.9, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)])

        assert issue == GeometryIssue(GeometryIssueCode.DUPLICATE_VERTEX, ring=0, vertex=2)

    def test_zero_length_closing_edge(self) -> None:
        # Замыкание повторением первой точки — ребро нулевой длины между последней и первой.
        issue = validate_polygon([*SQUARE, SQUARE[0]])

        assert issue == GeometryIssue(GeometryIssueCode.DUPLICATE_VERTEX, ring=0, vertex=0)

    def test_collinear_ring_is_degenerate(self) -> None:
        issue = validate_polygon([(0.1, 0.1), (0.5, 0.5), (0.9, 0.9), (0.3, 0.3)])

        assert _code(issue) is GeometryIssueCode.DEGENERATE_RING

    def test_two_distinct_points_repeated_is_degenerate(self) -> None:
        assert _code(validate_polygon([(0.1, 0.1), (0.9, 0.9), (0.1, 0.1), (0.9, 0.9)])) is (
            GeometryIssueCode.DEGENERATE_RING
        )

    def test_too_few_vertices(self) -> None:
        assert (
            _code(validate_polygon([(0.1, 0.1), (0.9, 0.9)])) is GeometryIssueCode.TOO_FEW_VERTICES
        )

    def test_spike_folding_back_along_an_edge(self) -> None:
        # Ребро возвращается по предыдущему: соседние рёбра накладываются на одной прямой.
        issue = validate_polygon([(0.1, 0.1), (0.9, 0.1), (0.5, 0.1), (0.5, 0.9)])

        assert _code(issue) is GeometryIssueCode.SELF_INTERSECTION

    def test_collinear_straight_vertex_is_valid(self) -> None:
        # Вершина посреди прямого участка — законна: соседние рёбра не накладываются.
        assert (
            validate_polygon([(0.1, 0.1), (0.5, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]) is None
        )

    def test_figure_eight_touching_at_a_vertex_is_invalid(self) -> None:
        # Две петли с общей вершиной: касание — тоже пересечение, площадь неоднозначна.
        issue = validate_polygon(
            [(0.5, 0.5), (0.1, 0.1), (0.1, 0.9), (0.5, 0.5), (0.9, 0.9), (0.9, 0.1)]
        )

        assert _code(issue) is GeometryIssueCode.SELF_INTERSECTION

    def test_vertex_touching_a_non_adjacent_edge_is_invalid(self) -> None:
        # Вершина ровно на противоположном ребре — касание.
        issue = validate_polygon([(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.1 + 0.0), (0.1, 0.9)])

        assert _code(issue) is GeometryIssueCode.SELF_INTERSECTION

    def test_near_touching_vertex_is_valid(self) -> None:
        # Та же вершина на расстоянии 1e-12 от ребра — не касание. Допуска нет: точные предикаты.
        assert (
            validate_polygon([(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.1 + 1e-12), (0.1, 0.9)])
            is None
        )

    def test_near_parallel_thin_sliver_is_valid(self) -> None:
        # Узкая щель между двумя почти касающимися рёбрами.
        assert (
            validate_polygon(
                [
                    (0.1, 0.1),
                    (0.9, 0.1),
                    (0.9, 0.5),
                    (0.2, 0.5),
                    (0.2, 0.5 + 1e-15),
                    (0.9, 0.5 + 2e-15),
                    (0.9, 0.9),
                    (0.1, 0.9),
                ]
            )
            is None
        )

    def test_float_rounding_does_not_create_false_intersections(self) -> None:
        # Точка, «почти» лежащая на прямой через две другие: в double ориентация на грани нуля,
        # решает точная арифметика — и ответ одинаков при любом порядке вершин.
        ring = [(0.1, 0.1), (0.3, 0.7), (0.7, 0.3 + 1e-17), (0.9, 0.9), (0.2, 0.95)]
        results = {
            _code(validate_polygon(ring[shift:] + ring[:shift])) for shift in range(len(ring))
        }

        assert len(results) == 1


class TestHoles:
    def test_hole_strictly_inside_is_valid(self) -> None:
        assert validate_polygon(SQUARE, [[(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)]]) is None

    def test_several_separate_holes_are_valid(self) -> None:
        holes = [
            [(0.2, 0.2), (0.3, 0.2), (0.3, 0.3)],
            [(0.6, 0.6), (0.8, 0.6), (0.8, 0.8), (0.6, 0.8)],
        ]
        assert validate_polygon(SQUARE, holes) is None

    def test_hole_outside_the_outer_ring(self) -> None:
        issue = validate_polygon(SQUARE, [[(0.92, 0.92), (0.99, 0.92), (0.99, 0.99)]])

        assert issue == GeometryIssue(GeometryIssueCode.HOLE_OUTSIDE_OUTER, ring=1)

    def test_hole_crossing_the_outer_ring(self) -> None:
        issue = validate_polygon(SQUARE, [[(0.5, 0.5), (0.95, 0.5), (0.95, 0.6), (0.5, 0.6)]])

        assert _code(issue) is GeometryIssueCode.RING_INTERSECTION
        assert issue is not None and issue.ring == 1 and issue.other_ring == 0

    def test_hole_touching_the_outer_ring(self) -> None:
        issue = validate_polygon(SQUARE, [[(0.1, 0.4), (0.6, 0.4), (0.6, 0.6)]])

        assert _code(issue) is GeometryIssueCode.RING_INTERSECTION

    def test_overlapping_holes(self) -> None:
        holes = [
            [(0.3, 0.3), (0.6, 0.3), (0.6, 0.6), (0.3, 0.6)],
            [(0.5, 0.5), (0.8, 0.5), (0.8, 0.8), (0.5, 0.8)],
        ]
        issue = validate_polygon(SQUARE, holes)

        assert issue is not None and issue.code is GeometryIssueCode.RING_INTERSECTION
        assert (issue.ring, issue.other_ring) == (2, 1)

    def test_hole_inside_another_hole(self) -> None:
        holes = [
            [(0.3, 0.3), (0.7, 0.3), (0.7, 0.7), (0.3, 0.7)],
            [(0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)],
        ]

        assert validate_polygon(SQUARE, holes) == GeometryIssue(
            GeometryIssueCode.HOLE_INSIDE_HOLE, ring=2, other_ring=1
        )

    def test_hole_with_own_defect_is_reported_on_that_hole(self) -> None:
        issue = validate_polygon(SQUARE, [[(0.4, 0.4), (0.6, 0.4), (0.6, 0.4), (0.5, 0.6)]])

        assert issue == GeometryIssue(GeometryIssueCode.DUPLICATE_VERTEX, ring=1, vertex=2)

    def test_hole_in_a_concave_notch_is_outside(self) -> None:
        # Отверстие в «выемке» вогнутого контура — снаружи, хотя внутри его охвата.
        outer = [(0.1, 0.1), (0.9, 0.1), (0.5, 0.5), (0.9, 0.9), (0.1, 0.9)]
        issue = validate_polygon(outer, [[(0.75, 0.45), (0.85, 0.45), (0.85, 0.55)]])

        assert _code(issue) is GeometryIssueCode.HOLE_OUTSIDE_OUTER


class TestOrderAndScale:
    def test_first_problem_in_a_fixed_order(self) -> None:
        # Внешний контур с нулевым ребром и отверстие вне контура: сначала — устройство колец.
        issue = validate_polygon(
            [(0.1, 0.1), (0.9, 0.1), (0.9, 0.1), (0.9, 0.9)],
            [[(0.95, 0.95), (0.99, 0.95), (0.99, 0.99)]],
        )

        assert _code(issue) is GeometryIssueCode.DUPLICATE_VERTEX

    def test_grid_and_brute_force_agree_on_the_first_pair(self) -> None:
        # Малый и крупный контур с одной и той же первой парой рёбер: ответ не зависит от способа
        # отбора пар (перебор до 64 рёбер, сетка — дальше).
        # Неравномерные углы без генератора случайных чисел: дробные части кратных золотого
        # сечения — детерминированно и воспроизводимо.
        golden = (math.sqrt(5) - 1) / 2
        for size in (12, 40, 200, 1500):
            angles = sorted((k * golden) % 1.0 * 2 * math.pi for k in range(size))
            ring = [(0.5 + 0.4 * math.cos(a), 0.5 + 0.4 * math.sin(a)) for a in angles]
            assert validate_polygon(ring) is None
            crossed = list(ring)
            crossed[1], crossed[size // 2] = crossed[size // 2], crossed[1]
            issue = validate_polygon(crossed)
            assert issue is not None and issue.code is GeometryIssueCode.SELF_INTERSECTION

    def test_large_valid_outline_passes_within_the_budget(self) -> None:
        count = 10_000
        ring = [
            (
                0.5 + 0.4 * math.cos(2 * math.pi * k / count),
                0.5 + 0.4 * math.sin(2 * math.pi * k / count),
            )
            for k in range(count)
        ]

        assert validate_polygon(ring) is None

    def test_adversarial_comb_is_refused_as_too_complex_not_guessed(self) -> None:
        # Тысячи длинных узких зубьев: проверка вышла бы за предел работы. Отказ с кодом, а не
        # «вероятно, годится».
        teeth: list[tuple[float, float]] = [(0.02, 0.02)]
        count = 2500
        for index in range(count):
            left = 0.05 + 0.9 * index / count
            right = left + 0.9 / (2 * count)
            teeth += [(left, 0.95), (left + 1e-9, 0.1), (right, 0.1), (right - 1e-9, 0.95)]
        teeth.append((0.98, 0.02))

        assert _code(validate_polygon(teeth)) is GeometryIssueCode.TOO_COMPLEX
        assert MAX_CANDIDATE_PAIRS > 0

    @pytest.mark.parametrize("code", list(GeometryIssueCode))
    def test_every_code_has_a_message(self, code: GeometryIssueCode) -> None:
        assert GeometryIssue(code, ring=1, vertex=0, edge=0, other_ring=0, other_edge=1).message
