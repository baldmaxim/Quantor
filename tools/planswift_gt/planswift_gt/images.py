"""Размер и отпечаток листа: TIFF — стандартной библиотекой, PDF — через pypdfium2.

Нужны только размер системы координат разметки и SHA-256: пиксели импортёр не читает.

- **TIFF** (II/MM, 42) разбирается по первому IFD; координаты PlanSwift — пиксели растра.
  BigTIFF и прочее — отказ с причиной, а не догадка.
- **PDF** (Р-9): координаты PlanSwift — точки PDF первой страницы (72 dpi) с учётом поворота
  страницы; правило взято у SU10 (`build_canonical_v2.py`) и проверяется оверлеями QA. Размер —
  дробный, в точках; растр для тайлов рендерится позже с `pdf_render_dpi` сборки.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import struct
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

PDF_POINTS_PER_INCH = 72.0

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
    # Размер системы координат разметки: пиксели TIFF (целые) или точки PDF (дробные). Имя поля
    # сохранено ради совместимости planswift-gt-v1: у TIFF значения и отпечатки не меняются.
    width_px: float
    height_px: float
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


PAGE_IMAGE_SUFFIXES = (".tif", ".tiff", ".pdf")


def pdfium() -> ModuleType:
    """Модуль pypdfium2 или отказ с причиной: PDF без него не читается, а не пропускается молча.

    Импорт в момент вызова: импортёр TIFF по-прежнему работает на одной стандартной библиотеке.
    """
    if importlib.util.find_spec("pypdfium2") is None:
        raise ImageRejectedError("image_pdf_reader_missing", "не установлен pypdfium2 (extra pdf)")
    return importlib.import_module("pypdfium2")


def pdf_size(path: Path) -> tuple[float, float]:
    """Ширина и высота первой страницы в точках с учётом /Rotate."""
    module = pdfium()
    try:
        document = module.PdfDocument(str(path))
    except Exception as error:
        raise ImageRejectedError("image_pdf_unreadable", type(error).__name__) from error
    try:
        if len(document) < 1:
            raise ImageRejectedError("image_pdf_empty", "в PDF нет страниц")
        page = document[0]
        width, height = page.get_size()
        page.close()
    finally:
        document.close()
    if not (width > 0 and height > 0):
        raise ImageRejectedError("image_no_size", f"размер страницы {width}×{height}")
    return float(width), float(height)


def inspect_image(path: Path) -> ImageInfo:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        width_pt, height_pt = pdf_size(path)
        return ImageInfo(
            width_px=width_pt,
            height_px=height_pt,
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
            format="pdf",
        )
    width, height = tiff_size(path)
    return ImageInfo(
        width_px=width,
        height_px=height,
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        format="tiff",
    )
