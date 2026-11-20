"""Фрагмент плана на листе корпуса: стены целиком вне пятна корпуса в 3D не идут (объект 346)."""

from __future__ import annotations

from app.contracts.cad_building3d import CadBuilding3dFloorRead, CadBuilding3dWallRead
from app.services import cad_building3d as b3d
from app.services import cad_building3d_assembly as assembly
from tests.test_cad_building3d import built


def _floors() -> list[CadBuilding3dFloorRead]:
    items = [
        built(corps="1", section=None, order=i, elevation=3000 * i, include_walls=True)
        for i in range(4)
    ]
    floors = b3d.align_floors(items)
    assert all(f.walls for f in floors)
    assert len({f.group_key for f in floors}) == 1
    return floors


def _far(floor: CadBuilding3dFloorRead, count: int, dx: int = 60000) -> CadBuilding3dFloorRead:
    walls = list(floor.walls or [])
    extra = [
        CadBuilding3dWallRead.model_validate(
            {
                "id": f"far{i}",
                "kind": "monolith_wall",
                "shell": [
                    [dx + 1000 * i, 0],
                    [dx + 1000 * i + 200, 0],
                    [dx + 1000 * i + 200, 3000],
                    [dx + 1000 * i, 3000],
                ],
                "top_mm": None,
            }
        )
        for i in range(count)
    ]
    box = floor.bbox or [0.0, 0.0, 0.0, 0.0]
    return floor.model_copy(
        update={"walls": walls + extra, "bbox": [box[0], box[1], dx + 1000 * count, box[3]]}
    )


def test_fragment_beside_the_plan_is_dropped() -> None:
    floors = _floors()
    before = len(floors[1].walls or [])
    floors[1] = _far(floors[1], 1)
    out, notes = assembly.drop_fragments(floors)
    assert len(out[1].walls or []) == before
    assert out[1].bbox is not None and out[1].bbox[2] < 60000
    assert notes == [(floors[1].label, 1)]
    assert out[0] is floors[0] and out[2] is floors[2]


def test_mostly_far_floor_is_not_a_fragment() -> None:
    floors = _floors()
    floors[2] = _far(floors[2], 3 * len(floors[2].walls or []))
    out, notes = assembly.drop_fragments(floors)
    assert out[2] is floors[2]
    assert notes == []


def test_stylobate_groups_are_not_touched() -> None:
    floors = [f.model_copy(update={"group_key": "none"}) for f in _floors()]
    floors[1] = _far(floors[1], 1)
    out, notes = assembly.drop_fragments(floors)
    assert out == floors and notes == []
