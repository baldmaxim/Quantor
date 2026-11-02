import hashlib
import json

from building_model.pipeline import dumps_model
from tests.synth import JsonObj, build, door, gap_item, make_sheet, sp, wall

TOP_LEVEL = [
    "schema", "tender", "reader", "units", "origin", "levels", "walls", "openings", "slabs",
    "rooms", "stacks", "review", "columns", "params", "stats",
]  # fmt: skip


def _rich_sheet() -> JsonObj:
    walls = [
        wall("W0", (0, 0), (2000, 0)),
        wall("W1", (3000, 0), (6000, 0)),
        wall("W2", (6000, 0), (6000, 5000)),
        wall("W3", (6000, 5000), (0, 5000), t=300, role="outer wall"),
        wall("W4", (0, 5000), (0, 0), t=300, role="outer wall"),
        wall("W5", (3000, 1000), (3000, 4000), t=100),
        wall("W6", (500, 500), (700, 500), t=400, role="column"),
        wall("W7", (1000, 2000), (1030, 2000), t=100),
    ]
    two_segments = wall("W8", (1000, 3000), (2500, 3000))
    segments = two_segments["segments"]
    assert isinstance(segments, list)
    segments.append({"a": sp(2520, 3000), "b": sp(4000, 3000), "thickness_mm": 200.0})
    walls.append(two_segments)
    room_poly = [sp(100, 100), sp(2900, 100), sp(2900, 2900), sp(100, 2900)]
    return make_sheet(
        walls=walls,
        doors=[
            door("D0", (2000, 0), (3000, 0), (2000, 1000), 1000, host="W0"),
            door("D1", (4000, 0), (4500, 0), (4000, 500), 1000, leaves=2, width=500),
            door("D2", (5000, 0), (4500, 0), (5000, 500), 1000, leaves=2, width=500),
        ],
        windows=[gap_item("O0", (0, 1500), (0, 2500)), gap_item("O1", (3500, 5000), (4500, 5000))],
        openings=[gap_item("H0", (6000, 1000), (6000, 1800))],
        rooms=[
            {
                "id": "R0", "type": "living", "type_source": "name", "area_m2": 7.8,
                "schedule_area_m2": 8.0, "tag": "1", "polygon_mm": room_poly,
            },
            {
                "id": "R1", "type": "shaft", "type_source": "geometry", "area_m2": 1.0,
                "polygon_mm": [sp(4000, 1000), sp(5000, 1000), sp(5000, 2000), sp(4000, 2000)],
            },
        ],
        stairs=[
            {
                "id": "T0",
                "polygon_mm": [sp(100, 3500), sp(900, 3500), sp(900, 4500), sp(100, 4500)],
                "slab_opening_mm": [sp(100, 3500), sp(900, 3500), sp(900, 4500), sp(100, 4500)],
            }
        ],
        slab_outlines_mm=[[sp(0, 0), sp(6000, 0), sp(6000, 5000), sp(0, 5000)]],
        axes=[
            {"label": "1", "angle": 0.0, "normal": [1.0, 0.0], "offset_mm": 1000.0, "bubbles": 2},
            {"label": "2", "angle": 0.0, "normal": [1.0, 0.0], "offset_mm": 7000.0, "bubbles": 2},
            {"label": "A", "angle": 0.0, "normal": [0.0, 1.0], "offset_mm": 2000.0, "bubbles": 2},
        ],
    )  # fmt: skip


def _rank(seed: int, item: object) -> int:
    """Псевдослучайный, но воспроизводимый порядок: перемешивание по хешу, без random."""
    digest = hashlib.sha256(f"{seed}|{json.dumps(item, sort_keys=True)}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _shuffled(sheet: JsonObj, seed: int) -> JsonObj:
    result: JsonObj = dict(sheet)
    for name in ("walls", "doors", "windows", "openings", "rooms", "stairs", "axes"):
        items = result[name]
        assert isinstance(items, list)
        copy = [dict(item) for item in items]
        for item in copy:
            segments = item.get("segments")
            if isinstance(segments, list):
                mixed = []
                for seg in sorted(segments, key=lambda x: _rank(seed, x)):
                    seg = dict(seg)
                    if _rank(seed, seg) % 2:
                        seg["a"], seg["b"] = seg["b"], seg["a"]
                    mixed.append(seg)
                item["segments"] = mixed
            for field in ("polygon_mm", "slab_opening_mm"):
                poly = item.get(field)
                if isinstance(poly, list) and poly:
                    shift = _rank(seed, poly) % len(poly)
                    item[field] = poly[shift:] + poly[:shift]
        result[name] = sorted(copy, key=lambda x: _rank(seed, x))
    return result


def test_shuffled_input_gives_byte_identical_output() -> None:
    sheet = _rich_sheet()
    reference = dumps_model(build(sheet))
    for seed in range(5):
        assert dumps_model(build(_shuffled(sheet, seed))) == reference


def test_repeated_run_is_identical_and_has_no_run_time() -> None:
    sheet = _rich_sheet()
    first, second = dumps_model(build(sheet)), dumps_model(build(sheet))
    assert first == second
    data = json.loads(first)
    assert "seconds" not in first
    assert "read_seconds" not in first
    assert list(data) == TOP_LEVEL
    assert data["schema"] == "quantor.building_model.v1"
    assert data["tender"] == {"number": None, "version": None, "manifest_sha256": None}


def test_wall_key_does_not_depend_on_ab_direction() -> None:
    forward = build(make_sheet(walls=[wall("W0", (0, 0), (4000, 0))]))
    backward = build(make_sheet(walls=[wall("W0", (4000, 0), (0, 0))]))
    assert forward.walls[0].key == backward.walls[0].key
    assert dumps_model(forward) == dumps_model(backward)


def test_keys_do_not_change_when_another_element_moves() -> None:
    def keys(second_y: float) -> dict[str, str]:
        sheet = make_sheet(
            walls=[wall("W0", (0, 0), (4000, 0)), wall("W1", (0, second_y), (4000, second_y))]
        )
        return {f"{w.a}-{w.b}": w.key for w in build(sheet).walls}

    before, after = keys(3000), keys(3500)
    assert before["(0.0, 0.0)-(4000.0, 0.0)"] == after["(0.0, 0.0)-(4000.0, 0.0)"]
    assert before["(0.0, 3000.0)-(4000.0, 3000.0)"] != after["(0.0, 3500.0)-(4000.0, 3500.0)"]


def test_key_rounding_absorbs_sub_step_shifts_and_not_larger_ones() -> None:
    def key(shift: float) -> str:
        return build(make_sheet(walls=[wall("W0", (shift, 0), (4000, 0))])).walls[0].key

    assert key(0.0) == key(3.0)
    assert key(0.0) != key(30.0)


def test_key_collisions_get_deterministic_suffix() -> None:
    thin = wall("W0", (0, 0), (4000, 0), t=100)
    thick = wall("W1", (0, 0), (4000, 0), t=300)
    first = build(make_sheet(walls=[thin, thick]))
    second = build(make_sheet(walls=[thick, thin]))
    assert [w.key for w in first.walls] == [w.key for w in second.walls]
    base = first.walls[0].key.split("-")[0]
    assert sorted(w.key for w in first.walls) == [base, f"{base}-1"]


def test_tender_arguments_pass_through() -> None:
    from building_model.pipeline import TenderArgs, build_model
    from tests.synth import document

    model = build_model(document(make_sheet()), 0, TenderArgs("123", 2, "ab" * 32))
    assert (model.tender.number, model.tender.version) == ("123", 2)
    assert model.tender.manifest_sha256 == "ab" * 32
