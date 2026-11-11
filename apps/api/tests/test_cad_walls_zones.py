"""Зоны помещений как вход задания cad_walls: канонический JSON и ключ идемпотентности."""

from __future__ import annotations

import json
import uuid

from app.services import cad_floor3d, cad_walls, cad_walls_zones

PARENT = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _key(zones_sha256: str) -> str:
    return cad_walls.idempotency_key(
        PARENT,
        parent_attempt=1,
        page_index=0,
        view=0,
        params_sha256="a" * 64,
        generator_version="cad_walls.v1.4",
        sequence=0,
        zones_sha256=zones_sha256,
    )


def test_idempotency_key_depends_on_zones() -> None:
    assert _key("") == _key("")
    assert _key("") != _key("b" * 64)
    assert _key("b" * 64) != _key("c" * 64)


def test_canonical_bytes_ignore_zone_order_and_are_rounded() -> None:
    a = cad_floor3d.RoomZoneMm("room_apartment", [(0.04, 0.0), (10.0, 0.0), (10.0, 10.0)])
    b = cad_floor3d.RoomZoneMm("room_mop", [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0)])
    raw = cad_walls_zones.canonical_bytes([b, a])
    assert raw == cad_walls_zones.canonical_bytes([a, b])
    rows = json.loads(raw)
    assert [row["kind"] for row in rows] == ["room_apartment", "room_mop"]
    assert rows[0]["shell"][0] == [0.0, 0.0]


def test_no_zones_input_is_empty() -> None:
    assert not cad_walls_zones.NO_ZONES.present
    assert cad_walls_zones.NO_ZONES.sha256 == ""
