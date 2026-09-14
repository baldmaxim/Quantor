"""Кодировка XML, размер TIFF и оглавление архива."""

from __future__ import annotations

import codecs
from pathlib import Path

import pytest

from planswift_gt.archive import ArchiveRejectedError, check_listing
from planswift_gt.images import ImageRejectedError, tiff_size
from planswift_gt.xmlio import XmlRejectedError, decode, parse_text
from tests.synthetic import tiff_bytes

DECLARED_UTF8 = '<?xml version="1.0" encoding="UTF-8"?>\n<Item Name="Стены"/>'


class TestDecode:
    def test_utf8_declared_but_cp1251_bytes_falls_back_and_is_counted(self) -> None:
        decoded = decode(DECLARED_UTF8.encode("cp1251"))

        assert decoded.encoding == "cp1251"
        assert decoded.fallback is True
        assert decoded.declared == "UTF-8"
        assert parse_text(decoded.text).get("Name") == "Стены"

    def test_real_utf8_is_not_a_fallback(self) -> None:
        decoded = decode(DECLARED_UTF8.encode("utf-8"))

        assert (decoded.encoding, decoded.fallback) == ("utf-8", False)

    def test_bom_wins(self) -> None:
        decoded = decode(codecs.BOM_UTF8 + DECLARED_UTF8.encode("utf-8"))

        assert decoded.encoding == "utf-8"
        assert parse_text(decoded.text).get("Name") == "Стены"

    def test_explicit_non_utf8_declaration_is_honoured(self) -> None:
        text = '<?xml version="1.0" encoding="windows-1251"?><Item Name="Плита"/>'
        decoded = decode(text.encode("cp1251"))

        assert decoded.encoding == "cp1251"
        assert decoded.fallback is False

    def test_doctype_is_rejected_before_parsing(self) -> None:
        with pytest.raises(XmlRejectedError) as error:
            parse_text('<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')

        assert error.value.reason == "forbidden_dtd"


class TestTiff:
    @pytest.mark.parametrize("big_endian", [False, True])
    def test_reads_size_in_both_byte_orders(self, tmp_path: Path, big_endian: bool) -> None:
        path = tmp_path / "page.tiff"
        path.write_bytes(tiff_bytes(8608, 6081, big_endian=big_endian))

        assert tiff_size(path) == (8608, 6081)

    def test_bigtiff_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "big.tiff"
        path.write_bytes(b"II+\x00\x08\x00\x00\x00" + b"\x00" * 16)

        with pytest.raises(ImageRejectedError) as error:
            tiff_size(path)
        assert error.value.reason == "image_unsupported_tiff"


class TestArchiveListing:
    @pytest.mark.parametrize("path", ["..\\escape\\Data.xml", "C:\\Windows\\x", "/etc/passwd"])
    def test_escaping_paths_are_refused(self, path: str) -> None:
        with pytest.raises(ArchiveRejectedError):
            check_listing(["project\\Data.xml", path], [10, 10])

    def test_unpacked_size_is_bounded(self) -> None:
        with pytest.raises(ArchiveRejectedError):
            check_listing(["a", "b"], [600, 600], limit=1000)

    def test_normal_listing_passes(self) -> None:
        check_listing(["Проект\\Pages\\Лист\\Data.xml"], [4960])
