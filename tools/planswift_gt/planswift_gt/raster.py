"""Растр листа стандартной библиотекой: строки полного разрешения, уменьшенная копия, PNG.

Нужно для визуальной проверки разметки и проверки совмещения координат с растром. Лист целиком в
память не собирается: TIFF читается полосами, разжатая полоса кешируется ограниченно.

Поддержано ровно то, что встречается в листах PlanSwift и проверено тестом: классический TIFF,
один канал, 1/4/8 бит, без сжатия или PackBits, BlackIsZero/WhiteIsZero, полосами. Остальное —
отказ с причиной, а не картинка, похожая на правду.
"""

from __future__ import annotations

import struct
import zlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol, Self

from planswift_gt.images import PDF_POINTS_PER_INCH, ImageRejectedError, pdfium

DEFAULT_PDF_DPI = 200.0


class PageRaster(Protocol):
    """Лист как строки яркости 0…255 — одинаково для TIFF и отрендеренного PDF."""

    width: int
    height: int

    def row(self, y: int) -> bytes: ...

    def close(self) -> None: ...

    def __enter__(self) -> Self: ...

    def __exit__(self, *_: object) -> None: ...


_TAGS = {
    256: "width",
    257: "height",
    258: "bits",
    259: "compression",
    262: "photometric",
    266: "fill_order",
    273: "strip_offsets",
    277: "samples",
    278: "rows_per_strip",
    279: "strip_byte_counts",
    284: "planar",
}
_TYPE_SIZE = {3: 2, 4: 4}
COMPRESSION_NONE = 1
COMPRESSION_PACKBITS = 32773
DARK_BELOW = 128


def _read_tags(stream: BinaryIO) -> dict[str, list[int]]:
    header = stream.read(8)
    if len(header) < 8 or header[:2] not in (b"II", b"MM"):
        raise ImageRejectedError("image_not_tiff", "нет сигнатуры TIFF")
    order = "<" if header[:2] == b"II" else ">"
    if struct.unpack(order + "H", header[2:4])[0] != 42:
        raise ImageRejectedError("image_unsupported_tiff", "не классический TIFF")
    stream.seek(struct.unpack(order + "I", header[4:8])[0])
    count = struct.unpack(order + "H", stream.read(2))[0]
    entries: list[tuple[str, int, int, bytes]] = []
    for _ in range(count):
        tag, kind, items, value = struct.unpack(order + "HHI4s", stream.read(12))
        if tag in _TAGS:
            entries.append((_TAGS[tag], kind, items, value))

    tags: dict[str, list[int]] = {}
    for name, kind, items, value in entries:
        size = _TYPE_SIZE.get(kind)
        if size is None:
            raise ImageRejectedError("image_unsupported_tiff", f"тип тега {name}: {kind}")
        fmt = order + ("H" if kind == 3 else "I") * items
        if size * items <= 4:
            raw = value[: size * items]
        else:
            stream.seek(struct.unpack(order + "I", value)[0])
            raw = stream.read(size * items)
        tags[name] = list(struct.unpack(fmt, raw))
    return tags


def unpackbits(data: bytes, expected: int) -> bytes:
    """PackBits (TIFF 32773). Вывод обрезан ожидаемым размером: битый поток не раздует память."""
    out = bytearray()
    index = 0
    length = len(data)
    while index < length and len(out) < expected:
        header = data[index]
        index += 1
        if header < 128:
            out += data[index : index + header + 1]
            index += header + 1
        elif header > 128:
            if index < length:
                out += bytes((data[index],)) * (257 - header)
            index += 1
    return bytes(out[:expected])


class TiffRaster:
    """Строки листа в яркостях 0 (чёрный) … 255 (белый), по одному байту на пиксель."""

    def __init__(self, path: Path, *, strip_cache: int = 8) -> None:
        self._stream: BinaryIO = path.open("rb")
        try:
            tags = _read_tags(self._stream)
        except Exception:
            self._stream.close()
            raise

        def one(name: str, default: int | None = None) -> int:
            values = tags.get(name)
            if values:
                return values[0]
            if default is None:
                raise ImageRejectedError("image_unsupported_tiff", f"нет тега {name}")
            return default

        self.width = one("width")
        self.height = one("height")
        self.bits = one("bits", 1)
        self.compression = one("compression", COMPRESSION_NONE)
        photometric = one("photometric", 0)
        if one("samples", 1) != 1 or one("planar", 1) != 1 or one("fill_order", 1) != 1:
            raise ImageRejectedError("image_unsupported_tiff", "не один канал или иной порядок бит")
        if self.bits not in (1, 4, 8) or photometric not in (0, 1):
            raise ImageRejectedError(
                "image_unsupported_tiff", f"{self.bits} бит, photometric {photometric}"
            )
        if self.compression not in (COMPRESSION_NONE, COMPRESSION_PACKBITS):
            raise ImageRejectedError("image_unsupported_tiff", f"сжатие {self.compression}")

        self.rows_per_strip = one("rows_per_strip", self.height)
        self._offsets = tags.get("strip_offsets", [])
        self._counts = tags.get("strip_byte_counts", [])
        if not self._offsets or len(self._offsets) != len(self._counts):
            raise ImageRejectedError("image_unsupported_tiff", "полосы описаны неполно")
        self._row_bytes = (self.width * self.bits + 7) // 8
        self._strips: OrderedDict[int, bytes] = OrderedDict()
        self._strip_cache = strip_cache

        maximum = (1 << self.bits) - 1
        levels = bytes(
            round(255 * (value if photometric == 1 else maximum - value) / maximum)
            for value in range(maximum + 1)
        )
        # Таблицы перевода байта файла в яркость: для 4 бит — старший и младший полубайты.
        if self.bits == 8:
            self._table = levels
        elif self.bits == 4:
            self._high = bytes(levels[byte >> 4] for byte in range(256))
            self._low = bytes(levels[byte & 0xF] for byte in range(256))
        else:
            self._bits1 = [
                bytes(levels[(byte >> (7 - bit)) & 1] for bit in range(8)) for byte in range(256)
            ]

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _strip(self, index: int) -> bytes:
        cached = self._strips.get(index)
        if cached is not None:
            self._strips.move_to_end(index)
            return cached
        rows = min(self.rows_per_strip, self.height - index * self.rows_per_strip)
        self._stream.seek(self._offsets[index])
        raw = self._stream.read(self._counts[index])
        expected = rows * self._row_bytes
        data = unpackbits(raw, expected) if self.compression == COMPRESSION_PACKBITS else raw
        data = data.ljust(expected, b"\0")
        self._strips[index] = data
        if len(self._strips) > self._strip_cache:
            self._strips.popitem(last=False)
        return data

    def row(self, y: int) -> bytes:
        """Строка `y` полного разрешения: `width` байт яркости."""
        strip = self._strip(y // self.rows_per_strip)
        start = (y % self.rows_per_strip) * self._row_bytes
        line = strip[start : start + self._row_bytes]
        if self.bits == 8:
            return line.translate(self._table)
        if self.bits == 4:
            out = bytearray(len(line) * 2)
            out[0::2] = line.translate(self._high)
            out[1::2] = line.translate(self._low)
            return bytes(out[: self.width])
        return b"".join(self._bits1[byte] for byte in line)[: self.width]


class PdfRaster:
    """Первая страница PDF, отрендеренная pypdfium2 в оттенках серого при `dpi`.

    Страница рендерится целиком один раз (лист A0 при 200 dpi — около 62 МБ полутона); строки —
    срезы буфера. Поворот страницы применяет сам рендер — так же, как он учтён в размере в точках,
    по которому нормализована разметка.
    """

    def __init__(self, path: Path, *, dpi: float = DEFAULT_PDF_DPI) -> None:
        module = pdfium()
        try:
            document = module.PdfDocument(str(path))
        except Exception as error:
            raise ImageRejectedError("image_pdf_unreadable", type(error).__name__) from error
        try:
            page = document[0]
            bitmap = page.render(
                scale=dpi / PDF_POINTS_PER_INCH, grayscale=True, fill_color=(255, 255, 255, 255)
            )
            self.width: int = int(bitmap.width)
            self.height: int = int(bitmap.height)
            self._stride = int(bitmap.stride)
            self._channels = int(bitmap.n_channels)
            self._buffer = bytes(bitmap.buffer)
            page.close()
        finally:
            document.close()
        self.dpi = dpi

    def row(self, y: int) -> bytes:
        start = y * self._stride
        line = self._buffer[start : start + self.width * self._channels]
        if self._channels == 1:
            return line
        # Порядок каналов pdfium — BGR(A); яркость по весам ITU-R BT.601 в целых.
        blue, green, red = (
            line[0 :: self._channels],
            line[1 :: self._channels],
            line[2 :: self._channels],
        )
        return bytes(
            (29 * b + 150 * g + 77 * r) >> 8 for b, g, r in zip(blue, green, red, strict=True)
        )

    def close(self) -> None:
        self._buffer = b""

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def open_raster(
    path: Path, *, pdf_dpi: float = DEFAULT_PDF_DPI, strip_cache: int = 8
) -> PageRaster:
    """TIFF или PDF по расширению файла листа."""
    if path.suffix.lower() == ".pdf":
        return PdfRaster(path, dpi=pdf_dpi)
    return TiffRaster(path, strip_cache=strip_cache)


@dataclass(frozen=True, slots=True)
class Gray:
    """Уменьшенная копия: пиксель — самый тёмный из четырёх отсчётов блока `step × step`."""

    width: int
    height: int
    step: int
    pixels: bytes


def downscale(raster: PageRaster, *, max_side: int) -> Gray:
    step = max(1, -(-max(raster.width, raster.height) // max_side))
    out_width = -(-raster.width // step)
    out_height = -(-raster.height // step)
    half = step // 2
    rows: list[bytes] = []
    for out_y in range(out_height):
        y = out_y * step
        samples = [raster.row(y)]
        if half and y + half < raster.height:
            samples.append(raster.row(y + half))
        darkest = bytes((255,)) * out_width
        for line in samples:
            a = line[0::step][:out_width]
            # Второй отсчёт по столбцам сохраняет тонкие линии, которые шаг пропустил бы.
            b = line[half::step][:out_width] if half else a
            pooled = bytes(map(min, a, b.ljust(out_width, b"\xff")))
            darkest = bytes(map(min, darkest, pooled))
        rows.append(darkest)
    return Gray(out_width, out_height, step, b"".join(rows))


def working_page(raster: PageRaster, downsample: int) -> Gray:
    """Рабочий растр датасета: целый шаг уменьшения, пиксель — самый тёмный из отсчётов блока.

    Держится в памяти одна рабочая копия листа (при шаге 2 это четверть исходных пикселей по байту),
    а не полный растр; тайлы — срезы этой копии.
    """
    step = max(1, downsample)
    width = raster.width // step
    height = raster.height // step
    half = step // 2
    rows: list[bytes] = []
    for out_y in range(height):
        y = out_y * step
        darkest = bytes((255,)) * width
        for line in (raster.row(y), raster.row(y + half)) if half else (raster.row(y),):
            a = line[0::step][:width]
            b = line[half::step][:width] if half else a
            darkest = bytes(map(min, darkest, map(min, a, b)))
        rows.append(darkest)
    return Gray(width, height, step, b"".join(rows))


def write_png_gray(path: Path, width: int, height: int, pixels: bytes | bytearray) -> None:
    """Полутоновый PNG 8 бит — тайлы и маски."""
    raw = b"".join(b"\0" + bytes(pixels[y * width : (y + 1) * width]) for y in range(height))
    _write_chunks(path, struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0), raw)


def _write_chunks(path: Path, header: bytes, raw: bytes) -> None:
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def write_png(path: Path, width: int, height: int, rgb: bytes | bytearray) -> None:
    """RGB 8 бит. Без метаданных времени: одинаковый вход — одинаковые байты."""
    stride = width * 3
    raw = b"".join(b"\0" + bytes(rgb[y * stride : (y + 1) * stride]) for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )
