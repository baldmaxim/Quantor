import pytest

from building_model.geometry import Pt, centroid, interior_point, point_in_polygon

U_SHAPE: list[Pt] = [
    (0, 0), (6000, 0), (6000, 5000), (4000, 5000), (4000, 1000), (2000, 1000), (2000, 5000),
    (0, 5000),
]  # fmt: skip


def test_centroid_is_used_when_inside() -> None:
    square: list[Pt] = [(0, 0), (4000, 0), (4000, 2000), (0, 2000)]
    assert interior_point(square) == (2000.0, 1000.0)


def test_concave_polygon_gets_point_inside_when_centroid_is_outside() -> None:
    assert not point_in_polygon(centroid(U_SHAPE), U_SHAPE)
    point = interior_point(U_SHAPE)
    assert point is not None
    assert point_in_polygon(point, U_SHAPE)


def test_point_does_not_depend_on_vertex_order() -> None:
    forward = interior_point(U_SHAPE)
    backward = interior_point(list(reversed(U_SHAPE)))
    rotated = interior_point(U_SHAPE[3:] + U_SHAPE[:3])
    assert forward is not None
    assert forward == backward == rotated


def test_comb_polygon_with_centroid_in_gap() -> None:
    comb: list[Pt] = [
        (0, 0), (9000, 0), (9000, 6000), (7000, 6000), (7000, 1000), (5000, 1000),
        (5000, 6000), (3000, 6000), (3000, 1000), (2000, 1000), (2000, 6000), (0, 6000),
    ]  # fmt: skip
    point = interior_point(comb)
    assert point is not None
    assert point_in_polygon(point, comb)


@pytest.mark.parametrize(
    "poly", [[], [(0.0, 0.0), (1.0, 1.0)], [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]
)
def test_degenerate_polygon_has_no_point(poly: list[Pt]) -> None:
    assert interior_point(poly) is None
