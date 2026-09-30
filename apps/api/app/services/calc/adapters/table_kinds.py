"""Смысл распознанной таблицы — по названию и шапке, не по имени файла (PROMPT 02).

Классификатор детерминированный и расширяемый: вид таблицы — правило над нормализованными
названием, шапкой и первыми ячейками строк. Новый вид — новое правило в `classify` и, если
нужно, свой извлекатель. Таблица, которую не удалось понять, честно остаётся UNKNOWN и ничего
не даёт.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.contracts.calc.enums import CalcTableKind
from app.services.calc.adapters.markdown_tables import MarkdownTable
from app.services.calc.adapters.normalize import normalize_text

TABLE_KINDS_VERSION: Final = "calc.table_kinds.v2"

EXTRACTED_KINDS: Final = frozenset(
    {
        CalcTableKind.APARTMENT_EXPLICATION,
        CalcTableKind.ROOM_EXPLICATION,
        CalcTableKind.APARTMENT_SUMMARY,
        CalcTableKind.WATER_SYSTEM_SUMMARY,
    }
)
"""Виды таблиц, из которых текущие адаптеры извлекают факты."""

UNEXTRACTED_FACT_TYPES: Final[MappingProxyType[CalcTableKind, tuple[str, ...]]] = MappingProxyType(
    {
        CalcTableKind.SANITARY_FIXTURES: ("building.fixtures_count",),
        CalcTableKind.WATER_CONSUMERS: (
            "system.flow_daily",
            "system.flow_hourly_max",
            "system.flow_second_max",
            "building.residents_count",
        ),
    }
)
"""Какие факты могли бы дать таблицы, извлечение из которых ещё не реализовано.

Найденная, но не разобранная таблица превращает «не найдено» в «определить сейчас нельзя»:
данные, скорее всего, в документе есть.
"""

TABLE_KIND_TITLES: Final[MappingProxyType[CalcTableKind, str]] = MappingProxyType(
    {
        CalcTableKind.APARTMENT_EXPLICATION: "экспликации квартир",
        CalcTableKind.ROOM_EXPLICATION: "экспликации помещений",
        CalcTableKind.PARKING_STORAGE: "машиноместа и кладовые",
        CalcTableKind.APARTMENT_SUMMARY: "квартирография",
        CalcTableKind.SANITARY_FIXTURES: "санитарные приборы",
        CalcTableKind.WATER_CONSUMERS: "потребители воды",
        CalcTableKind.WATER_SYSTEM_SUMMARY: "сводные расходы систем водоснабжения",
        CalcTableKind.LOADS: "нагрузки",
        CalcTableKind.AIR_EXCHANGE: "воздухообмены",
        CalcTableKind.EQUIPMENT_SPEC: "спецификации",
        CalcTableKind.UNKNOWN: "не определены",
    }
)
"""Подписи видов для текста сводки сбора — те же, что в интерфейсе (`lib/calc/format.ts`)."""


@dataclass(frozen=True, slots=True)
class TableClassification:
    kind: CalcTableKind
    basis: str
    """На чём основан вывод — для сводки сбора."""


_FIXTURE_WORDS = re.compile(r"умывальник|унитаз|мойк|ванн|душ|биде")
_RESIDENTIAL_ROOMS = re.compile(r"^(комнат|кухн|спальн|гостин)")


def _find(cells: list[str], pattern: str) -> str | None:
    compiled = re.compile(pattern)
    return next((cell for cell in cells if compiled.search(cell)), None)


def classify(table: MarkdownTable) -> TableClassification:
    context = normalize_text(" ".join(part for part in (table.title, *table.context) if part))
    header = [normalize_text(cell) for cell in table.header if cell]
    first = [normalize_text(row[0]) for row in table.rows if row and row[0]]
    names = [normalize_text(row[1]) for row in table.rows if len(row) > 1 and row[1]]

    def by_context(pattern: str) -> str | None:
        match = re.search(pattern, context)
        return match.group(0) if match else None

    if hit := by_context(r"машиномест|кладов"):
        return TableClassification(CalcTableKind.PARKING_STORAGE, f"название: «{hit}»")
    if hit := by_context(r"экспликац\w*\s+квартир"):
        return TableClassification(CalcTableKind.APARTMENT_EXPLICATION, f"название: «{hit}»")
    area = _find(header, r"площад")
    if area and any(cell.startswith("квартир") for cell in first):
        return TableClassification(
            CalcTableKind.APARTMENT_EXPLICATION, "строки «Квартира №» и столбец площади"
        )
    if hit := by_context(r"экспликац\w*"):
        return TableClassification(CalcTableKind.ROOM_EXPLICATION, f"название: «{hit}»")
    if area and _find(header, r"^№|номер") and _find(header, r"имя|наименовани|помещени"):
        # Продолжение экспликации квартир на новой странице: без названия, но с комнатами.
        if any(_RESIDENTIAL_ROOMS.match(name) for name in names):
            return TableClassification(
                CalcTableKind.APARTMENT_EXPLICATION, "шапка экспликации и жилые комнаты"
            )
        return TableClassification(CalcTableKind.ROOM_EXPLICATION, "шапка: номер, имя, площадь")
    if hit := by_context(r"квартирограф\w*"):
        return TableClassification(CalcTableKind.APARTMENT_SUMMARY, f"название: «{hit}»")
    if hit := _find(header, r"тип\w*\s+квартир|кол\w*\.?\s*квартир|количеств\w*\s+квартир"):
        return TableClassification(CalcTableKind.APARTMENT_SUMMARY, f"шапка: «{hit}»")
    fixtures = {m.group(0) for cell in (*header, *first) for m in _FIXTURE_WORDS.finditer(cell)}
    if by_context(r"санитарн\w*\s+прибор") or len(fixtures) >= 2:
        return TableClassification(CalcTableKind.SANITARY_FIXTURES, "названия приборов")
    if (
        header
        and header[0] == "наименование системы"
        and table.rows
        and len(table.rows[0]) >= 5
        and tuple(normalize_text(cell).replace("³", "3") for cell in table.rows[0][2:5])
        == ("м3/сут", "м3/ч", "л/с")
    ):
        return TableClassification(
            CalcTableKind.WATER_SYSTEM_SUMMARY, "шапка систем и единицы расходов"
        )
    if hit := _find(header, r"потребител|водопотреблен|норм\w*\s+расход|расход\w*\s+вод"):
        return TableClassification(CalcTableKind.WATER_CONSUMERS, f"шапка: «{hit}»")
    if (hit := _find(header, r"воздухообмен|кратност")) or (
        _find(header, r"обозначение систем") and (hit := _find(header, r"воздух|вентилятор"))
    ):
        return TableClassification(CalcTableKind.AIR_EXCHANGE, f"шапка: «{hit}»")
    if hit := _find(header, r"нагрузк|расход теплоты|расход холода|мощност|\bквт\b"):
        return TableClassification(CalcTableKind.LOADS, f"шапка: «{hit}»")
    if _find(header, r"^поз") and _find(header, r"наименовани") and _find(header, r"кол"):
        return TableClassification(
            CalcTableKind.EQUIPMENT_SPEC, "шапка спецификации: поз., наименование, кол."
        )
    return TableClassification(CalcTableKind.UNKNOWN, "смысл не определён")
