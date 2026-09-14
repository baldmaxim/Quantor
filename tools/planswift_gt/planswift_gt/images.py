"""Размер и отпечаток растра листа без сторонних библиотек.

Нужны только ширина, высота и SHA-256: пиксели импортёр не читает. Классический TIFF (II/MM, 42)
разбирается по первому IFD; BigTIFF и прочее — отказ с причиной, а не догадка.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

_TAG_WIDTH = 256
_TAG_HEIGHT = 257
_TYPE_SHORT = 3
_TYPE_LONG = 4


class ImageRejectedError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ImageInfo:
    width_px: int
    height_px: int
    sha256: str
    size_bytes: int
    format: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tiff_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(8)
        if len(header) < 8 or header[:2] not in (b"II", b"MM"):
            raise ImageRejectedError("image_not_tiff", "нет сигнатуры TIFF")
        order = "<" if header[:2] == b"II" else ">"
        magic = struct.unpack(order + "H", header[2:4])[0]
        if magic != 42:
            raise ImageRejectedError("image_unsupported_tiff", f"сигнатура {magic}, ожидается 42")
        offset = struct.unpack(order + "I", header[4:8])[0]
        stream.seek(offset)
        raw_count = stream.read(2)
        if len(raw_count) < 2:
            raise ImageRejectedError("image_truncated", "нет каталога IFD")
        count = struct.unpack(order + "H", raw_count)[0]
        width: int | None = None
        height: int | None = None
        for _ in range(count):
            entry = stream.read(12)
            if len(entry) < 12:
                raise ImageRejectedError("image_truncated", "каталог IFD обрезан")
            tag, kind, _items, value = struct.unpack(order + "HHI4s", entry)
            if tag not in (_TAG_WIDTH, _TAG_HEIGHT):
                continue
            if kind == _TYPE_SHORT:
                number = int(struct.unpack(order + "H", value[:2])[0])
            elif kind == _TYPE_LONG:
                number = int(struct.unpack(order + "I", value)[0])
            else:
                raise ImageRejectedError("image_unsupported_tiff", f"тип тега размера {kind}")
            if tag == _TAG_WIDTH:
                width = number
            else:
                height = number
    if not width or not height:
        raise ImageRejectedError("image_no_size", "в первом IFD нет ширины или высоты")
    return width, height


def inspect_image(path: Path) -> ImageInfo:
    width, height = tiff_size(path)
    return ImageInfo(
        width_px=width,
        height_px=height,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        format="tiff",
    )
