"""Тесты проверки топологии трасс (cad_mep.topology) на готовых линиях."""

from __future__ import annotations

from typing import cast

from cad_mep.params import load_params
from cad_mep.result import Line3D, NodeMark, Result
from cad_mep.topology import route_topology

PARAMS = load_params(None)
Pts = list[tuple[float, float]]


def _line(layer: str, pts: Pts, kind: str = "route") -> Line3D:
    return Line3D(layer, [(x, y, 2800.0) for x, y in pts], None, kind)


def _layer(res: Result, layer: str) -> dict[str, object]:
    layers = cast(dict[str, dict[str, object]], route_topology(res, PARAMS)["layers"])
    return layers[layer]


def test_joint_in_point_has_no_dangling_in_the_joint() -> None:
    res = Result(
        lines=[_line("M-OV-T1", [(0, 0), (1000, 0)]), _line("M-OV-T1", [(1000, 0), (1000, 800)])]
    )
    info = _layer(res, "M-OV-T1")
    # свободны лишь дальние концы (стык в (1000, 0) подключён)
    assert info["lines"] == 2 and info["ends"] == 4 and info["dangling"] == 2
    assert info["dangling_samples"] == [[0, 0], [1000, 800]]


def test_closed_ring_of_two_lines_has_no_dangling() -> None:
    res = Result(
        lines=[
            _line("M-OV-T1", [(0, 0), (1000, 0), (1000, 800)]),
            _line("M-OV-T1", [(1000, 800), (0, 800), (0, 0)]),
        ]
    )
    assert _layer(res, "M-OV-T1")["dangling"] == 0


def test_gap_60mm_gives_dangling() -> None:
    joined = Result(
        lines=[_line("M-OV-T1", [(0, 0), (1000, 0)]), _line("M-OV-T1", [(1000, 0), (2000, 0)])]
    )
    gap = Result(
        lines=[_line("M-OV-T1", [(0, 0), (1000, 0)]), _line("M-OV-T1", [(1060, 0), (2000, 0)])]
    )
    assert _layer(joined, "M-OV-T1")["dangling"] == 2  # только крайние концы
    assert _layer(gap, "M-OV-T1")["dangling"] == 4  # плюс оба конца у зазора


def test_end_on_segment_of_other_line_is_connected() -> None:
    res = Result(
        lines=[_line("M-VK-V1", [(0, 0), (2000, 0)]), _line("M-VK-V1", [(1000, 3), (1000, 900)])]
    )
    assert _layer(res, "M-VK-V1")["dangling"] == 3  # (0,0), (2000,0), (1000,900); T-стык подключён


def test_end_near_node_mark_is_connected() -> None:
    lines = [_line("M-OV-T1", [(0, 0), (1000, 0)])]
    bare = Result(lines=lines)
    marked = Result(
        lines=lines,
        nodes=[
            NodeMark("M-NODE", "collector", (0.0, 100.0), 1000.0, 1, "heating"),
            NodeMark("M-NODE", "device", (1000.0, 0.0), 1000.0, 1, "heating"),
        ],
    )
    other_system = Result(
        lines=lines, nodes=[NodeMark("M-NODE", "meter", (0.0, 0.0), 1000.0, 1, "water")]
    )
    assert _layer(bare, "M-OV-T1")["dangling"] == 2
    assert _layer(marked, "M-OV-T1")["dangling"] == 0
    assert _layer(other_system, "M-OV-T1")["dangling"] == 2


def test_end_at_riser_is_connected_and_riser_is_not_a_route_line() -> None:
    res = Result(
        lines=[
            _line("M-OV-T1", [(0, 0), (1000, 0)], "leadin"),
            Line3D("M-OV-T1", [(0.0, 0.0, 0.0), (0.0, 0.0, 3000.0)], None, "riser"),
        ]
    )
    info = _layer(res, "M-OV-T1")
    assert info["lines"] == 1 and info["dangling"] == 1


def test_x_crossing_same_layer() -> None:
    res = Result(
        lines=[_line("M-VK-T3", [(0, 0), (2000, 2000)]), _line("M-VK-T3", [(0, 2000), (2000, 0)])]
    )
    info = _layer(res, "M-VK-T3")
    assert info["same_layer_crossings"] == 1
    assert info["crossing_samples"] == [[1000, 1000]]


def test_touch_at_common_vertex_is_not_crossing() -> None:
    res = Result(
        lines=[
            _line("M-VK-T3", [(0, 0), (1000, 0), (2000, 0)]),
            _line("M-VK-T3", [(0, 1000), (1000, 0), (2000, 1000)]),
        ]
    )
    assert _layer(res, "M-VK-T3")["same_layer_crossings"] == 0


def test_t_junction_is_not_crossing() -> None:
    res = Result(
        lines=[_line("M-VK-T3", [(0, 0), (2000, 0)]), _line("M-VK-T3", [(1000, 0), (1000, 900)])]
    )
    assert _layer(res, "M-VK-T3")["same_layer_crossings"] == 0


def test_cross_layer_crossing_is_reported_by_system() -> None:
    res = Result(
        lines=[_line("M-OV-T1", [(0, 0), (2000, 2000)]), _line("M-OV-T2", [(0, 2000), (2000, 0)])]
    )
    topo = route_topology(res, PARAMS)
    systems = cast(dict[str, dict[str, int]], topo["systems"])
    assert systems["heating"]["cross_layer_crossings"] == 1
    assert _layer(res, "M-OV-T1")["same_layer_crossings"] == 0
    assert cast(dict[str, int], topo["totals"])["cross_layer_crossings"] == 1


def test_aup_dead_end_is_branch_end_not_dangling() -> None:
    res = Result(
        lines=[_line("M-PT-AUP", [(0, 0), (1000, 0)]), _line("M-PT-VPV", [(0, 0), (1000, 0)])]
    )
    aup = _layer(res, "M-PT-AUP")
    assert aup["dangling"] == 0 and aup["branch_ends"] == 2
    assert _layer(res, "M-PT-VPV")["dangling"] == 2
    totals = cast(dict[str, int], route_topology(res, PARAMS)["totals"])
    assert totals["dangling"] == 2 and totals["branch_ends"] == 2


def test_vertical_drop_duplicates_are_collapsed() -> None:
    res = Result(
        lines=[
            Line3D(
                "M-VK-V1",
                [(0.0, 0.0, 2800.0), (1000.0, 0.0, 2800.0), (1000.0, 0.0, 1000.0)],
                None,
                "route",
            )
        ]
    )
    info = _layer(res, "M-VK-V1")
    assert info["lines"] == 1 and info["length_m"] == 1.0
