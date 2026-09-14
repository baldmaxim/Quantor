"""Разбиение train/val/test по листам с кластерами почти одинаковых листов.

Аннотации одной страницы не расходятся по частям; типовые этажи (pHash ближе порога или один и тот
же растр) образуют кластер, и кластер целиком попадает в одну часть. Порядок кластеров задаётся
хешем от seed, а не результатами модели. Разбиение замораживается файлом с хешем: пересобрать его
поверх существующего без явного `--refreeze` нельзя.

Честное имя такого теста — within-project grouped holdout, а не проверка обобщения.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from planswift_gt.geometry2d import hamming

HOLDOUT_KIND = "within-project grouped holdout"


class SplitFrozenError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PageInfo:
    project_key: str
    page_guid: str
    image_sha256: str
    phash: int
    # Вес страницы при распределении: число аннотаций целевых задач (пустые листы — вес 0).
    weight: int

    @property
    def key(self) -> str:
        """GUID листа уникален только внутри проекта PlanSwift."""
        return f"{self.project_key}|{self.page_guid}"


def clusters(pages: list[PageInfo], threshold: int) -> list[list[PageInfo]]:
    """Объединение-поиск по близости pHash и совпадению растра внутри проекта."""
    parent = list(range(len(pages)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, left in enumerate(pages):
        for j in range(i + 1, len(pages)):
            right = pages[j]
            if left.project_key != right.project_key:
                continue
            if (
                left.image_sha256 == right.image_sha256
                or hamming(left.phash, right.phash) <= threshold
            ):
                parent[find(j)] = find(i)
    grouped: dict[int, list[PageInfo]] = {}
    for index, page in enumerate(pages):
        grouped.setdefault(find(index), []).append(page)
    return sorted(
        (sorted(group, key=lambda page: page.page_guid) for group in grouped.values()),
        key=lambda group: (group[0].project_key, group[0].page_guid),
    )


def _order_key(seed: int, group: list[PageInfo]) -> str:
    identity = "|".join(page.page_guid for page in group)
    return hashlib.sha256(f"{seed}:{identity}".encode()).hexdigest()


def assign(groups: list[list[PageInfo]], fractions: dict[str, float], seed: int) -> dict[str, str]:
    """Кластер целиком уходит в часть с наибольшим недобором веса аннотаций.

    Кластеры идут от тяжёлого к лёгкому (при равенстве — по хешу от seed): жадное распределение
    в таком порядке держит доли близко к целевым. Первая редакция заполняла пустые части первыми
    попавшимися кластерами и на Мосфильмовской отдала в val лист с третью всех аннотаций.
    Если test всё же пуст, в него переносится самый лёгкий кластер из другой части.
    """
    result: dict[str, str] = {}
    projects = sorted({group[0].project_key for group in groups})
    for project in projects:
        own = [g for g in groups if g[0].project_key == project]
        total = sum(page.weight for group in own for page in group) or 1
        filled = {"train": 0, "val": 0, "test": 0}
        weighted = sorted(
            (g for g in own if sum(p.weight for p in g) > 0),
            key=lambda g: (-sum(p.weight for p in g), _order_key(seed, g)),
        )
        empty = sorted(
            (g for g in own if sum(p.weight for p in g) == 0), key=lambda g: _order_key(seed, g)
        )
        placed: dict[str, list[list[PageInfo]]] = {"train": [], "val": [], "test": []}
        for group in weighted:
            weight = sum(page.weight for page in group)
            part = max(
                ("test", "val", "train"),
                key=lambda name: fractions[name] * total - filled[name],
            )
            filled[part] += weight
            placed[part].append(group)
        if not placed["test"] and len(weighted) > 1:
            donor = max(("train", "val"), key=lambda name: len(placed[name]))
            lightest = min(placed[donor], key=lambda g: sum(p.weight for p in g))
            placed[donor].remove(lightest)
            placed["test"].append(lightest)
        for part, members in placed.items():
            for group in members:
                for page in group:
                    result[page.key] = part
        # Листы без целевой разметки — негативы; распределяются по кругу, чтобы были во всех частях.
        cycle = ("train", "val", "train", "test", "train")
        for index, group in enumerate(empty):
            for page in group:
                result[page.key] = cycle[index % len(cycle)]
    return result


def freeze(
    path: Path,
    *,
    config_fingerprint: str,
    seed: int,
    groups: list[list[PageInfo]],
    assignment: dict[str, str],
    refreeze: bool,
) -> dict[str, object]:
    pages = [
        {
            "project_key": page.project_key,
            "page_guid": page.page_guid,
            "image_sha256": page.image_sha256,
            "phash": f"{page.phash:016x}",
            "cluster": index,
            "weight": page.weight,
            "split": assignment[page.key],
        }
        for index, group in enumerate(groups)
        for page in group
    ]
    body: dict[str, object] = {
        "holdout": HOLDOUT_KIND,
        "seed": seed,
        "split_config_fingerprint": config_fingerprint,
        "pages": sorted(pages, key=lambda page: (str(page["project_key"]), str(page["page_guid"]))),
    }
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    if path.exists() and not refreeze:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        existing: dict[str, object] = loaded if isinstance(loaded, dict) else {}
        if existing.get("sha256") != digest:
            raise SplitFrozenError(
                f"{path}: разбиение уже заморожено ({str(existing.get('sha256', ''))[:12]})"
                " и отличается от вычисленного; test не пересобирается по результатам —"
                " нужен явный --refreeze"
            )
        return existing
    frozen = {**body, "sha256": digest}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(frozen, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return frozen
