"""Безопасность чтения архива и разбор пакета.

Архив недоверенный, поэтому здесь собраны именно попытки навредить: выход за пределы
каталога, бомба сжатия, ссылки, посторонние файлы. Базы данных эти проверки не требуют.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest

from app.errors import DomainError, ErrorCode
from app.services.legacy import archive as archive_reader
from app.services.legacy import markdown, package
from app.services.legacy.archive import ArchiveLimits

PDF_BYTES = b"%PDF-1.7\n" + b"0" * 256
BASE_NAME = "01-03-00-01-12_ПД-00260560-АР"

DEFAULT_LIMITS = ArchiveLimits()


def blocks_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "coordinate_space": "normalized_page_top_left",
        "pages": [
            {"page_index": 0, "width_px": 2481, "height_px": 3509, "rotation": 0},
            {"page_index": 1, "width_px": 2481, "height_px": 3509, "rotation": 0},
        ],
        "blocks": [
            {
                "block_id": "blk_text_1",
                "ordinal": 1,
                "page_index": 0,
                "page_label": 1,
                "block_type": "text",
                "shape_type": "rectangle",
                "status": "recognized",
                "export_status": "recognized",
                "coords_norm": [0.1, 0.1, 0.9, 0.4],
                "polygon_points": None,
                "crop_url": "https://example.invalid/api/crops/1",
            },
            {
                "block_id": "blk_stamp_2",
                "ordinal": None,
                "page_index": 1,
                "page_label": 2,
                "block_type": "stamp",
                "shape_type": "rectangle",
                "status": "recognized",
                "coords_norm": [0.7, 0.9, 0.98, 0.99],
                "polygon_points": None,
                "crop_url": None,
            },
        ],
    }
    payload.update(overrides)
    return payload


def build_package(
    *,
    blocks: dict[str, Any] | str | None = None,
    with_md: bool = True,
    with_html: bool = False,
    extra: dict[str, bytes] | None = None,
    omit_pdf: bool = False,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if not omit_pdf:
            archive.writestr(f"{BASE_NAME}.pdf", PDF_BYTES)
        if blocks is not None:
            raw = blocks if isinstance(blocks, str) else json.dumps(blocks, ensure_ascii=False)
            archive.writestr(f"{BASE_NAME}_blocks.json", raw)
        if with_md:
            archive.writestr(
                f"{BASE_NAME}_results.md",
                "### BLOCK #1 [TEXT]: blk_text_1\n\n"
                "**Summary:** План 3-го этажа, оси 1–14.\n"
                "**Description:** Планировка жилой секции.\n",
            )
        if with_html:
            archive.writestr(f"{BASE_NAME}_results.html", "<html><body>отчёт</body></html>")
        for name, payload in (extra or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _inspect(data: bytes, limits: ArchiveLimits = DEFAULT_LIMITS) -> list[Any]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive_reader.inspect(archive, limits)


class TestArchiveSafety:
    def test_valid_package_passes(self) -> None:
        members = _inspect(build_package(blocks=blocks_payload()))

        assert {member.extension for member in members} == {"pdf", "json", "md"}

    @pytest.mark.parametrize(
        "path",
        [
            "../../../etc/passwd.pdf",
            "..\\..\\windows\\system32\\config.pdf",
            "/etc/shadow.pdf",
            "C:/Windows/system.pdf",
            "вложенная/../../../побег.pdf",
        ],
    )
    def test_path_traversal_is_rejected(self, path: str) -> None:
        data = build_package(blocks=blocks_payload(), extra={path: b"payload"})

        with pytest.raises(DomainError) as error:
            _inspect(data)

        assert error.value.code is ErrorCode.ARCHIVE_UNSAFE_PATH

    def test_unexpected_file_type_is_rejected(self) -> None:
        data = build_package(blocks=blocks_payload(), extra={"payload.exe": b"MZ\x90\x00"})

        with pytest.raises(DomainError) as error:
            _inspect(data)

        assert error.value.code is ErrorCode.ARCHIVE_UNSAFE_PATH

    def test_symlink_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(f"{BASE_NAME}.pdf", PDF_BYTES)
            info = zipfile.ZipInfo("ссылка.pdf")
            # 0o120777 — символическая ссылка в старших битах внешних атрибутов.
            info.external_attr = (0o120777 << 16) | 0o777
            archive.writestr(info, "/etc/passwd")

        with pytest.raises(DomainError) as error:
            _inspect(buffer.getvalue())

        assert error.value.code is ErrorCode.ARCHIVE_UNSAFE_PATH

    def test_zip_bomb_ratio_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{BASE_NAME}.pdf", PDF_BYTES)
            # Один мегабайт нулей сжимается в тысячи раз.
            archive.writestr(f"{BASE_NAME}_blocks.json", b"\x00" * (1024 * 1024))

        with pytest.raises(DomainError) as error:
            _inspect(buffer.getvalue())

        assert error.value.code is ErrorCode.ARCHIVE_LIMIT_EXCEEDED

    def test_too_many_files_is_rejected(self) -> None:
        extra = {f"файл_{index}.txt": b"x" for index in range(20)}
        data = build_package(blocks=blocks_payload(), extra=extra)

        with pytest.raises(DomainError) as error:
            _inspect(data, ArchiveLimits(max_files=5))

        assert error.value.code is ErrorCode.ARCHIVE_LIMIT_EXCEEDED

    def test_total_size_limit_is_enforced(self) -> None:
        data = build_package(blocks=blocks_payload())

        with pytest.raises(DomainError) as error:
            _inspect(data, ArchiveLimits(max_total_uncompressed_bytes=10))

        assert error.value.code is ErrorCode.ARCHIVE_LIMIT_EXCEEDED

    def test_declared_size_is_not_trusted_when_reading(self) -> None:
        """Оглавление обещает размер, но читаем всё равно с ограничением."""
        data = build_package(blocks=blocks_payload())
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive_reader.inspect(archive, DEFAULT_LIMITS)
            pdf = next(member for member in members if member.extension == "pdf")

            with pytest.raises(DomainError) as error:
                archive_reader.read_member(archive, pdf, max_bytes=16)

        assert error.value.code is ErrorCode.ARCHIVE_LIMIT_EXCEEDED


class TestNameDecoding:
    def test_cyrillic_names_with_utf8_flag(self) -> None:
        members = _inspect(build_package(blocks=blocks_payload()))

        assert any("ПД" in member.name for member in members)

    def test_cyrillic_names_without_utf8_flag(self) -> None:
        """Старые архиваторы не ставят флаг UTF-8 и пишут имена в кодировке DOS.

        Такой архив нельзя собрать штатным writer'ом — он сам поставит флаг, — поэтому
        проверяется само декодирование записи оглавления.
        """
        info = zipfile.ZipInfo()
        info.flag_bits = 0
        info.orig_filename = "чертёж.pdf".encode("cp866").decode("cp437")

        assert archive_reader.decode_member_name(info) == "чертёж.pdf"

    def test_utf8_flag_wins_over_fallback(self) -> None:
        info = zipfile.ZipInfo("план 3 этажа.pdf")
        info.flag_bits |= 0x800

        assert archive_reader.decode_member_name(info) == "план 3 этажа.pdf"


class TestPackageLayout:
    def test_missing_pdf_is_reported(self) -> None:
        members = _inspect(build_package(blocks=blocks_payload(), omit_pdf=True))

        with pytest.raises(DomainError) as error:
            package.locate(members)

        assert error.value.code is ErrorCode.LEGACY_PDF_MISSING

    def test_missing_blocks_is_reported(self) -> None:
        members = _inspect(build_package(blocks=None, with_md=False))

        with pytest.raises(DomainError) as error:
            package.locate(members)

        assert error.value.code is ErrorCode.LEGACY_BLOCKS_INVALID

    def test_html_is_optional(self) -> None:
        layout = package.locate(_inspect(build_package(blocks=blocks_payload())))

        assert layout.results_html is None
        assert layout.results_md is not None


class TestBlocksValidation:
    def test_valid_document(self) -> None:
        document = package.parse_blocks(json.dumps(blocks_payload()).encode())

        assert document.schema_version == 1
        assert len(document.pages) == 2
        assert len(document.blocks) == 2

    def test_crop_url_lands_in_metadata_untouched(self) -> None:
        document = package.parse_blocks(json.dumps(blocks_payload()).encode())

        metadata = document.blocks[0].legacy_metadata

        assert metadata["crop_url"] == "https://example.invalid/api/crops/1"

    def test_invalid_json(self) -> None:
        with pytest.raises(DomainError) as error:
            package.parse_blocks(b"{ not json")

        assert error.value.code is ErrorCode.LEGACY_BLOCKS_INVALID

    def test_unsupported_schema_version(self) -> None:
        with pytest.raises(DomainError) as error:
            package.parse_blocks(json.dumps(blocks_payload(schema_version=2)).encode())

        assert error.value.code is ErrorCode.LEGACY_SCHEMA_UNSUPPORTED

    def test_unsupported_coordinate_space(self) -> None:
        payload = blocks_payload(coordinate_space="pdf_user_space_bottom_left")

        with pytest.raises(DomainError) as error:
            package.parse_blocks(json.dumps(payload).encode())

        assert error.value.code is ErrorCode.LEGACY_SCHEMA_UNSUPPORTED

    @pytest.mark.parametrize(
        "coords",
        [[0.1, 0.1, 0.9], [1.5, 0.1, 0.9, 0.4], [-0.1, 0.1, 0.9, 0.4], [0.9, 0.1, 0.1, 0.4]],
    )
    def test_invalid_coordinates(self, coords: list[float]) -> None:
        payload = blocks_payload()
        payload["blocks"][0]["coords_norm"] = coords

        with pytest.raises(DomainError) as error:
            package.parse_blocks(json.dumps(payload).encode())

        assert error.value.code is ErrorCode.LEGACY_BLOCKS_INVALID

    def test_polygon_without_points_is_rejected(self) -> None:
        payload = blocks_payload()
        payload["blocks"][0]["shape_type"] = "polygon"

        with pytest.raises(DomainError) as error:
            package.parse_blocks(json.dumps(payload).encode())

        assert error.value.code is ErrorCode.LEGACY_BLOCKS_INVALID

    def test_polygon_with_points_is_accepted(self) -> None:
        payload = blocks_payload()
        payload["blocks"][0]["shape_type"] = "polygon"
        payload["blocks"][0]["polygon_points"] = [[0.1, 0.1], [0.9, 0.1], [0.5, 0.8]]

        document = package.parse_blocks(json.dumps(payload).encode())

        assert document.blocks[0].polygon_points is not None

    def test_duplicate_block_id_is_rejected(self) -> None:
        payload = blocks_payload()
        payload["blocks"][1]["block_id"] = payload["blocks"][0]["block_id"]

        with pytest.raises(DomainError) as error:
            package.parse_blocks(json.dumps(payload).encode())

        assert error.value.code is ErrorCode.LEGACY_BLOCKS_INVALID

    def test_block_pointing_to_missing_page_is_rejected(self) -> None:
        payload = blocks_payload()
        payload["blocks"][0]["page_index"] = 99

        with pytest.raises(DomainError) as error:
            package.parse_blocks(json.dumps(payload).encode())

        assert error.value.code is ErrorCode.LEGACY_BLOCKS_INVALID


class TestMarkdownIndex:
    def test_sections_are_indexed_by_block_id(self) -> None:
        text = (
            "# Отчёт\n\n"
            "### BLOCK #1 [TEXT]: blk_one\n\n**Summary:** Первый блок\n\n"
            "### BLOCK #2 [IMAGE]: blk_two\n\n**Summary:** Второй блок\n"
        )

        sections = markdown.index_sections(text)

        assert set(sections) == {"blk_one", "blk_two"}
        assert "Первый блок" in sections["blk_one"]
        assert "Второй" in sections["blk_two"]
        assert "Первый" not in sections["blk_two"]

    def test_heading_without_ordinal_and_type(self) -> None:
        sections = markdown.index_sections("### BLOCK: blk_solo\n\nтекст\n")

        assert sections["blk_solo"] == "текст"

    def test_file_without_headings_gives_empty_index(self) -> None:
        assert markdown.index_sections("обычный текст без заголовков") == {}

    def test_markdown_is_not_interpreted(self) -> None:
        """Разметка сохраняется как есть и не превращается в HTML."""
        text = "### BLOCK #1 [TEXT]: blk_one\n\n<script>alert(1)</script>\n"

        sections = markdown.index_sections(text)

        assert sections["blk_one"] == "<script>alert(1)</script>"

    def test_broken_encoding_does_not_fail(self) -> None:
        assert markdown.decode(b"\xff\xfe irregular") is not None
