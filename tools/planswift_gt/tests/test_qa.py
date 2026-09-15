"""Растр, оверлеи, совмещение, расширенная проверка и карточка датасета (промт 07)."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from planswift_gt import card, qa
from planswift_gt.cli import main
from planswift_gt.manifest import (
    ANNOTATIONS,
    MANIFEST,
    dataset_fingerprint,
    findings,
    validate,
)
from planswift_gt.raster import TiffRaster, downscale, unpackbits, write_png
from tests.synthetic import GUIDS, HEIGHT, WIDTH, packbits, tiff_image

ROOT_NAME = "Синтетика кладка"


def _convert(project: Path, out: Path) -> None:
    code = main(
        [
            "convert",
            str(project),
            "--project-key",
            "synthetic",
            "--out",
            str(out),
            "--allow-inside-repo",
        ]
    )
    assert code == 0


def _rewrite_with_hashes(dataset: Path, name: str, text: str) -> None:
    """Подмена содержимого с честно пересчитанными хешами: ловить её должна уже семантика."""
    (dataset / name).write_text(text, encoding="utf-8")
    manifest = json.loads((dataset / MANIFEST).read_text(encoding="utf-8"))

    manifest["files"][name] = hashlib.sha256((dataset / name).read_bytes()).hexdigest()
    manifest["dataset_fingerprint"] = dataset_fingerprint(manifest["files"])
    (dataset / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")


class TestRaster:
    def test_packbits_roundtrip(self) -> None:
        data = bytes([0] * 300 + [1, 2, 3] + [9] * 5 + list(range(200)))

        assert unpackbits(packbits(data), len(data)) == data

    def test_truncated_packbits_never_exceeds_expected_size(self) -> None:
        assert len(unpackbits(bytes([0x81, 7] * 1000), 10)) == 10

    @pytest.mark.parametrize(
        ("bits", "compress", "rows_per_strip"), [(4, True, None), (8, False, 7)]
    )
    def test_rows_decode_to_luminance(
        self, tmp_path: Path, bits: int, compress: bool, rows_per_strip: int | None
    ) -> None:
        width, height = 21, 17
        luminance = bytearray(b"\xff" * (width * height))
        luminance[5 * width + 3] = 0
        path = tmp_path / "page.tiff"
        path.write_bytes(
            tiff_image(
                width,
                height,
                luminance,
                bits=bits,
                compress=compress,
                rows_per_strip=rows_per_strip,
            )
        )

        with TiffRaster(path) as raster:
            assert (raster.width, raster.height) == (width, height)
            assert raster.row(5)[3] == 0
            assert raster.row(5)[4] == 255
            assert raster.row(16) == b"\xff" * width

    def test_downscale_keeps_a_one_pixel_line(self, tmp_path: Path) -> None:
        width, height = 400, 400
        luminance = bytearray(b"\xff" * (width * height))
        for x in range(width):
            luminance[202 * width + x] = 0  # строка, которую шаг 4 без второго отсчёта пропустил бы
        path = tmp_path / "line.tiff"
        path.write_bytes(tiff_image(width, height, luminance))

        with TiffRaster(path) as raster:
            gray = downscale(raster, max_side=100)

        assert gray.step == 4
        assert min(gray.pixels[50 * gray.width : 51 * gray.width]) == 0

    def test_png_is_well_formed(self, tmp_path: Path) -> None:
        path = tmp_path / "out.png"
        write_png(path, 3, 2, bytes(range(18)))
        data = path.read_bytes()

        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", data[16:24]) == (3, 2)
        idat = data.index(b"IDAT")
        length = struct.unpack(">I", data[idat - 4 : idat])[0]
        assert len(zlib.decompress(data[idat + 4 : idat + 4 + length])) == 2 * (1 + 9)


class TestAlignmentAndOverlays:
    def test_true_geometry_peaks_at_zero_offset(self, project: Path, tmp_path: Path) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)

        summary = qa.run(dataset, project / ROOT_NAME, tmp_path / "qa", debug_pages=1, max_side=800)

        assert summary["pages_aligned"] == 1
        page = summary["pages_report"]
        assert isinstance(page, list)
        assert page[0]["alignment"]["best_offset_px"] == [0, 0]

    def test_shifted_geometry_is_not_aligned(self, project: Path, tmp_path: Path) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        rows = [
            json.loads(line)
            for line in (dataset / ANNOTATIONS).read_text(encoding="utf-8").splitlines()
        ]
        # Совмещение проверяется по нормализованным координатам (они общие для TIFF и PDF),
        # поэтому сдвиг применяется к обоим представлениям точек одинаково.
        shifted = [
            {
                **row["annotation"],
                "points_source_px": [
                    [x + 30, y + 30] for x, y in row["annotation"]["points_source_px"]
                ],
                "points_normalized": [
                    [x + 30 / WIDTH, y + 30 / HEIGHT]
                    for x, y in row["annotation"]["points_normalized"]
                ],
            }
            for row in rows
        ]

        with TiffRaster(
            project
            / ROOT_NAME
            / next(
                json.loads(line)["image"]["path"]
                for line in (dataset / "pages.jsonl").read_text(encoding="utf-8").splitlines()
            )
        ) as raster:
            probe = qa.alignment(raster, shifted)

        assert not probe.aligned
        assert probe.best_offset_px != (0, 0)
        assert probe.score_at_zero < probe.best_score

    def test_overlays_and_debug_legend_are_deterministic(
        self, project: Path, tmp_path: Path
    ) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        first = qa.run(dataset, project / ROOT_NAME, tmp_path / "a", debug_pages=1, max_side=800)
        qa.run(dataset, project / ROOT_NAME, tmp_path / "b", debug_pages=1, max_side=800)

        for name in ("page-001.png", "page-001-debug.png", "qa-report.json"):
            assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
        report = first["pages_report"]
        assert isinstance(report, list)
        assert set(report[0]["debug_legend"].values()) == {
            GUIDS.linear,
            GUIDS.duplicate,
            GUIDS.area,
            GUIDS.hole,
            GUIDS.count,
        }

    def test_qa_refuses_to_write_inside_a_repository(self, project: Path, tmp_path: Path) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)

        code = main(
            ["qa", str(dataset), "--source", str(project / ROOT_NAME), "--out", str(repo / "qa")]
        )

        assert code == 2


class TestValidation:
    def test_normalization_tampering_is_caught_even_with_fresh_hashes(
        self, project: Path, tmp_path: Path
    ) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        rows = (dataset / ANNOTATIONS).read_text(encoding="utf-8").splitlines()
        row = json.loads(rows[0])
        row["annotation"]["points_normalized"][0][0] += 0.001
        rows[0] = json.dumps(row, ensure_ascii=False)
        _rewrite_with_hashes(dataset, ANNOTATIONS, "\n".join(rows) + "\n")

        assert any("нормализация" in problem.message for problem in validate(dataset))

    def test_placeholder_in_source_pixels_is_caught(self, project: Path, tmp_path: Path) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        rows = (dataset / ANNOTATIONS).read_text(encoding="utf-8").splitlines()
        row = json.loads(rows[0])
        row["annotation"]["points_source_px"][0] = [-1, -1]
        rows[0] = json.dumps(row, ensure_ascii=False)
        _rewrite_with_hashes(dataset, ANNOTATIONS, "\n".join(rows) + "\n")

        assert any("заглушка" in problem.message for problem in validate(dataset))

    def test_fingerprint_mismatch_is_caught(self, project: Path, tmp_path: Path) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        manifest = json.loads((dataset / MANIFEST).read_text(encoding="utf-8"))
        manifest["dataset_fingerprint"] = "0" * 64
        (dataset / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

        assert any("dataset_fingerprint" in problem.message for problem in validate(dataset))

    def test_duplicates_are_reported_not_hidden(self, project: Path, tmp_path: Path) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)

        report = findings(dataset)

        assert report["duplicate_geometry_groups"] == 1
        assert report["duplicate_geometry_examples"] == [sorted([GUIDS.linear, GUIDS.duplicate])]

    def test_reparse_reproduces_the_fingerprint(
        self, project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        capsys.readouterr()

        code = main(["validate", str(dataset), "--reparse", str(project)])

        assert code == 0
        assert json.loads(capsys.readouterr().out)["reparse_matches"] is True

    def test_changed_source_is_reported_on_reparse(self, project: Path, tmp_path: Path) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        target = project / ROOT_NAME / "Takeoff" / "Двери" / "Data.xml"
        target.write_bytes(target.read_bytes().replace(b"</Item>", b"</Item>\n"))

        assert main(["validate", str(dataset), "--reparse", str(project)]) == 1


class TestCard:
    def test_card_has_metadata_but_no_page_names(self, project: Path, tmp_path: Path) -> None:
        dataset = tmp_path / "gt"
        _convert(project, dataset)
        manifest = json.loads((dataset / MANIFEST).read_text(encoding="utf-8"))

        text = card.build(dataset)

        assert "`synthetic`" in text
        assert manifest["dataset_fingerprint"] in text
        assert "placeholder_coordinates" in text
        assert "xml_cp1251_fallback" in text
        assert "polyline · Стены [толщина 250]" in text
        assert "Лист 1" not in text
        assert ROOT_NAME not in text
        assert f"{WIDTH}" not in text or f"{HEIGHT}" not in text
