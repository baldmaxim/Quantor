"""Цели SFT из растровых целей сборки промта 08 — только для train-меток.

Объект плиты — связная область маски `targets/slab` (с отверстиями) на сетке с шагом `stride`:
рамка по её клеткам, положительные точки — самые глубокие клетки области, отрицательные — клетки
внутри рамки, дальше всего отстоящие от плиты (отверстия, проёмы между плитами, фон).
Соприкасающиеся плиты сливаются в один объект: SAM в промте 14 тоже получает одну связную область.

Кладка — грубая область интереса: клетки, где цель осевой `targets/masonry` не ноль; направляющие
точки — разнесённые клетки на линиях. Километры осевых токенами не генерируются.

Всё — стандартная библиотека: тайл 1 024 px при шаге 4 — сетка 256×256.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from quantor_vision.qwen.schema import COORDINATE_MAX, Box, MasonryRoi, Point, SlabObject

INFINITY = 1 << 30


@dataclass(frozen=True, slots=True)
class TargetConfig:
    stride: int = 4
    # Области меньше этого числа пикселей тайла — обрывки плит на краю тайла, не объект.
    min_area_px: int = 1024
    positive_points: int = 2
    negative_points: int = 2
    # Отрицательная точка не ближе этого числа клеток к плите: иначе она на контуре и спорна.
    min_negative_depth: int = 2
    guide_points: int = 4
    masonry_threshold: int = 128


@dataclass(frozen=True, slots=True)
class TileGeometry:
    tile_px: int
    valid_width: int
    valid_height: int


@dataclass(frozen=True, slots=True)
class SlabTarget:
    objects: list[SlabObject]
    # Области, найденные в маске, но отброшенные как обрывки (для отчёта, не для молчаливой потери).
    dropped_small: int


Grid = list[list[bool]]


def _grid_size(tile: TileGeometry, stride: int) -> tuple[int, int]:
    return -(-tile.valid_width // stride), -(-tile.valid_height // stride)


def _sample_grid(pixels: bytes, tile: TileGeometry, stride: int) -> Grid:
    """Клетка — плита, если пиксель в её центре (в пределах допустимой области) — плита."""
    columns, rows = _grid_size(tile, stride)
    grid: Grid = []
    for row in range(rows):
        y = min(row * stride + stride // 2, tile.valid_height - 1)
        grid.append(
            [
                pixels[y * tile.tile_px + min(col * stride + stride // 2, tile.valid_width - 1)]
                > 127
                for col in range(columns)
            ]
        )
    return grid


def _max_grid(pixels: bytes, tile: TileGeometry, stride: int, threshold: int) -> Grid:
    """Клетка — линия, если хоть один пиксель клетки не ниже порога: тонкая осевая не теряется."""
    columns, rows = _grid_size(tile, stride)
    grid: Grid = []
    for row in range(rows):
        y_end = min((row + 1) * stride, tile.valid_height)
        line: list[bool] = []
        for col in range(columns):
            x0, x1 = col * stride, min((col + 1) * stride, tile.valid_width)
            line.append(
                any(
                    max(pixels[y * tile.tile_px + x0 : y * tile.tile_px + x1]) >= threshold
                    for y in range(row * stride, y_end)
                )
            )
        grid.append(line)
    return grid


def _components(grid: Grid) -> list[list[Point]]:
    rows, columns = len(grid), len(grid[0]) if grid else 0
    seen = [[False] * columns for _ in range(rows)]
    found: list[list[Point]] = []
    for start_y in range(rows):
        for start_x in range(columns):
            if not grid[start_y][start_x] or seen[start_y][start_x]:
                continue
            seen[start_y][start_x] = True
            queue = deque([(start_x, start_y)])
            cells: list[Point] = []
            while queue:
                x, y = queue.popleft()
                cells.append((x, y))
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= ny < rows and 0 <= nx < columns and grid[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        queue.append((nx, ny))
            found.append(cells)
    return found


def _depth(region: Grid) -> list[list[int]]:
    """Шахматное расстояние до ближайшей клетки вне области; край сетки границей не считается —
    плита продолжается за краем тайла."""
    rows, columns = len(region), len(region[0]) if region else 0
    depth = [[INFINITY if region[y][x] else 0 for x in range(columns)] for y in range(rows)]
    neighbours_forward = ((-1, -1), (0, -1), (1, -1), (-1, 0))
    neighbours_backward = ((1, 1), (0, 1), (-1, 1), (1, 0))
    for y in range(rows):
        for x in range(columns):
            if depth[y][x]:
                for dx, dy in neighbours_forward:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < columns and 0 <= ny < rows:
                        depth[y][x] = min(depth[y][x], depth[ny][nx] + 1)
    for y in reversed(range(rows)):
        for x in reversed(range(columns)):
            if depth[y][x]:
                for dx, dy in neighbours_backward:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < columns and 0 <= ny < rows:
                        depth[y][x] = min(depth[y][x], depth[ny][nx] + 1)
    return depth


def _spread(candidates: list[tuple[int, Point]], count: int) -> list[Point]:
    """Первая точка — самая глубокая; следующие — дальше всего от уже выбранных."""
    if not candidates or count <= 0:
        return []
    ordered = sorted(candidates, key=lambda item: (-item[0], item[1][1], item[1][0]))
    chosen = [ordered[0][1]]
    while len(chosen) < count:
        best: tuple[int, int, Point] | None = None
        for depth, cell in ordered:
            distance = min(max(abs(cell[0] - c[0]), abs(cell[1] - c[1])) for c in chosen)
            if distance == 0:
                continue
            key = (distance, depth, cell)
            if best is None or key[:2] > best[:2]:
                best = key
        if best is None or best[0] < 2:
            break
        chosen.append(best[2])
    return chosen


def _to_model(cell: Point, stride: int, tile: TileGeometry) -> Point:
    def scale(value: float, limit: int) -> int:
        clamped = min(max(value, 0.0), float(limit))
        return round(clamped / tile.tile_px * COORDINATE_MAX)

    return (
        scale((cell[0] + 0.5) * stride, tile.valid_width),
        scale((cell[1] + 0.5) * stride, tile.valid_height),
    )


def _box(cells: list[Point], stride: int, tile: TileGeometry) -> Box:
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]

    def scale(value: int, limit: int) -> int:
        return round(min(value, limit) / tile.tile_px * COORDINATE_MAX)

    x0 = scale(min(xs) * stride, tile.valid_width)
    y0 = scale(min(ys) * stride, tile.valid_height)
    x1 = max(x0 + 1, scale((max(xs) + 1) * stride, tile.valid_width))
    y1 = max(y0 + 1, scale((max(ys) + 1) * stride, tile.valid_height))
    return x0, y0, min(x1, COORDINATE_MAX), min(y1, COORDINATE_MAX)


def slab_target(pixels: bytes, tile: TileGeometry, config: TargetConfig) -> SlabTarget:
    stride = config.stride
    grid = _sample_grid(pixels, tile, stride)
    rows, columns = len(grid), len(grid[0]) if grid else 0
    min_cells = max(1, -(-config.min_area_px // (stride * stride)))
    components = _components(grid)
    kept = [cells for cells in components if len(cells) >= min_cells]
    not_slab = [[not grid[y][x] for x in range(columns)] for y in range(rows)]
    background_depth = _depth(not_slab)

    objects: list[SlabObject] = []
    for cells in kept:
        member = set(cells)
        x_min, x_max = min(x for x, _ in cells), max(x for x, _ in cells)
        y_min, y_max = min(y for _, y in cells), max(y for _, y in cells)
        # Глубина считается в рамке области с полем в клетку: любая клетка дальше поля не ближе
        # клетки поля в том же направлении, а сетка 256×256 на каждую область — лишние секунды.
        left, top = max(0, x_min - 1), max(0, y_min - 1)
        right, bottom = min(columns - 1, x_max + 1), min(rows - 1, y_max + 1)
        region = [
            [(x, y) in member for x in range(left, right + 1)] for y in range(top, bottom + 1)
        ]
        depth = _depth(region)
        positive = _spread(
            [(depth[y - top][x - left], (x, y)) for x, y in cells], config.positive_points
        )
        negative_candidates = [
            (background_depth[y][x], (x, y))
            for y in range(y_min, y_max + 1)
            for x in range(x_min, x_max + 1)
            if not grid[y][x] and background_depth[y][x] >= config.min_negative_depth
        ]
        negative = _spread(negative_candidates, config.negative_points)
        objects.append(
            SlabObject(
                bbox=_box(cells, stride, tile),
                positive_points=tuple(_to_model(cell, stride, tile) for cell in positive),
                negative_points=tuple(_to_model(cell, stride, tile) for cell in negative),
            )
        )
    objects.sort(key=lambda item: (item.bbox[1], item.bbox[0], item.bbox[3], item.bbox[2]))
    return SlabTarget(objects=objects, dropped_small=len(components) - len(kept))


def masonry_target(pixels: bytes, tile: TileGeometry, config: TargetConfig) -> MasonryRoi:
    stride = config.stride
    grid = _max_grid(pixels, tile, stride, config.masonry_threshold)
    cells = [(x, y) for y, line in enumerate(grid) for x, value in enumerate(line) if value]
    if not cells:
        return MasonryRoi(contains_masonry=False, roi=None, guide_points=())
    roi = _box(cells, stride, tile)
    guides = _spread([(0, cell) for cell in cells], config.guide_points)
    points = sorted(_to_model(cell, stride, tile) for cell in guides)
    inside = tuple((min(max(x, roi[0]), roi[2]), min(max(y, roi[1]), roi[3])) for x, y in points)
    return MasonryRoi(contains_masonry=True, roi=roi, guide_points=inside)
