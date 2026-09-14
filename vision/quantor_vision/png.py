"""Чтение полутоновых PNG сборки промта 08 стандартной библиотекой.

Сборщик пишет тайлы и маски 8-битным полутоном; здесь поддержаны все пять фильтров строк PNG,
чтобы файл, пересохранённый сторонней программой, не читался молча неверно. Другие форматы —
отказ.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PngError(ValueError):
    pass


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def read_gray(path: Path) -> tuple[int, int, bytes]:
    """Возвращает ширину, высоту и пиксели 0..255 построчно."""
    data = path.read_bytes()
    if not data.startswith(SIGNATURE):
        raise PngError(f"{path}: не PNG")
    offset = len(SIGNATURE)
    width = height = 0
    idat = bytearray()
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        chunk_type = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or color != 0 or interlace != 0:
                raise PngError(f"{path}: ожидается полутон 8 бит без чересстрочности")
        elif chunk_type == b"IDAT":
            idat += body
        elif chunk_type == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    stride = width
    if len(raw) != height * (stride + 1):
        raise PngError(f"{path}: размер данных {len(raw)} не сходится с {width}×{height}")

    rows: list[bytes] = []
    previous = bytes(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind = raw[start]
        line = raw[start + 1 : start + 1 + stride]
        if kind == 0:
            current = line
        elif kind == 2:
            current = bytes((v + p) & 0xFF for v, p in zip(line, previous, strict=True))
        else:
            out = bytearray(stride)
            for x in range(stride):
                left = out[x - 1] if x else 0
                up = previous[x]
                upper_left = previous[x - 1] if x else 0
                if kind == 1:
                    predictor = left
                elif kind == 3:
                    predictor = (left + up) // 2
                elif kind == 4:
                    predictor = _paeth(left, up, upper_left)
                else:
                    raise PngError(f"{path}: неизвестный фильтр строки {kind}")
                out[x] = (line[x] + predictor) & 0xFF
            current = bytes(out)
        rows.append(current)
        previous = current
    return width, height, b"".join(rows)
