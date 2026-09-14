"""Карточка частного датасета: метаданные без изображений и без имён листов.

Карточка описывает датасет так, чтобы его можно было обсуждать, не показывая чертежей: ключ
проекта вместо названия, формат и версии, счётчики, причины отказов, откаты кодировки, отпечатки,
результат проверки совмещения и известные ограничения. Имена листов и путь к исходникам в неё
не попадают; метки позиций — да, это рабочие названия строк обмера.
"""

from __future__ import annotations

import json
from pathlib import Path

from planswift_gt.manifest import ANNOTATIONS, MANIFEST, findings

JsonObject = dict[str, object]

KNOWN_LIMITATIONS = (
    "Один проект-источник на домен: оценка на нём — within-project grouped holdout, не обобщение.",
    "Геометрия не ремонтируется: повторы вершин и самопересечения остаются как в PlanSwift.",
    "ScaleX/ScaleY — свидетельство, не калибровка: физические величины по датасету не считаются.",
    "Семантика меток — рабочие названия позиций PlanSwift, не онтология элементов.",
    "Отказанные секции (заглушки, 1–2 точки, пустые) не входят в датасет — они в rejections.",
)


def _mapping(value: object) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _table(rows: list[tuple[str, object]], header: tuple[str, str]) -> list[str]:
    lines = [f"| {header[0]} | {header[1]} |", "| --- | ---: |"]
    lines += [f"| {key} | {value} |" for key, value in rows]
    return lines


def build(dataset: Path, *, qa_report: Path | None = None) -> str:
    manifest = _mapping(json.loads((dataset / MANIFEST).read_text(encoding="utf-8")))
    summary = _mapping(manifest.get("summary"))
    counters = _mapping(summary.get("counters"))
    tool = _mapping(manifest.get("tool"))

    labels: dict[str, int] = {}
    for line in (dataset / ANNOTATIONS).read_text(encoding="utf-8").splitlines():
        annotation = _mapping(json.loads(line).get("annotation"))
        key = f"{annotation.get('kind')} · {annotation.get('label_raw')}"
        labels[key] = labels.get(key, 0) + 1

    quality = findings(dataset)
    lines = [
        f"# Карточка датасета `{manifest.get('project_key')}`",
        "",
        f"- Формат: `{manifest.get('format')}`,"
        f" инструмент `{tool.get('name')}` {tool.get('version')}",
        f"- Источник: `{manifest.get('source')}` (частные данные, вне git)",
        f"- dataset_id: `{manifest.get('dataset_id')}`",
        f"- dataset_fingerprint: `{manifest.get('dataset_fingerprint')}`",
        f"- source_fingerprint: `{manifest.get('source_fingerprint')}`",
        "",
        "## Объём",
        "",
        *_table(
            [
                ("листов", summary.get("pages")),
                ("листов без растра", summary.get("pages_without_image")),
                ("аннотаций", summary.get("annotations")),
                *(
                    (f"аннотаций · {k}", v)
                    for k, v in _mapping(summary.get("annotations_by_kind")).items()
                ),
                *(
                    (f"объектов · {k}", v)
                    for k, v in _mapping(summary.get("objects_by_kind")).items()
                ),
            ],
            ("Показатель", "Значение"),
        ),
        "",
        "## Метки",
        "",
        *_table(
            [(key, labels[key]) for key in sorted(labels, key=lambda key: (-labels[key], key))],
            ("Вид · метка", "Аннотаций"),
        ),
        "",
        "## Отказы",
        "",
        *_table(
            list(_mapping(summary.get("rejections_by_reason")).items()) or [("нет", 0)],
            ("Причина", "Секций"),
        ),
        "",
        "## Кодировка",
        "",
        *_table(
            [(key, value) for key, value in counters.items() if key.startswith("xml_")],
            ("Счётчик", "Файлов"),
        ),
        "",
        "## Замечания качества",
        "",
        *_table(
            [
                ("групп одинаковой геометрии", quality["duplicate_geometry_groups"]),
                ("аннотаций в таких группах", quality["duplicate_geometry_annotations"]),
                (
                    "аннотаций с повтором соседней вершины",
                    quality["repeated_consecutive_vertex_annotations"],
                ),
            ],
            ("Замечание", "Число"),
        ),
    ]

    if qa_report is not None and qa_report.is_file():
        report = _mapping(json.loads(qa_report.read_text(encoding="utf-8")))
        lines += [
            "",
            "## Совмещение с растром",
            "",
            *_table(
                [
                    ("листов с геометрией", report.get("pages_with_geometry")),
                    ("листов с пиком в нулевом сдвиге", report.get("pages_aligned")),
                    ("минимальная доля попаданий в нуле", report.get("min_score_at_zero")),
                    ("максимальный фон по сдвигам (медиана)", report.get("max_median_score")),
                ],
                ("Показатель", "Значение"),
            ),
        ]

    lines += ["", "## Известные ограничения", "", *(f"- {item}" for item in KNOWN_LIMITATIONS), ""]
    return "\n".join(lines)
