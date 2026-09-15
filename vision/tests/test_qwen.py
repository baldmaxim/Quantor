"""Промт 12: строгий парсер ответа Qwen, цели SFT из масок, адаптер набора и окружение."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantor_vision.cli import VISION_ROOT, main
from quantor_vision.environment import BLOCKED_EXIT
from quantor_vision.qwen import environment
from quantor_vision.qwen.models import MODELS, local_dir_name
from quantor_vision.qwen.schema import (
    MASONRY_SCHEMA,
    SLAB_SCHEMA,
    Limits,
    MasonryRoi,
    ResponseError,
    SlabObject,
    failure_counts,
    parse_masonry,
    parse_slab,
    serialize_masonry,
    serialize_slab,
)
from quantor_vision.qwen.sft import INSTRUCTIONS, SftConfig, SftRefusedError, build_sft
from quantor_vision.qwen.targets import TargetConfig, TileGeometry, masonry_target, slab_target
from tests.synthetic_build import TILE, make_build

SMALL = SftConfig(targets=TargetConfig(stride=2, min_area_px=16))
GEOMETRY = TileGeometry(tile_px=TILE, valid_width=TILE, valid_height=TILE)


def _error(text: str) -> str:
    with pytest.raises(ResponseError) as caught:
        parse_slab(text)
    return caught.value.code


def _valid_slab() -> str:
    return serialize_slab(
        [SlabObject(bbox=(120, 180, 870, 820), positive_points=((350, 420),), negative_points=())]
    )


class TestSlabParser:
    def test_serialized_target_round_trips(self) -> None:
        item = SlabObject(
            bbox=(120, 180, 870, 820),
            positive_points=((350, 420), (710, 550)),
            negative_points=((470, 350),),
        )

        text = serialize_slab([item])

        assert " " not in text
        assert text.startswith('{"schema":"qwen_slab_localization_v1","objects":')
        assert parse_slab(text) == [item]

    def test_empty_objects_are_a_valid_answer(self) -> None:
        assert parse_slab('{"schema":"qwen_slab_localization_v1","objects":[]}') == []

    def test_surrounding_whitespace_is_tolerated(self) -> None:
        assert len(parse_slab("\n " + _valid_slab() + "\n")) == 1

    @pytest.mark.parametrize(
        ("text", "code"),
        [
            ("", "empty"),
            ("Вот ответ: {}", "prose_or_fence"),
            ('```json\n{"schema":"qwen_slab_localization_v1","objects":[]}\n```', "prose_or_fence"),
            ("{not json}", "not_json"),
            ('{"schema":"qwen_slab_localization_v1","objects":[],"objects":[]}', "duplicate_key"),
            ('{"schema":"qwen_slab_localization_v2","objects":[]}', "schema_mismatch"),
            ('{"schema":"qwen_slab_localization_v1"}', "missing_key"),
            ('{"schema":"qwen_slab_localization_v1","objects":[],"note":"x"}', "extra_key"),
            ('{"schema":"qwen_slab_localization_v1","objects":{}}', "wrong_type"),
        ],
    )
    def test_structural_failures_have_codes(self, text: str, code: str) -> None:
        assert _error(text) == code

    @pytest.mark.parametrize(
        ("bbox", "positive", "code"),
        [
            ("[120.5,180,870,820]", "[]", "wrong_type"),
            ("[true,180,870,820]", "[]", "wrong_type"),
            ("[120,180,1001,820]", "[]", "coordinate_out_of_range"),
            ("[-1,180,870,820]", "[]", "coordinate_out_of_range"),
            ("[870,180,120,820]", "[]", "bbox_order"),
            ("[120,180,120,820]", "[]", "bbox_area"),
            ("[120,180,870]", "[]", "wrong_type"),
            ("[120,180,870,820]", "[[10,10]]", "point_outside_box"),
            ("[120,180,870,820]", "[[200,200],[300,300],[400,400],[500,500]]", "too_many_points"),
            ("[120,180,870,820]", "[[200]]", "wrong_type"),
        ],
    )
    def test_geometry_failures_have_codes(self, bbox: str, positive: str, code: str) -> None:
        text = (
            '{"schema":"qwen_slab_localization_v1","objects":[{"class":"slab","bbox":'
            + bbox
            + ',"positive_points":'
            + positive
            + ',"negative_points":[]}]}'
        )
        assert _error(text) == code

    def test_nan_is_not_json(self) -> None:
        text = (
            '{"schema":"qwen_slab_localization_v1","objects":[{"class":"slab",'
            '"bbox":[NaN,1,2,3],"positive_points":[],"negative_points":[]}]}'
        )
        assert _error(text) == "not_json"

    def test_wrong_class_and_extra_object_key_are_rejected(self) -> None:
        wall = _valid_slab().replace('"class":"slab"', '"class":"wall"')
        extra = _valid_slab().replace('"class":"slab"', '"class":"slab","area_m2":12')
        assert _error(wall) == "schema_mismatch"
        assert _error(extra) == "extra_key"

    def test_object_count_is_bounded(self) -> None:
        with pytest.raises(ResponseError) as caught:
            parse_slab(_valid_slab(), Limits(max_objects=0))
        assert caught.value.code == "too_many_objects"

    def test_failures_are_counted_as_a_metric(self) -> None:
        summary = failure_counts([None, "not_json", "not_json", None])
        assert summary == {
            "responses": 4,
            "parsed": 2,
            "parse_rate": 0.5,
            "failures": {"not_json": 2},
        }


class TestMasonryParser:
    def test_round_trip(self) -> None:
        value = MasonryRoi(contains_masonry=True, roi=(10, 20, 500, 600), guide_points=((50, 60),))
        assert parse_masonry(serialize_masonry(value)) == value
        empty = MasonryRoi(contains_masonry=False, roi=None, guide_points=())
        assert parse_masonry(serialize_masonry(empty)) == empty

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ('"contains_masonry":false,"roi":[1,1,5,5],"guide_points":[]', "inconsistent_roi"),
            ('"contains_masonry":true,"roi":null,"guide_points":[]', "inconsistent_roi"),
            ('"contains_masonry":1,"roi":null,"guide_points":[]', "wrong_type"),
            ('"contains_masonry":true,"roi":[1,1,5,5],"guide_points":[[9,9]]', "point_outside_box"),
        ],
    )
    def test_failures(self, body: str, code: str) -> None:
        with pytest.raises(ResponseError) as caught:
            parse_masonry('{"schema":"qwen_masonry_roi_v1",' + body + "}")
        assert caught.value.code == code


def _synthetic_mask(*, left: int = 6, right: int = 26) -> bytes:
    mask = bytearray(TILE * TILE)
    for y in range(6, 26):
        for x in range(left, right):
            if not (13 <= x < 18 and 13 <= y < 18):
                mask[y * TILE + x] = 255
    return bytes(mask)


def _pixel(mask: bytes, point: tuple[int, int]) -> int:
    x = min(TILE - 1, int(point[0] / 1000 * TILE))
    y = min(TILE - 1, int(point[1] / 1000 * TILE))
    return mask[y * TILE + x]


class TestTargets:
    def test_slab_with_hole_gives_box_inside_and_hole_points(self) -> None:
        mask = _synthetic_mask()

        target = slab_target(mask, GEOMETRY, SMALL.targets)

        assert target.dropped_small == 0
        assert len(target.objects) == 1
        item = target.objects[0]
        assert item.bbox == (188, 188, 812, 812)
        assert item.positive_points
        assert all(_pixel(mask, point) == 255 for point in item.positive_points)
        assert item.negative_points
        assert all(_pixel(mask, point) == 0 for point in item.negative_points)
        # Цель проходит собственный строгий парсер.
        assert parse_slab(serialize_slab(target.objects)) == target.objects

    def test_empty_mask_gives_no_objects(self) -> None:
        target = slab_target(bytes(TILE * TILE), GEOMETRY, SMALL.targets)
        assert target.objects == []

    def test_small_fragments_are_dropped_and_counted(self) -> None:
        mask = bytearray(TILE * TILE)
        mask[0] = mask[1] = 255
        target = slab_target(bytes(mask), GEOMETRY, TargetConfig(stride=2, min_area_px=64))
        assert target.objects == []
        assert target.dropped_small == 1

    def test_padding_outside_valid_area_is_ignored(self) -> None:
        mask = bytes([255] * (TILE * TILE))
        geometry = TileGeometry(tile_px=TILE, valid_width=16, valid_height=TILE)
        target = slab_target(mask, geometry, SMALL.targets)
        assert [item.bbox for item in target.objects] == [(0, 0, 500, 1000)]

    def test_masonry_roi_covers_thin_line(self) -> None:
        heat = bytearray(TILE * TILE)
        for x in range(4, 28):
            heat[9 * TILE + x] = 255
        roi = masonry_target(bytes(heat), GEOMETRY, SMALL.targets)
        assert roi.contains_masonry
        assert roi.roi is not None
        assert roi.roi[0] <= 125 and roi.roi[2] >= 875
        assert 1 <= len(roi.guide_points) <= SMALL.targets.guide_points
        assert parse_masonry(serialize_masonry(roi)) == roi
        empty = masonry_target(bytes(TILE * TILE), GEOMETRY, SMALL.targets)
        assert not empty.contains_masonry


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestSftAdapter:
    def test_train_has_answers_and_evaluation_has_only_image_and_instruction(
        self, tmp_path: Path
    ) -> None:
        build = make_build(tmp_path / "build", per_split={"train": 2, "val": 1, "test": 1})

        result = build_sft(build, tmp_path / "sft", SMALL)

        view = tmp_path / "sft" / SLAB_SCHEMA
        train = _jsonl(view / "train.jsonl")
        assert len(train) == 2
        for row in train:
            messages = row["messages"]
            assert isinstance(messages, list)
            assert [message["role"] for message in messages] == ["user", "assistant"]
            answer = messages[1]["content"][0]["text"]
            assert len(parse_slab(answer)) == 1
        for split in ("val", "test"):
            rows = _jsonl(view / f"{split}.jsonl")
            assert len(rows) == 1
            assert set(rows[0]) == {
                "id",
                "image",
                "image_sha256",
                "page_guid",
                "crop_policy",
                "messages",
            }
            assert rows[0]["messages"] == [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": INSTRUCTIONS[SLAB_SCHEMA]},
                    ],
                }
            ]
            labels = _jsonl(view / f"labels-{split}.jsonl")
            assert [label["id"] for label in labels] == [rows[0]["id"]]
        assert (tmp_path / "sft" / MASONRY_SCHEMA / "train.jsonl").read_text(encoding="utf-8") == ""
        leakage = result["anti_leakage"]
        assert isinstance(leakage, dict)
        assert all(leakage.values())
        manifest = json.loads((tmp_path / "sft" / "sft.json").read_text(encoding="utf-8"))
        assert "qwen_slab_polygon_v0" in manifest["unsupported_views"]
        assert f"{SLAB_SCHEMA}/train.jsonl" in manifest["files_sha256"]

    def test_non_grid_evaluation_tile_refuses_whole_build(self, tmp_path: Path) -> None:
        build = make_build(tmp_path / "build", per_split={"train": 1, "val": 1})
        tiles = build / "tiles.jsonl"
        tiles.write_text(
            tiles.read_text(encoding="utf-8").replace(
                '"split": "val", "crop_policy": "grid"',
                '"split": "val", "crop_policy": "gt_positive"',
            ),
            encoding="utf-8",
        )
        with pytest.raises(SftRefusedError):
            build_sft(build, tmp_path / "sft", SMALL)
        assert not (tmp_path / "sft").exists()

    def test_unsupported_target_is_not_truncated(self, tmp_path: Path) -> None:
        build = make_build(tmp_path / "build", per_split={"train": 1, "val": 1})
        config = SftConfig(targets=SMALL.targets, limits=Limits(max_objects=0))

        result = build_sft(build, tmp_path / "sft", config)

        view = tmp_path / "sft" / SLAB_SCHEMA
        assert _jsonl(view / "train.jsonl") == []
        assert len(_jsonl(view / "val.jsonl")) == 1
        assert _jsonl(view / "labels-val.jsonl") == [
            {"id": "val000", "target": None, "unsupported": "too_many_objects"}
        ]
        counters = result["counters"]
        assert isinstance(counters, dict)
        assert counters[f"{SLAB_SCHEMA}.train.unsupported.too_many_objects"] == 1

    def test_existing_output_is_not_overwritten(self, tmp_path: Path) -> None:
        build = make_build(tmp_path / "build", per_split={"train": 1})
        out = tmp_path / "sft"
        out.mkdir()
        (out / "keep.txt").write_text("x", encoding="utf-8")
        with pytest.raises(SftRefusedError):
            build_sft(build, out, SMALL)

    def test_cli_refuses_output_inside_repository(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        build = make_build(tmp_path / "build", per_split={"train": 1})
        out = VISION_ROOT / "never-created-sft"

        code = main(["qwen-build-sft", "--build", str(build), "--out", str(out), "--skip-verify"])

        report = json.loads(capsys.readouterr().out)
        assert code == BLOCKED_EXIT
        assert report["status"] == "BLOCKED"
        assert not out.exists()


class TestEnvironment:
    def test_telemetry_is_disabled_and_offline_is_opt_in(self) -> None:
        environ: dict[str, str] = {}
        environment.disable_telemetry(environ)
        assert environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
        assert environ["WANDB_MODE"] == "disabled"
        assert environ["UNSLOTH_DISABLE_STATISTICS"] == "1"
        assert "HF_HUB_OFFLINE" not in environ
        environment.disable_telemetry(environ, offline=True)
        assert environ["HF_HUB_OFFLINE"] == "1"

    def test_models_are_pinned_to_full_revisions_and_hashes(self) -> None:
        assert set(MODELS) == {"2b", "4b", "8b"}
        decisions = json.loads(
            (VISION_ROOT / "licenses" / "decisions.json").read_text(encoding="utf-8")
        )
        for model in MODELS.values():
            assert len(model.revision) == 40
            assert decisions["weights"][model.repo_id]["revision"] == model.revision
            assert decisions["weights"][model.repo_id]["decision"] == "allow"
            assert decisions["weights"][model.repo_id]["weights_sha256"] == model.weights_sha256
            assert all(len(value) == 64 for value in model.weights_sha256.values())
        assert local_dir_name(MODELS["4b"]) == "Qwen--Qwen3-VL-4B-Instruct@ebb281ec70b0"

    def test_weights_with_wrong_hash_are_refused(self, tmp_path: Path) -> None:
        model = MODELS["2b"]
        assert environment.verify_weights(tmp_path, model) == ["нет файла model.safetensors"]
        (tmp_path / "model.safetensors").write_bytes(b"not the pinned parent")
        assert environment.verify_weights(tmp_path, model) == [
            "SHA-256 model.safetensors не совпадает с закреплённым"
        ]

    def test_version_mismatches_are_reported(self) -> None:
        mismatches = environment.version_mismatches({"torch": "2.11.0+cu128"})
        assert "torch" not in mismatches
        assert "unsloth" in mismatches

    def test_synthetic_drawing_is_deterministic(self, tmp_path: Path) -> None:
        pytest.importorskip("PIL")
        first = environment.synthetic_drawing(tmp_path / "a.png", size=256)
        second = environment.synthetic_drawing(tmp_path / "b.png", size=256)
        assert first == second
