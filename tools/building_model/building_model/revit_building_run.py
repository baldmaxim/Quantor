"""Ввод-вывод команды `revit-building`: состав листов, чтение моделей и актов, сборка пакета здания.

Чистая сборка — в `revit_building.py`. Здесь только выбор страниц и чтение файлов; тексты ошибок
не содержат путей. Модуль не требует ни plangeom, ни Pillow.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from building_model.approval import ApprovalOut, load_approval, sha256_of_file
from building_model.canonical import BuildingModel
from building_model.reader import Document, Excluded, load_document, read_sheet
from building_model.revit import RevitRefusalError
from building_model.revit_building import SheetInput, build_building_package
from building_model.revit_format import RevitBuildingPackage, SkippedPage


def select_pages(
    doc: Document, building: int, added: Sequence[int], excluded: Sequence[int]
) -> list[int]:
    """Страницы группы здания, плюс добавленные, минус исключённые."""
    if not 0 <= building < len(doc.building_pages):
        raise ValueError(
            f"нет группы зданий {building}: в комплекте групп {len(doc.building_pages)}"
        )
    chosen = (set(doc.building_pages[building]) | set(added)) - set(excluded)
    return sorted(chosen)


def run_building(
    input_path: Path,
    models_dir: Path,
    building: int,
    added: Sequence[int],
    excluded: Sequence[int],
    approvals_dir: Path | None,
) -> RevitBuildingPackage:
    """Читает комплект, модели и акты, собирает пакет здания. `approvals_dir=None` — тестовый."""
    doc = load_document(input_path)
    skipped: list[SkippedPage] = []
    sheets: list[SheetInput] = []
    missing: list[int] = []
    for page in select_pages(doc, building, added, excluded):
        sheet = read_sheet(doc, page)
        if isinstance(sheet, Excluded):
            skipped.append(SkippedPage(page=page, reason=sheet.reason))
            continue
        model_path = models_dir / f"model_{page}.json"
        if not model_path.is_file():
            raise ValueError(f"нет файла модели для страницы {page}")
        model = BuildingModel.model_validate_json(model_path.read_text(encoding="utf-8"))
        approval: ApprovalOut | None = None
        if approvals_dir is not None:
            approval_path = approvals_dir / f"approval_{page}.json"
            if approval_path.is_file():
                approval = load_approval(approval_path)
            else:
                missing.append(page)
        sheets.append(
            SheetInput(page, model, approval, sha256_of_file(model_path), sheet.axes or [])
        )
    if missing:
        listed = ", ".join(str(p) for p in missing)
        raise RevitRefusalError(f"нет подтверждения (approval_<N>.json) у страниц: {listed}")
    return build_building_package(
        sheets, building, added, excluded, skipped, sha256_of_file(input_path)
    )
