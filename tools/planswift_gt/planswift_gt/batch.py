"""Пакетный импорт всех проектов PlanSwift и черновик конфига сборки v2 (Р-9).

```text
planswift_gt import-all <архивы> --work <распаковка> --out <planswift-gt-v1> --rules <правила>
```

Для каждого `.7z` / `.rar` каталога: безопасная распаковка (оглавление проверяется до распаковки),
разбор, запись `planswift-gt-v1` в `<out>/<ключ>`. Ключ проекта — транслитерация имени архива.
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
from planswift_gt.parser import ProjectRejectedError, parse_project, resolve_project_root

JsonObject = dict[str, object]
ARCHIVE_SUFFIXES = (".7z", ".rar")

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


def import_all(archives: Path, work: Path, out: Path, rules_path: Path) -> JsonObject:
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
        key = slug(archive.stem)
        if key in seen_keys:
            key = f"{key}_{len(seen_keys)}"
        seen_keys.add(key)
        entry: JsonObject = {"archive": archive.name, "project_key": key}
        try:
            unpacked = extract(archive, work / key)
            root = resolve_project_root(unpacked)
            result = parse_project(root)
            dataset_dir = out / key
            manifest = write(result, dataset_dir, dataset_id=f"{FORMAT}:{key}", project_key=key)
        except (ArchiveRejectedError, ProjectRejectedError, OSError) as error:
            entry.update({"status": "rejected", "reason": f"{type(error).__name__}: {error}"})
            projects.append(entry)
            continue
        counts = _task_counts(dataset_dir, targets)
        tasks = sorted(task for task, count in counts.items() if count > 0)
        family = family_for(key, families)
        entry.update(
            {
                "status": "imported",
                "project_name": result.project_name,
                "family": family,
                "pages": len(result.pages),
                "pages_without_image": sum(1 for page in result.pages if page.image is None),
                "page_formats": sorted({page.image.format for page in result.pages if page.image}),
                "task_annotations": counts,
                "dataset_fingerprint": manifest.get("dataset_fingerprint"),
                "in_build": bool(tasks),
            }
        )
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

    fingerprints: dict[str, list[str]] = {}
    for entry in projects:
        fingerprint = entry.get("dataset_fingerprint")
        if isinstance(fingerprint, str):
            fingerprints.setdefault(fingerprint, []).append(str(entry["project_key"]))
    config: JsonObject = {
        key: value for key, value in rules.items() if key not in ("families", "_note")
    }
    config["datasets"] = datasets
    report: JsonObject = {
        "projects": projects,
        "identical_projects": [keys for keys in fingerprints.values() if len(keys) > 1],
        "families": sorted({str(item["family"]) for item in datasets}),
    }
    (out / "build-v2.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "import-all-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
