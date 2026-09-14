"""Чтение полутоновых PNG стандартной библиотекой (промт 10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from quantor_vision.png import PngError, read_gray
from tests.synthetic_build import _png


class TestPng:
    @pytest.mark.parametrize("filter_type", [0, 2])
    def test_reads_gray_with_filters(self, tmp_path: Path, filter_type: int) -> None:
        pixels = bytes((x * 7 + y * 3) % 256 for y in range(5) for x in range(6))
        _png(tmp_path / "a.png", 6, 5, pixels, filter_type=filter_type)

        assert read_gray(tmp_path / "a.png") == (6, 5, pixels)

    def test_rejects_non_png(self, tmp_path: Path) -> None:
        (tmp_path / "x.png").write_bytes(b"not a png")
        with pytest.raises(PngError):
            read_gray(tmp_path / "x.png")
