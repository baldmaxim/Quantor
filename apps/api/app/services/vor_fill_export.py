"""Выгрузка заполненного ВОР (ADR-0055, п. 7): копия книги Заказчика с колонками Quantor.

Оригинал не меняется: книга читается из хранилища, изменения идут в копию. Справа от последней
колонки листа добавляются «Кол-во Quantor», «Разница», «Источник Quantor»; в конец листа - блок
«Нет в ВОР Заказчика (дополнение Quantor)» с объектами без связи. Исходные ячейки не трогаются.
Цен нет. Формулы и стили, которые openpyxl не сохраняет (диаграммы, изображения), в копии теряются.
"""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO
from typing import Final

from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from app.contracts.cad_vor import CadVorSheetColumnsRead
from app.contracts.vor_fill import VorFillItemRead, VorObjectRead, VorQuantityUnit

HEADER_QUANTITY: Final = "Кол-во Quantor"
HEADER_DIFFERENCE: Final = "Разница"
HEADER_SOURCE: Final = "Источник Quantor"
EXTRA_TITLE: Final = "Нет в ВОР Заказчика (дополнение Quantor)"
UNIT_LABELS: Final[dict[VorQuantityUnit, str]] = {"m3": "м3", "m2": "м2", "m": "м", "pcs": "шт"}
_UNIT_ORDER: Final[tuple[VorQuantityUnit, ...]] = ("m3", "m2", "m", "pcs")
_STATUS_NOTES: Final = {
    "no_quantor": "Quantor: количества нет",
    "unit_mismatch": "Единицы не совпадают",
}
_MAX_SOURCES: Final = 5


def _sources_text(labels: Sequence[str]) -> str:
    shown = list(labels[:_MAX_SOURCES])
    rest = len(labels) - len(shown)
    return "; ".join(shown) + (f"; ещё {rest}" if rest > 0 else "")


def _primary(obj: VorObjectRead) -> tuple[VorQuantityUnit, float] | None:
    for unit in _UNIT_ORDER:
        for quantity in obj.quantities:
            if quantity.unit == unit:
                return unit, quantity.value
    return None


def _last_column(sheet: Worksheet, header_row: int) -> int:
    """Последняя занятая колонка шапки (не меньше последней колонки листа с данными)."""
    last = 0
    for cell in sheet[header_row]:
        if cell.value is not None:
            last = max(last, cell.column)
    return max(last, sheet.max_column)


def fill_workbook(
    source: bytes,
    sheets: Sequence[CadVorSheetColumnsRead],
    rows: Sequence[VorFillItemRead],
    unlinked: Sequence[VorObjectRead],
) -> bytes:
    """Копия книги с колонками Quantor и блоком «Нет в ВОР»; `source` не изменяется."""
    book = load_workbook(BytesIO(source))
    bold = Font(bold=True)
    layout = {entry.sheet: entry for entry in sheets}
    by_sheet: dict[str, list[VorFillItemRead]] = {}
    for row in rows:
        by_sheet.setdefault(row.item.sheet, []).append(row)
    first_filled: str | None = None
    columns_of: dict[str, int] = {}
    for name, items in by_sheet.items():
        entry = layout.get(name)
        if name not in book.sheetnames or entry is None:
            continue
        sheet = book[name]
        first = _last_column(sheet, entry.header_row) + 1
        columns_of[name] = first
        for offset, title in enumerate((HEADER_QUANTITY, HEADER_DIFFERENCE, HEADER_SOURCE)):
            cell = sheet.cell(row=entry.header_row, column=first + offset, value=title)
            cell.font = bold
        for item in items:
            row_no = item.item.row_no
            if item.quantor_quantity is not None:
                sheet.cell(row=row_no, column=first, value=item.quantor_quantity)
            if item.difference is not None:
                sheet.cell(row=row_no, column=first + 1, value=item.difference)
            note = _STATUS_NOTES.get(item.status)
            text = _sources_text(item.sources) if item.sources else (note or "")
            if item.sources and note is not None:
                text = f"{note}. {text}"
            if text:
                sheet.cell(row=row_no, column=first + 2, value=text)
        first_filled = first_filled or name
    if unlinked:
        target = first_filled or (sheets[0].sheet if sheets else None)
        if target is not None and target in book.sheetnames and target in layout:
            _write_unlinked(book[target], layout[target], columns_of.get(target), unlinked, bold)
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def _write_unlinked(
    sheet: Worksheet,
    entry: CadVorSheetColumnsRead,
    first_extra: int | None,
    unlinked: Sequence[VorObjectRead],
    bold: Font,
) -> None:
    name_col = entry.columns.get("name", 2)
    unit_col = entry.columns.get("unit", name_col + 1)
    if first_extra is None:
        first_extra = _last_column(sheet, entry.header_row) + 1
        for offset, title in enumerate((HEADER_QUANTITY, HEADER_DIFFERENCE, HEADER_SOURCE)):
            sheet.cell(row=entry.header_row, column=first_extra + offset, value=title).font = bold
    row = sheet.max_row + 2
    sheet.cell(row=row, column=name_col, value=EXTRA_TITLE).font = bold
    for obj in unlinked:
        primary = _primary(obj)
        if primary is None:
            continue
        row += 1
        unit, value = primary
        sheet.cell(row=row, column=name_col, value=obj.title)
        sheet.cell(row=row, column=unit_col, value=UNIT_LABELS[unit])
        sheet.cell(row=row, column=first_extra, value=value)
        text = _sources_text([source.label for source in obj.sources])
        if obj.incomplete:
            text = f"неполно (часть величин не определена). {text}"
        sheet.cell(row=row, column=first_extra + 2, value=text)
