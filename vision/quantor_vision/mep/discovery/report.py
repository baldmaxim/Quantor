"""Private detailed report and an explicitly whitelisted, publishable aggregate summary."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .archives import Archive
from .common import FIELDS, Document, Page
from .pairing import Pair, Project


def summarize(
    archives: list[Archive],
    documents: list[Document],
    pages: list[Page],
    projects: list[Project],
    pairs: list[Pair],
) -> dict[str, object]:
    return {
        "archives_total": len(archives),
        "archives_status": dict(Counter(a.status for a in archives)),
        "archives_hold_reasons": dict(Counter(r for a in archives for r in a.reasons)),
        "unique_files": len(documents),
        "file_occurrences": sum(len(d.original_paths) for d in documents),
        "files_by_type": dict(Counter(d.extension for d in documents)),
        "file_occurrences_by_type": dict(
            Counter(Path(source).suffix.lower() for d in documents for source in d.original_paths)
        ),
        "pdf_pages": len(pages),
        "pdf_content_kind": dict(Counter(p.content_kind for p in pages)),
        "pdf_no_text": sum(p.text_characters == 0 for p in pages),
        "scans_without_text": sum(
            p.content_kind == "raster_scan" and p.text_characters == 0 for p in pages
        ),
        "pdf_pages_with_issues": sum(bool(p.issues) for p in pages),
        "pdf_page_issues": dict(Counter(issue for p in pages for issue in set(p.issues))),
        "file_revision_status": dict(Counter(d.revision_status for d in documents)),
        "file_occurrence_revision_status": dict(
            Counter(str(v["status"]) for d in documents for v in d.versions)
        ),
        "version_sets": len({str(v["set_id"]) for d in documents for v in d.versions}),
        "page_revision_status": dict(Counter(p.revision_status for p in pages)),
        "fire_documents": sum(d.classification["fire_system"].value == "yes" for d in documents),
        "pdf_files_with_errors": sum(d.extension == ".pdf" and bool(d.issues) for d in documents),
        "dwg_versions": dict(
            Counter(d.header_version or "unknown" for d in documents if d.extension == ".dwg")
        ),
        "dwg_with_same_path_pdf": sum(
            bool(d.paired_pdf_ids) for d in documents if d.extension == ".dwg"
        ),
        "projects": len(projects),
        "project_group_basis": dict(Counter(p.basis for p in projects)),
        "pages_without_project": sum(p.project_id is None for p in pages),
        "albums_stage_discipline": dict(
            Counter(
                d.classification["stage"].value + "/" + d.classification["discipline"].value
                for d in documents
                if d.extension == ".pdf"
            )
        ),
        "document_unknown_fraction": {
            name: round(
                sum(d.classification[name].value == "unknown" for d in documents)
                / max(len(documents), 1),
                6,
            )
            for name in FIELDS
        },
        "page_unknown_fraction": {
            name: round(
                sum(p.classification[name].value == "unknown" for p in pages) / max(len(pages), 1),
                6,
            )
            for name in FIELDS
        },
        "vk_pairs": dict(Counter(p.pair_status for p in pairs)),
        "confirmed_floor_system_pairs": sum(p.pair_status == "AUTO_OK" for p in pairs),
        "paired_project_sets": len({p.project_id for p in pairs if p.pair_status == "AUTO_OK"}),
        "boq_or_spec_candidates": sum(d.boq_or_spec_candidate for d in documents),
        "poc_targets": {
            "projects": [20, 30],
            "paired_sets": [40, 60],
            "floor_system_pairs": [150, 300],
        },
    }


def aggregate_report(summary: dict[str, object]) -> str:
    return (
        "# MEP D0: агрегаты инвентаризации\n\n"
        "Только опись, заголовки CAD и текстовый слой PDF. OCR, рендер, модели, "
        "разметка, split и alignment не выполнялись.\n\n"
        "```json\n" + json.dumps(summary, ensure_ascii=False, indent=2) + "\n```\n\n"
        "## Ограничения и вопросы владельцу\n\n"
        "- Project ID подтверждается шифром или явно подписанным именем объекта; "
        "общая папка не доказывает принадлежность к проекту. Число групп может отличаться "
        "от числа строительных объектов.\n"
        "- Альбомом в агрегатах считается уникальный PDF. Совпадение имени DWG/PDF "
        "в одной исходной папке — кандидат, не подтверждение одинакового содержания.\n"
        "- AUTO_OK требует также совпадения корпуса и секции; неизвестные значения дают REVIEW. "
        "Связь П→РД по различным корпусам 1:N получает REVIEW; неоднозначность внутри "
        "корпуса — HOLD.\n"
        "- Цели PoC: 20–30 проектов, 40–60 парных комплектов, 150–300 пар этаж–система. "
        "Подтверждённые пары считаются нижней оценкой; REVIEW и HOLD в неё не входят.\n"
        "- Формат страницы и доля изображения получены из PDF-операторов, не из визуальной оценки. "
        "Пользовательские clip paths отмечаются как верхняя оценка. Штамп — кандидат в нижнем "
        "правом углу с характерными подписями; читаемость человеком не проверялась.\n"
        "- Имена ZIP без флага UTF-8 требуют выбранной кодировки; исходные байты сохранены. "
        "7-Zip возвращает Unicode, исходные байты имён недоступны и отмечены null.\n"
        "- Для XLS имена листов недоступны без дополнительного парсера; "
        "содержимое таблиц не читалось.\n"
        "- Выбрать лист, систему и этаж из частного pilot_candidates.json для PROMPT 02. "
        "При нехватке кандидатов дополнить комплект, "
        "не подменять неизвестные поля догадками.\n"
        "- Если PDF недостаточно, решить отдельно вопрос конвертера DWG "
        "и ezdxf через лицензионный гейт.\n"
        "- Штампы сканов без текстового слоя остаются недоступны: "
        "нужен отдельный дальнейший шаг.\n"
        "- Нужны ли кандидаты ВОР сейчас или только к PROMPT 10?\n\nSTOP после D0.\n"
    )


def private_report(
    summary: dict[str, object],
    archives: list[Archive],
    documents: list[Document],
    pilots: list[dict[str, object]],
) -> str:
    lines = [aggregate_report(summary), "\n## Архивы\n"]
    for archive in archives:
        lines.append(f"- {archive.source}: {archive.status}; {', '.join(archive.reasons) or 'OK'}")
    by_id = {document.file_id: document for document in documents}
    lines.append("\n## Кандидаты PROMPT 02\n")
    if not pilots:
        lines.append(
            "Нет подтверждённых правилами планов П/ВК. Требуется уточнить метаданные или комплект."
        )
    for pilot in pilots:
        document = by_id[str(pilot["file_id"])]
        lines.append(f"\n- {document.original_paths[0]}, страница {pilot['page_number']}")
        lines.append("  " + json.dumps(pilot, ensure_ascii=False))
    lines.append("\n## Файлы с ограничениями чтения\n")
    for document in documents:
        if document.issues:
            lines.append(f"- {document.original_paths[0]}: {', '.join(document.issues)}")
    return "\n".join(lines) + "\n"
