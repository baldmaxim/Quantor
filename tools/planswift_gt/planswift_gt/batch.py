"""Пакетный импорт всех проектов PlanSwift и черновик конфига сборки v2 (Р-9).

```text
planswift_gt import-all <архивы> --work <распаковка> --out <planswift-gt-v1> --rules <правила>
```

Для каждого `.7z` / `.rar` каталога: безопасная распаковка (оглавление проверяется до распаковки),
разбор, запись `planswift-gt-v1` в `<out>/<ключ>`. Ключ проекта — транслитерация имени архива.
Архив с несколькими проектами PlanSwift (корпуса одного комплекса) даёт проект на каждый — с ключом
`<архив>__<проект>` и общим семейством архива. Уже импортированный проект при повторном запуске
берётся с диска (`--force` — распаковать и разобрать заново).
По правилам (шаблоны меток целей и семейства по маскам ключей) считаются аннотации задач и пишется
`build-v2.json`: проект входит в задачу, если у него есть её аннотации; проекты без плит и стен
(двери, люки) перечисляются в отчёте и в сборку не входят.

Правила и отчёт содержат только ключи проектов, метки и числа — не чертежи и не координаты.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

from planswift_gt import FORMAT
from planswift_gt.archive import ArchiveRejectedError, extract
from planswift_gt.buildconfig import TargetConfig
from planswift_gt.manifest import write
from planswift_gt.parser import (
    DATA_FILE,
    ProjectRejectedError,
    parse_project,
    resolve_project_root,
)

JsonObject = dict[str, object]
ARCHIVE_SUFFIXES = (".7z", ".rar")
STATE_FILE = "import-state.json"

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh",
    "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip


def slug(name: str) -> str:
    """«ЖК Селигер Сити4 - К1» → `zhk_seliger_siti4_k1`: ASCII-ключ без пробелов."""
    text = "".join(_TRANSLIT.get(char, char) for char in name.lower())
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "project"


def family_for(key: str, families: dict[str, list[str]]) -> str:
    for family, masks in sorted(families.items()):
        if any(fnmatch.fnmatchcase(key, mask) for mask in masks):
            return family
    return key


def _targets(rules: JsonObject) -> dict[str, TargetConfig]:
    raw = rules.get("targets")
    if not isinstance(raw, dict):
        raise ValueError("в правилах нет targets")
    targets: dict[str, TargetConfig] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ValueError(f"targets.{name}: ожидается объект")
        targets[str(name)] = TargetConfig(
            kinds=tuple(str(kind) for kind in spec.get("kinds", [])),
            labels=tuple(str(label) for label in spec.get("labels", [])),
            label_patterns=tuple(str(pattern) for pattern in spec.get("label_patterns", [])),
            min_positive_fraction=float(spec.get("min_positive_fraction", 0.001)),
            radius_px=float(spec.get("radius_px", 6.0)),
        )
    return targets


def _task_counts(dataset_dir: Path, targets: dict[str, TargetConfig]) -> dict[str, int]:
    counts = dict.fromkeys(targets, 0)
    path = dataset_dir / "annotations.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        annotation = json.loads(line).get("annotation", {})
        for task, target in targets.items():
            if target.selects(annotation.get("kind"), annotation.get("label_raw")):
                counts[task] += 1
    return counts


def project_roots(unpacked: Path) -> list[tuple[str, Path]]:
    """Проекты PlanSwift в распакованном архиве: суффикс ключа и корень.

    Один проект — суффикс пустой. Несколько подкаталогов с `Data.xml` — каждый свой проект: так
    выгружаются корпуса одного комплекса.
    """
    try:
        return [("", resolve_project_root(unpacked))]
    except ProjectRejectedError:
        candidates = sorted(
            (child for child in unpacked.iterdir() if (child / DATA_FILE).is_file()),
            key=lambda child: child.name,
        )
        if len(candidates) < 2:
            raise
    roots: list[tuple[str, Path]] = []
    used: set[str] = set()
    for child in candidates:
        suffix = slug(child.name)
        while suffix in used:
            suffix = f"{suffix}_{len(used)}"
        used.add(suffix)
        roots.append((suffix, child))
    return roots


def import_project(
    key: str,
    root: Path,
    dataset_dir: Path,
    targets: dict[str, TargetConfig],
    *,
    force: bool = False,
) -> JsonObject:
    """Разбор и запись одного проекта; уже записанный берётся с диска, если не `force`."""
    manifest_path = dataset_dir / "manifest.json"
    if manifest_path.is_file() and not force:
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest: JsonObject = loaded if isinstance(loaded, dict) else {}
        reused = True
    else:
        manifest = write(
            parse_project(root), dataset_dir, dataset_id=f"{FORMAT}:{key}", project_key=key
        )
        reused = False
    (dataset_dir / STATE_FILE).write_text(
        json.dumps({"source_root": str(root)}, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    raw_summary = manifest.get("summary")
    summary: JsonObject = raw_summary if isinstance(raw_summary, dict) else {}
    formats: set[str] = set()
    images: list[str] = []
    for line in (dataset_dir / "pages.jsonl").read_text(encoding="utf-8").splitlines():
        image = json.loads(line).get("image") if line else None
        if isinstance(image, dict):
            formats.add(str(image.get("format")))
            images.append(str(image.get("sha256")))
    return {
        "status": "imported",
        "reused": reused,
        "project_name": manifest.get("project_name"),
        "pages": summary.get("pages"),
        "pages_without_image": summary.get("pages_without_image"),
        "page_formats": sorted(formats),
        "rejections_by_reason": summary.get("rejections_by_reason"),
        "task_annotations": _task_counts(dataset_dir, targets),
        "source_fingerprint": manifest.get("source_fingerprint"),
        "page_images": images,
    }


def shared_pages(projects: list[JsonObject]) -> tuple[list[list[str]], dict[str, int]]:
    """Одинаковые проекты (по отпечатку источника) и число листов, чей растр есть в другом проекте.

    `dataset_fingerprint` сюда не годится: в него входит ключ проекта, и он разный всегда.
    """
    by_source: dict[str, list[str]] = {}
    owners: dict[str, set[str]] = {}
    for entry in projects:
        key = str(entry["project_key"])
        fingerprint = entry.get("source_fingerprint")
        if isinstance(fingerprint, str):
            by_source.setdefault(fingerprint, []).append(key)
        images = entry.get("page_images")
        for sha in images if isinstance(images, list) else []:
            owners.setdefault(str(sha), set()).add(key)
    shared: dict[str, int] = {}
    for keys in owners.values():
        if len(keys) > 1:
            for key in keys:
                shared[key] = shared.get(key, 0) + 1
    identical = sorted(sorted(keys) for keys in by_source.values() if len(keys) > 1)
    return identical, dict(sorted(shared.items()))


def import_all(
    archives: Path, work: Path, out: Path, rules_path: Path, *, force: bool = False
) -> JsonObject:
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    if not isinstance(rules, dict):
        raise ValueError("правила — JSON-объект")
    targets = _targets(rules)
    families_raw = rules.get("families", {})
    families = (
        {str(name): [str(mask) for mask in masks] for name, masks in families_raw.items()}
        if isinstance(families_raw, dict)
        else {}
    )

    projects: list[JsonObject] = []
    datasets: list[JsonObject] = []
    seen_keys: set[str] = set()
    for archive in sorted(archives.iterdir(), key=lambda path: path.name):
        if not archive.is_file() or archive.suffix.lower() not in ARCHIVE_SUFFIXES:
            continue
        archive_key = slug(archive.stem)
        if archive_key in seen_keys:
            archive_key = f"{archive_key}_{len(seen_keys)}"
        seen_keys.add(archive_key)
        family = family_for(archive_key, families)
        try:
            unpacked = work / archive_key / archive.stem
            if force or not unpacked.is_dir():
                unpacked = extract(archive, work / archive_key)
            roots = project_roots(unpacked)
        except (ArchiveRejectedError, ProjectRejectedError, OSError) as error:
            projects.append(
                {
                    "archive": archive.name,
                    "project_key": archive_key,
                    "status": "rejected",
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
            continue
        for suffix, root in roots:
            key = f"{archive_key}__{suffix}" if suffix else archive_key
            dataset_dir = out / key
            entry: JsonObject = {"archive": archive.name, "project_key": key, "family": family}
            try:
                entry.update(import_project(key, root, dataset_dir, targets, force=force))
            except (ProjectRejectedError, OSError) as error:
                entry.update({"status": "rejected", "reason": f"{type(error).__name__}: {error}"})
                projects.append(entry)
                continue
            counts = entry["task_annotations"]
            tasks = sorted(
                task
                for task, count in (counts.items() if isinstance(counts, dict) else [])
                if count
            )
            entry["in_build"] = bool(tasks)
            projects.append(entry)
            if tasks:
                datasets.append(
                    {
                        "project_key": key,
                        "family": family,
                        "dataset_dir": str(dataset_dir),
                        "source_root": str(root),
                        "tasks": tasks,
                    }
                )

    identical, shared = shared_pages(projects)
    for entry in projects:
        entry.pop("page_images", None)
    config: JsonObject = {
        key: value for key, value in rules.items() if key not in ("families", "_note")
    }
    config["datasets"] = datasets
    report: JsonObject = {
        "projects": projects,
        "identical_projects": identical,
        "pages_shared_with_other_projects": shared,
        "families": sorted({str(item["family"]) for item in datasets}),
    }
    (out / "build-v2.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "import-all-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
