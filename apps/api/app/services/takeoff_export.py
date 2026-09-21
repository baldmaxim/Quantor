"""Выгрузка обмера листа в CSV.

Отчёт строится из тех же результатов, что показывает экран: величины считает
`quantity_service`, здесь они только раскладываются по столбцам. Пересчёта в этом модуле
нет и быть не должно — иначе в выгрузке появилось бы второе, независимое число.

Область — лист. Выгрузка проекта целиком складывала бы измерения разных ревизий и
посчитала бы одни и те же двери дважды (ADR-0019).

Строка на измерение, а не на строку обмера: у измерений одной строки бывают разные
калибровки и разные правила, и свёрнутый итог эту разницу теряет. Итог по строке едет
рядом отдельными столбцами — так он есть, но ничего не скрывает.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal

from app.domain import GeometryType, QuantityState, QuantityUnit
from app.models import Document, DocumentRevision, Measurement, Project, Sheet, TakeoffItem
from app.services.quantity import QuantityResult, QuantityTotal

# Разделитель и запятая в дробях — соглашение русского Excel: с точкой и запятой-разделителем
# он разложит файл в один столбец. Байтовая метка нужна ему же, иначе кириллица открывается
# в кодировке системы и превращается в мусор.
DELIMITER = ";"
BOM = "﻿"

HEADERS = (
    "Проект",
    "Идентификатор проекта",
    "Документ",
    "Идентификатор документа",
    "Ревизия",
    "Идентификатор ревизии",
    "Лист",
    "Идентификатор листа",
    "Строка обмера",
    "Идентификатор строки",
    "Тип геометрии",
    "Идентификатор измерения",
    "Создано",
    "Состояние",
    "Код состояния",
    "Величина",
    "Единица",
    "Каноническая величина",
    "Каноническая единица",
    "Правило",
    "Версия правила",
    "Идентификатор калибровки",
    "Отпечаток геометрии страницы",
    "Отпечаток входа",
    "Итог по строке на листе",
    "Измерений в итоге",
    "Без масштаба",
    "Недействительных контуров",
    "Правило итога",
)

GEOMETRY_LABELS = {
    GeometryType.COUNT: "Количество",
    GeometryType.LINE: "Линия",
    GeometryType.POLYLINE: "Ломаная",
    GeometryType.POLYGON: "Площадь",
}

STATE_LABELS = {
    QuantityState.READY: "Посчитано",
    QuantityState.UNAVAILABLE_NO_SCALE: "Нет масштаба",
    QuantityState.UNAVAILABLE_NO_GEOMETRY: "Нет геометрии страницы",
    QuantityState.INVALID_GEOMETRY: "Недействительный контур",
}

UNIT_LABELS = {QuantityUnit.PCS: "шт", QuantityUnit.M: "м", QuantityUnit.M2: "м²"}


@dataclass(frozen=True, slots=True)
class ExportScope:
    """Полная цепочка владения листом — она же цепочка прослеживаемости в отчёте."""

    project: Project
    document: Document
    revision: DocumentRevision
    sheet: Sheet


def _decimal(value: Decimal | None) -> str:
    """Число без округления, с запятой в дробной части.

    Замена точки на запятую — подстановка символа, а не пересчёт: значение остаётся тем
    же, которое посчитал сервер, и проверяемо до последнего знака.
    """
    return "" if value is None else str(value).replace(".", ",")


def sheet_label(sheet: Sheet) -> str:
    return sheet.page_label or str(sheet.page_index + 1)


def revision_label(revision: DocumentRevision) -> str:
    return revision.revision_label or revision.source_filename


def build_csv(
    *,
    scope: ExportScope,
    measurements: list[Measurement],
    items: dict[str, TakeoffItem],
    results: dict[str, QuantityResult],
    totals: dict[str, QuantityTotal],
) -> str:
    """Собирает текст CSV. Чистая функция: ни сессии, ни запросов."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=DELIMITER, lineterminator="\r\n")
    writer.writerow(HEADERS)

    for measurement in measurements:
        item_id = str(measurement.takeoff_item_id)
        item = items.get(item_id)
        result = results.get(str(measurement.id))
        total = totals.get(item_id)

        writer.writerow(
            (
                scope.project.name,
                str(scope.project.id),
                scope.document.display_name,
                str(scope.document.id),
                revision_label(scope.revision),
                str(scope.revision.id),
                sheet_label(scope.sheet),
                str(scope.sheet.id),
                item.name if item else "",
                item_id,
                GEOMETRY_LABELS.get(measurement.geometry_type, measurement.geometry_type),
                str(measurement.id),
                measurement.created_at.isoformat(),
                STATE_LABELS.get(result.state, result.state) if result else "",
                result.state.value if result else "",
                _decimal(result.value) if result else "",
                UNIT_LABELS.get(result.unit, result.unit) if result else "",
                _decimal(result.canonical_value) if result else "",
                result.canonical_unit if result else "",
                result.rule_key if result else "",
                result.rule_version if result else "",
                result.scale_calibration_id or "" if result else "",
                result.page_geometry_fingerprint or "" if result else "",
                result.input_fingerprint if result else "",
                _decimal(total.value) if total else "",
                str(total.measurement_count) if total else "",
                str(total.unavailable_count) if total else "",
                str(total.invalid_count) if total else "",
                total.rule_key if total else "",
            )
        )

    return BOM + buffer.getvalue()


def filename(scope: ExportScope) -> str:
    """Имя файла, по которому потом понятно, что именно выгружено."""
    return f"Обмер — {scope.document.display_name} — лист {sheet_label(scope.sheet)}.csv"
