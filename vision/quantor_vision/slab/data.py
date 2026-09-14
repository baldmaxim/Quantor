"""Тайлы плиты из замороженной сборки промта 08.

Разбиение не пересчитывается и не фильтруется по результатам: тайлы берутся из `tiles.jsonl`
по полю `split` ровно так, как их записал сборщик. Заливка за краем листа в потерю и метрики не
входит — для неё строится маска допустимой области.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import torch

from quantor_vision.png import read_gray

TASK = "slab"


@dataclass(frozen=True, slots=True)
class TileRef:
    tile_id: str
    page_guid: str
    split: str
    crop_policy: str
    image: Path
    target: Path
    tile_px: int
    valid_width: int
    valid_height: int
    origin: tuple[int, int]
    working_size: tuple[int, int]


@dataclass(frozen=True, slots=True)
class BuildInfo:
    root: Path
    split_sha256: str
    tiles_sha256: str
    tiles: list[TileRef]


def load_build(root: Path) -> BuildInfo:
    manifest = json.loads((root / "build.json").read_text(encoding="utf-8"))
    tiles: list[TileRef] = []
    for line in (root / "tiles.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if TASK not in row["tasks"]:
            continue
        transform = row["transform"]
        tiles.append(
            TileRef(
                tile_id=row["tile_id"],
                page_guid=row["page_guid"],
                split=row["split"],
                crop_policy=row["crop_policy"],
                image=root / row["image"],
                target=root / "targets" / TASK / f"{row['tile_id']}.png",
                tile_px=int(transform["tile_px"]),
                valid_width=int(transform["valid_size"][0]),
                valid_height=int(transform["valid_size"][1]),
                origin=(
                    int(transform["origin_working_px"][0]),
                    int(transform["origin_working_px"][1]),
                ),
                working_size=(int(transform["working_size"][0]), int(transform["working_size"][1])),
            )
        )
    return BuildInfo(
        root=root,
        split_sha256=str(manifest["split_sha256"]),
        tiles_sha256=str(manifest["tiles_sha256"]),
        tiles=sorted(tiles, key=lambda tile: tile.tile_id),
    )


def _tensor(path: Path) -> torch.Tensor:
    width, height, pixels = read_gray(path)
    return torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(1, height, width)


def valid_mask(tile: TileRef) -> torch.Tensor:
    mask = torch.zeros(1, tile.tile_px, tile.tile_px, dtype=torch.bool)
    mask[:, : tile.valid_height, : tile.valid_width] = True
    return mask


class SlabTiles:
    """Тайлы части `split`. Кэш в памяти: при 1 024 px это ~2 МиБ на тайл.

    Не наследует `torch.utils.data.Dataset`: батчи собирает обучение само, детерминированно
    по seed, без процессов-загрузчиков (на Windows они порождаются заново и медленны)."""

    def __init__(
        self, tiles: list[TileRef], *, augment: bool, seed: int, cache: bool = True
    ) -> None:
        self.tiles = tiles
        self.augment = augment
        self.generator = torch.Generator().manual_seed(seed)
        self._cache: dict[int, tuple[torch.Tensor, torch.Tensor]] = {}
        self.cache = cache

    def __len__(self) -> int:
        return len(self.tiles)

    def raw(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        cached = self._cache.get(index)
        if cached is not None:
            return cached
        tile = self.tiles[index]
        pair = (_tensor(tile.image), _tensor(tile.target))
        if self.cache:
            self._cache[index] = pair
        return pair

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        image, target = self.raw(index)
        valid = valid_mask(self.tiles[index])
        x = image.float() / 255.0
        y = (target > 127).float()
        if self.augment:
            # Отражения и повороты на 90° не меняют топологию: отверстие остаётся отверстием.
            k = int(torch.randint(0, 4, (1,), generator=self.generator))
            flip = bool(torch.randint(0, 2, (1,), generator=self.generator))
            x, y, valid = (torch.rot90(t, k, dims=(1, 2)) for t in (x, y, valid))
            if flip:
                x, y, valid = (torch.flip(t, dims=(2,)) for t in (x, y, valid))
        return x, y, valid


def positive_fraction(dataset: SlabTiles) -> float:
    positive = 0
    total = 0
    for index, tile in enumerate(dataset.tiles):
        _, target = dataset.raw(index)
        region = target[:, : tile.valid_height, : tile.valid_width]
        positive += int((region > 127).sum())
        total += region.numel()
    return positive / total if total else 0.0
