"""Сборка v2 (Р-9): шаблоны меток, семейства, дубли листов, класс wall, листы PDF."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from planswift_gt import build as dataset_build
from planswift_gt.batch import family_for, slug
from planswift_gt.buildconfig import BuildConfig, DatasetRef, TargetConfig, load
from planswift_gt.cli import main
from planswift_gt.parser import parse_project
from planswift_gt.splits import PageInfo, assign_families
from tests.synthetic import HEIGHT, IMAGE_GUID, WIDTH, pdf_bytes

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
ROOT_NAME = "Синтетика кладка"


def _rules() -> dict[str, object]:
    loaded = json.loads(
        (CONFIGS / "dataset-build-v2.rules.example.json").read_text(encoding="utf-8")
    )
    assert isinstance(loaded, dict)
    return loaded


def _target(name: str) -> TargetConfig:
    targets = _rules()["targets"]
    assert isinstance(targets, dict)
    spec = targets[name]
    return TargetConfig(
        kinds=tuple(spec["kinds"]),
        label_patterns=tuple(spec["label_patterns"]),
    )


class TestLabelRules:
    @pytest.mark.parametrize(
        "label",
        [
            "Фундаментная Плита [Толщина ФП]м [Класс бетона ФП]",
            "Плита Перекрытия [Толщина ПП]м [Класс бетона ПП]",
            "Плита Перекытия [Толщина ПП]м [Класс бетона ПП]",
            "Плиты перекрытия",
            "плиты перекрытия 6 этажа",
            "Плиты покрытие",
            "03.07.01: Плиты перекрытия - КОРП.5 (-1-го Этажа)",
        ],
    )
    def test_slab_labels_are_selected(self, label: str) -> None:
        assert _target("slab").selects("polygon", label)

    @pytest.mark.parametrize(
        "label",
        [
            "Плита Перекрытия [Толщина Капители]м [Класс бетона Капители]",
            "Термовкладыш [Толщина ПП]м [Класс бетона ПП]",
            "Капитель [Толщина ПП]м [Класс бетона ПП]",
            "Площадка [Толщина ПП]м [Класс бетона ПП]",
            "Ресторан",
            None,
        ],
    )
    def test_not_slabs_are_rejected(self, label: str | None) -> None:
        assert not _target("slab").selects("polygon", label)

    def test_slab_rule_needs_polygon_kind(self) -> None:
        assert not _target("slab").selects("polyline", "Плиты перекрытия")

    @pytest.mark.parametrize(
        ("label", "selected"),
        [
            ("Стены [Толщина Стен, Т]м х [Высота Стен, В]м [Класс бетона стен]", True),
            ("Стены 4", True),
            ("Стена в грунте [Толщина СвГ]м х[Высота СвГ]м [Класс бетона СвГ]", True),
            ("Кладка стен толщиной 190 мм: из СКЦ", True),
            ("Кладка перегородок толщиной 80 мм: из СКЦ (на всю высоту помещения)", True),
            ("Стены кровли", False),
            ("Термовкладыш [Толщина Стен, Т]м х [Высота Стен, В]м [Класс бетона стен]", False),
            ("Балки [Толщина балки]м х [Высота балки]м х [Длина]м [Класс бетона балки]", False),
        ],
    )
    def test_wall_rule_joins_monolith_and_masonry(self, label: str, selected: bool) -> None:
        assert _target("wall").selects("polyline", label) is selected


class TestBatchKeys:
    def test_slug_is_ascii_and_stable(self) -> None:
        assert slug("ЖК Селигер Сити4 - К1") == "zhk_seliger_siti4_k1"
        assert slug("Мосфильмовская 31А Planswift") == "mosfilmovskaya_31a_planswift"
        assert slug("Секции 1 и 2  Полков") == "sektsii_1_i_2_polkov"

    def test_families_come_from_masks(self) -> None:
        families = _rules()["families"]
        assert isinstance(families, dict)
        assert family_for("s6_polkoavya_1", families) == "polkovaya"
        assert family_for("s7_i_s8", families) == "polkovaya"
        assert family_for("zhk_seligerkorp_h", families) == "seliger"
        assert family_for("k_22_fp_amfiteatra", families) == "korpus_22"
        assert family_for("zhk_sb5", families) == "zhk_sb5"


def _page(project: str, guid: str, slab: int, wall: int) -> PageInfo:
    return PageInfo(
        project, guid, guid * 4, 0, slab + wall, task_weights=(("slab", slab), ("wall", wall))
    )


class TestFamilySplit:
    def test_family_stays_whole_and_every_part_gets_a_family(self) -> None:
        pages = [
            _page("a1", "p1", 10, 1000),
            _page("a2", "p2", 5, 800),
            _page("b", "p3", 30, 50),
            _page("c", "p4", 20, 900),
            _page("d", "p5", 25, 100),
            _page("e", "p6", 10, 700),
        ]
        family_of = {"a1": "a", "a2": "a", "b": "b", "c": "c", "d": "d", "e": "e"}
        fractions = {"train": 0.7, "val": 0.15, "test": 0.15}

        split = assign_families(pages, family_of, fractions, seed=3)

        assert split["a1|p1"] == split["a2|p2"]
        assert set(split.values()) == {"train", "val", "test"}
        assert split == assign_families(pages, family_of, fractions, seed=3)

    def test_v1_split_fingerprint_is_unchanged(self) -> None:
        config = BuildConfig(
            build_id="v1",
            seed=20260914,
            datasets=(DatasetRef("mosfilm31a", "d", "s", ("slab",)),),
            targets={"slab": TargetConfig(kinds=("polygon",))},
        )
        legacy = json.dumps(
            {
                "seed": 20260914,
                "datasets": [("mosfilm31a", ("slab",))],
                "fractions": {"train": 0.7, "val": 0.15, "test": 0.15},
                "phash_hamming_threshold": 10,
                "downsample": 2,
            },
            sort_keys=True,
        )
        assert config.split_fingerprint() == hashlib.sha256(legacy.encode("utf-8")).hexdigest()


@pytest.fixture
def converted(project: Path, tmp_path: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "gt"
    code = main(
        [
            "convert",
            str(project),
            "--project-key",
            "synthetic",
            "--out",
            str(dataset),
            "--allow-inside-repo",
        ]
    )
    assert code == 0
    return dataset, project / ROOT_NAME


class TestBuildV2:
    def test_duplicate_pages_are_skipped_and_walls_get_targets(
        self, converted: tuple[Path, Path], tmp_path: Path
    ) -> None:
        dataset, source = converted
        # Три «проекта» из одного и того же листа: второй и третий — дубли первого.
        datasets = tuple(
            DatasetRef(key, str(dataset), str(source), ("slab", "wall"), family=family)
            for key, family in (("first", "f1"), ("copy", "f2"), ("again", "f3"))
        )
        config = BuildConfig(
            build_id="v2-synthetic",
            seed=5,
            datasets=datasets,
            tile_px=256,
            overlap_px=32,
            targets={
                "slab": TargetConfig(kinds=("polygon",), label_patterns=("^Плита",)),
                "wall": TargetConfig(
                    kinds=("polyline",), label_patterns=("^Стены",), min_positive_fraction=0.0005
                ),
            },
            split_fractions={"train": 1.0, "val": 0.0, "test": 0.0},
            holdout="families",
        )

        manifest = dataset_build.build(config, tmp_path / "build")

        skipped = manifest["duplicate_pages_skipped"]
        assert isinstance(skipped, list) and len(skipped) == 2
        leakage = manifest["leakage"]
        assert isinstance(leakage, dict) and all(leakage.values())
        assert leakage["families_in_one_split_only"] is True
        rows = [
            json.loads(line)
            for line in (tmp_path / "build" / "tiles.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert rows and {row["project_key"] for row in rows} == {"first"}
        assert {row["family"] for row in rows} == {"f1"}
        assert all(
            (tmp_path / "build" / "targets" / "wall" / f"{row['tile_id']}.png").is_file()
            for row in rows
        )
        assert any(row["target_fraction"]["wall"] > 0 for row in rows)
        split = json.loads((tmp_path / "build" / "split.json").read_text(encoding="utf-8"))
        assert split["holdout"] == "project-family holdout"

    def test_loaded_rules_config_is_valid(self, tmp_path: Path) -> None:
        rules = _rules()
        rules.pop("families")
        rules["datasets"] = [
            {"project_key": key, "dataset_dir": "d", "source_root": "s", "tasks": ["slab"],
             "family": key}
            for key in ("a", "b", "c")
        ]  # fmt: skip
        path = tmp_path / "build-v2.json"
        path.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")

        config = load(path)

        assert config.holdout == "families"
        assert config.targets["wall"].label_patterns


def _pdf_project(project: Path, tmp_path: Path) -> Path:
    """Синтетический проект, у которого лист — PDF того же размера в точках, что TIFF в пикселях."""
    copy = tmp_path / "pdf-project"
    shutil.copytree(project, copy)
    page_dir = next((copy / ROOT_NAME / "Pages").iterdir())
    (page_dir / f"{IMAGE_GUID}.tiff").unlink()
    (page_dir / f"{IMAGE_GUID}.pdf").write_bytes(
        pdf_bytes(WIDTH, HEIGHT, [(200, 200, 1800, 210), (400, 400, 600, 600)])
    )
    return copy


class TestPdf:
    def test_page_size_in_points_respects_rotation(self, tmp_path: Path) -> None:
        pytest.importorskip("pypdfium2")
        from planswift_gt.images import pdf_size

        flat = tmp_path / "flat.pdf"
        flat.write_bytes(pdf_bytes(200, 100, []))
        turned = tmp_path / "turned.pdf"
        turned.write_bytes(pdf_bytes(200, 100, [], rotate=90))

        assert pdf_size(flat) == (200.0, 100.0)
        assert pdf_size(turned) == (100.0, 200.0)

    def test_render_puts_ink_where_the_top_left_coordinates_say(self, tmp_path: Path) -> None:
        pytest.importorskip("pypdfium2")
        from planswift_gt.raster import PdfRaster

        path = tmp_path / "page.pdf"
        path.write_bytes(pdf_bytes(200, 100, [(20, 70, 60, 90)]))

        with PdfRaster(path, dpi=144) as raster:
            assert (raster.width, raster.height) == (400, 200)
            assert raster.row(160)[80] < 128
            assert raster.row(20)[80] > 200

    def test_project_with_pdf_page_is_parsed_in_points(self, project: Path, tmp_path: Path) -> None:
        pytest.importorskip("pypdfium2")

        result = parse_project(_pdf_project(project, tmp_path) / ROOT_NAME)

        page = result.pages[0]
        assert page.image is not None and page.image.format == "pdf"
        assert (page.image.width_px, page.image.height_px) == (float(WIDTH), float(HEIGHT))
        slab = next(item for item in result.annotations if item.kind == "polygon")
        assert slab.points_normalized[0] == [200 / WIDTH, 200 / HEIGHT]

    def test_missing_reader_is_a_page_rejection_not_a_crash(
        self, project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = importlib.util.find_spec
        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name, *rest: None if name == "pypdfium2" else original(name, *rest),
        )

        result = parse_project(_pdf_project(project, tmp_path) / ROOT_NAME)

        assert result.pages[0].image is None
        assert result.pages[0].image_rejection == "image_pdf_reader_missing"


def test_ci_really_runs_the_pdf_tests() -> None:
    """В CI отсутствие pypdfium2 — ошибка, а не тихий пропуск тестов PDF.

    `importorskip` удобен на машине без библиотеки, но в CI он превратил бы пропавшую зависимость
    в зелёную сборку: BLOCKED не записывается как PASS.
    """
    if os.environ.get("CI") != "true":
        pytest.skip("проверка только для CI")
    assert importlib.util.find_spec("pypdfium2") is not None
