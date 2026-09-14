"""Синтетическая сборка промта 08 для тестов промта 10: PNG-запись, тайлы плиты с отверстием."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

TILE = 32


def _png(path: Path, width: int, height: int, pixels: bytes, *, filter_type: int = 0) -> None:
    rows = []
    previous = bytes(width)
    for y in range(height):
        line = pixels[y * width : (y + 1) * width]
        if filter_type == 2:
            encoded = bytes((v - p) & 0xFF for v, p in zip(line, previous, strict=True))
        else:
            encoded = line
        rows.append(bytes((filter_type,)) + encoded)
        previous = line

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + chunk(b"IEND", b"")
    )


def _slab(width: int, height: int, *, offset: int) -> tuple[bytes, bytes]:
    """Плита с отверстием: на изображении — контуры чернилами, в маске — тело без отверстия."""
    image = bytearray([255] * (width * height))
    mask = bytearray(width * height)
    left, right = 6 + offset % 5, 26 - offset % 3
    for y in range(6, 26):
        for x in range(left, right):
            inside_hole = 13 <= x < 18 and 13 <= y < 18
            if not inside_hole:
                mask[y * width + x] = 255
            border = (
                x in (left, right - 1)
                or y in (6, 25)
                or (inside_hole and (x in (13, 17) or y in (13, 17)))
            )
            if border:
                image[y * width + x] = 0
            elif not inside_hole:
                image[y * width + x] = 200
    return bytes(image), bytes(mask)


def make_build(root: Path, *, per_split: dict[str, int], valid: int = TILE) -> Path:
    """Сборка в формате промта 08: tiles.jsonl, тайлы, маски, split.json, build.json."""
    lines = []
    for split, count in per_split.items():
        for index in range(count):
            tile_id = f"{split}{index:03d}"
            image, mask = _slab(TILE, TILE, offset=index)
            if valid < TILE:
                image = bytes(p if (i % TILE) < valid else 255 for i, p in enumerate(image))
                mask = bytes(p if (i % TILE) < valid else 0 for i, p in enumerate(mask))
            _png(root / "tiles" / f"{tile_id}.png", TILE, TILE, image)
            _png(root / "targets" / "slab" / f"{tile_id}.png", TILE, TILE, mask)
            lines.append(
                {
                    "tile_id": tile_id,
                    "page_guid": f"page-{split}-{index % 2}",
                    "split": split,
                    "crop_policy": "grid",
                    "tasks": ["slab"],
                    "image": f"tiles/{tile_id}.png",
                    "transform": {
                        "tile_px": TILE,
                        "valid_size": [valid, TILE],
                        "origin_working_px": [0, 0],
                        "working_size": [TILE, TILE],
                    },
                }
            )
    tiles = "".join(json.dumps(line) + "\n" for line in lines)
    (root / "tiles.jsonl").write_text(tiles, encoding="utf-8")
    (root / "build.json").write_text(
        json.dumps(
            {
                "split_sha256": "c" * 64,
                "tiles_sha256": hashlib.sha256(tiles.encode("utf-8")).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    return root
