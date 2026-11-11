"""Пучок путей одного источника: дерево от корня; новые пути стартуют со ствола со скидкой."""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from itertools import pairwise

import numpy as np

from cad_mep.params import Params
from cad_mep.raster import BoolArr, dilate
from cad_mep.route import RouteGrid, node_path, spt


class Bundle:
    """Дерево путей от корня без тройников внутри: путь касается дерева только началом.

    Стартовать новый путь можно с любой клетки дерева по цене ALPHA × длина по дереву от корня;
    входить в клетки дерева повторно нельзя, поэтому пути делят только общий ствол (префикс).
    """

    def __init__(
        self, rg: RouteGrid, root: int, params: Params, seed: Sequence[int] | None = None
    ) -> None:
        self.rg, self.root = rg, root
        self.alpha = params.num("bundle_trunk_alpha")
        self.penalty = params.num("route_occupied_penalty_mm")
        self.along: dict[int, float] = {root: 0.0}
        self.parent: dict[int, int | None] = {root: None}
        if seed is not None and len(seed) > 1:
            if seed[0] != root:
                raise ValueError("начало ствола не совпадает с корнем пучка")
            self.add(seed)

    def chain(self, cell: int) -> list[int]:
        """Путь по дереву от корня до клетки."""
        out: list[int] = []
        cur: int | None = cell
        while cur is not None:
            out.append(cur)
            cur = self.parent[cur]
        return out[::-1]

    def add(self, path: Sequence[int]) -> None:
        """Добавить в дерево путь, начинающийся с клетки дерева."""
        for a, b in pairwise(path):
            if b not in self.along:
                self.along[b] = self.along[a] + self.rg.step
                self.parent[b] = a

    def reach(
        self,
        target: int,
        occupied: Collection[int] = (),
        block: Mapping[int, float] | None = None,
    ) -> list[int]:
        """Путь от корня до цели (ствол + новый участок); пусто, если цели не достичь.

        occupied — клетки чужих пучков (штраф route_occupied_penalty_mm), block — добавки к цене
        входа в клетку (inf закрывает её).
        """
        if target in self.along:
            return self.chain(target)
        extra: dict[int, float] = dict.fromkeys(occupied, self.penalty)
        if block:
            extra.update(block)
        for cell in self.along:
            extra[cell] = math.inf
        init = {c: self.alpha * d for c, d in self.along.items()}
        tree = spt(self.rg, list(init), [target], True, init, extra)
        path = node_path(tree, target)
        if not path or path[0] not in self.along:
            return []
        self.add(path)
        return self.chain(path[0])[:-1] + path

    def length_mm(self, cells: Sequence[int]) -> float:
        return max(len(cells) - 1, 0) * self.rg.step


def grow(
    rg: RouteGrid,
    root: int,
    targets_far_to_near: Sequence[int],
    occupied: Collection[int],
    params: Params,
    seed: Sequence[int] | None = None,
    block: Mapping[int, float] | None = None,
) -> list[list[int]]:
    """Пути от корня к целям по очереди от дальних к ближним (пусто — цель недостижима)."""
    bundle = Bundle(rg, root, params, seed)
    return [bundle.reach(t, occupied, block) for t in targets_far_to_near]


def far_to_near(rg: RouteGrid, root: int, targets: Sequence[int]) -> list[int]:
    """Цели от дальних к ближним по пути от корня; недостижимые — в конце, по номеру."""
    tree = spt(rg, [root], list(targets))
    dist = {t: tree[t] for t in targets}
    reach = sorted((t for t in targets if math.isfinite(dist[t])), key=lambda t: (-dist[t], t))
    return reach + sorted(t for t in targets if not math.isfinite(dist[t]))


def halo(rg: RouteGrid, cells: Collection[int], radius_mm: float) -> set[int]:
    """Клетки в радиусе вокруг клеток пучка: зона, куда чужие пути лучше не заходить."""
    if not cells:
        return set()
    iy_ix = (rg.xy[list(cells)] // rg.step).astype(np.int64)
    mask: BoolArr = np.zeros(rg.pas.shape, dtype=np.bool_)
    mask[iy_ix[:, 1], iy_ix[:, 0]] = True
    wide = dilate(mask, math.ceil(radius_mm / rg.step)) & rg.pas
    return {int(n) for n in rg.idx[wide]}
