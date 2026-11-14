"""Каркас здания (ADR-0043, этап С2): сборка из паспортов листов, без базы данных.

Корпус → секция → уровень собираются из подтверждённых паспортов листов-планов: каждый план
даёт свой корпус, секцию и уровни (типовой план «2-17 этаж» — все уровни диапазона). Отметка
уровня берётся только из плана одного уровня; расхождение отметок источников не решается
молча — значение остаётся пустым, все значения лежат в доказательствах и показываются
проверкой. Высота уровня выводится из отметок соседних уровней при чтении, а не хранится.

Модуль чистый: не импортирует БД, calc и CAD. Ничего про конкретные объекты.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Final

from app.services.consistency.dictionaries import SheetKind

FRAME_VERSION: Final = "consistency.frame.v1"

# Сколько ссылок на паспорта хранить в доказательствах узла; остальное - счётчиком.
EVIDENCE_PASSPORTS_MAX: Final = 30
EVIDENCE_ELEVATIONS_MAX: Final = 20
# Разные отметки одного уровня, отличающиеся меньше допуска, - одна отметка.
ELEVATION_SAME_M: Final = 0.0005
# Диапазон уровней плана длиннее - ошибка разбора, а не типовой план.
LEVEL_RANGE_MAX: Final = 200


class NodeKind(StrEnum):
    BUILDING = "building"
    SECTION = "section"
    LEVEL = "level"


class NodeStatus(StrEnum):
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class NodeOrigin(StrEnum):
    PASSPORTS = "passports"  # собран из паспортов листов
    MANUAL = "manual"  # добавлен человеком


@dataclass(frozen=True, slots=True)
class PassportRow:
    """Подтверждённый паспорт листа: то, что каркасу и проверкам нужно от него."""

    id: str
    file_name: str
    page_index: int
    section_mark: str | None
    sheet_kind: str | None
    building: str | None
    section: str | None
    level_from: str | None
    level_to: str | None
    level_from_ordinal: int | None
    level_to_ordinal: int | None
    elevation_m: float | None
    title: str | None


@dataclass(frozen=True, slots=True)
class NodeKey:
    """Устойчивый ключ узла: корпус, секция и код уровня; None - «не указано»."""

    kind: NodeKind
    building: str | None
    section: str | None = None
    code: str | None = None

    @property
    def parent(self) -> NodeKey | None:
        if self.kind is NodeKind.LEVEL:
            return NodeKey(NodeKind.SECTION, self.building, self.section)
        if self.kind is NodeKind.SECTION:
            return NodeKey(NodeKind.BUILDING, self.building)
        return None


@dataclass(frozen=True, slots=True)
class ElevationSource:
    value_m: float
    passport_id: str
    file_name: str
    page_index: int


@dataclass(slots=True)
class NodeDraft:
    """Узел-кандидат каркаса из паспортов: значения и доказательства."""

    key: NodeKey
    ordinal: int | None = None
    passports: list[PassportRow] = field(default_factory=list)
    elevations: list[ElevationSource] = field(default_factory=list)

    @property
    def elevation_m(self) -> float | None:
        """Отметка, если все источники согласны; разные отметки - None (решает человек)."""
        values = distinct_elevations(self.elevations)
        return values[0] if len(values) == 1 else None

    def evidence(self) -> dict[str, object]:
        """Доказательства для базы: ссылки на паспорта и источники отметки."""
        return {
            "passport_count": len(self.passports),
            "passports": [
                {
                    "id": item.id,
                    "file_name": item.file_name,
                    "page_index": item.page_index,
                    "section_mark": item.section_mark,
                }
                for item in self.passports[:EVIDENCE_PASSPORTS_MAX]
            ],
            "elevations": [
                {
                    "value_m": item.value_m,
                    "passport_id": item.passport_id,
                    "file_name": item.file_name,
                    "page_index": item.page_index,
                }
                for item in self.elevations[:EVIDENCE_ELEVATIONS_MAX]
            ],
        }


def distinct_elevations(sources: list[ElevationSource]) -> list[float]:
    """Разные отметки источников по возрастанию; ближе допуска - одна."""
    values: list[float] = []
    for value in sorted(item.value_m for item in sources):
        if not values or value - values[-1] > ELEVATION_SAME_M:
            values.append(value)
    return values


# --------------------------------------------------------------------------- уровни


def level_code(ordinal: int) -> str:
    """Код уровня по номеру; так же его пишет разбор заголовка (`sheet_levels`)."""
    return f"{ordinal} этаж"


# Уровни без номера: место среди номерных. Цоколь - между подземными и первым этажом,
# технический этаж, чердак и кровля - над номерными. Неизвестное слово - в конце.
_NAMED_RANK: Final = {"цоколь": 5, "технический этаж": 10_001, "чердак": 10_002, "кровля": 10_003}
_UNKNOWN_RANK: Final = 20_000
# Уровни без номера, которые нормы могут относить к надземным этажам при подсчёте этажности.
ABOVE_GROUND_NAMED: Final = frozenset({"цоколь", "технический этаж"})


def level_rank(ordinal: int | None, code: str) -> int:
    """Порядок уровня снизу вверх для показа и для поиска соседей."""
    if ordinal is not None:
        return ordinal * 10
    return _NAMED_RANK.get(code.strip().lower(), _UNKNOWN_RANK)


def passport_levels(row: PassportRow) -> list[tuple[str, int | None]]:
    """Уровни, которые покрывает план: (код, номер). Диапазон номеров раскрывается, нуля нет."""
    low, high = row.level_from_ordinal, row.level_to_ordinal
    if low is not None and high is not None:
        low, high = min(low, high), max(low, high)
        if high - low > LEVEL_RANGE_MAX:
            return []
        return [(level_code(number), number) for number in range(low, high + 1) if number != 0]
    codes = [text.strip() for text in (row.level_from, row.level_to) if text and text.strip()]
    result: list[tuple[str, int | None]] = []
    for code in dict.fromkeys(codes):
        ordinal = low if code == (row.level_from or "").strip() else high
        result.append((code, ordinal))
    return result


def covers_level(row: PassportRow, *, code: str, ordinal: int | None) -> bool:
    """План покрывает уровень: номер в диапазоне плана либо совпадение кода уровня."""
    return any(
        item_code == code or (ordinal is not None and item_ordinal == ordinal)
        for item_code, item_ordinal in passport_levels(row)
    )


def scope_matches(row_value: str | None, node_value: str | None) -> bool:
    """Корпус или секция листа подходит узлу: у листа не указано - лист на все."""
    return row_value is None or row_value == node_value


# --------------------------------------------------------------------------- сборка


def build_frame(passports: list[PassportRow]) -> dict[NodeKey, NodeDraft]:
    """Узлы-кандидаты каркаса из подтверждённых паспортов листов-планов.

    Корпус и секция берутся из паспорта как есть (None - «не указан»); уровни - из плана
    любого раздела. Отметка привязывается к уровню, только если план покрывает один уровень.
    Порядок паспортов на результат не влияет.
    """
    nodes: dict[NodeKey, NodeDraft] = {}

    def node(key: NodeKey, ordinal: int | None = None) -> NodeDraft:
        found = nodes.get(key)
        if found is None:
            found = NodeDraft(key=key, ordinal=ordinal)
            nodes[key] = found
        return found

    ordered = sorted(passports, key=lambda item: (item.file_name, item.page_index, item.id))
    for row in ordered:
        if row.sheet_kind != SheetKind.FLOOR_PLAN.value:
            continue
        levels = passport_levels(row)
        if not levels:
            continue
        building = node(NodeKey(NodeKind.BUILDING, row.building))
        section = node(NodeKey(NodeKind.SECTION, row.building, row.section))
        building.passports.append(row)
        section.passports.append(row)
        single = len(levels) == 1
        for code, ordinal in levels:
            level = node(NodeKey(NodeKind.LEVEL, row.building, row.section, code), ordinal)
            level.passports.append(row)
            if single and row.elevation_m is not None:
                level.elevations.append(
                    ElevationSource(row.elevation_m, row.id, row.file_name, row.page_index)
                )
    return nodes


# --------------------------------------------------------------------------- высоты


@dataclass(frozen=True, slots=True)
class LevelPoint:
    """Уровень секции для вывода высот: номер и отметка (подтверждённая или кандидат)."""

    key: str
    ordinal: int | None
    elevation_m: float | None


def derived_heights(levels: list[LevelPoint]) -> dict[str, float]:
    """Высота уровня «пол - пол» по отметке следующего номерного уровня той же секции.

    Только для соседних номеров (−1 → 1 тоже соседи: нулевого этажа нет) и только при обеих
    отметках; неположительная разность - не высота, а ошибка отметок (её покажет проверка).
    """
    numbered = sorted(
        (item for item in levels if item.ordinal is not None and item.elevation_m is not None),
        key=lambda item: item.ordinal if item.ordinal is not None else 0,
    )
    result: dict[str, float] = {}
    for lower, upper in pairwise(numbered):
        if lower.ordinal is None or upper.ordinal is None:
            continue
        step = upper.ordinal - lower.ordinal
        if not (step == 1 or (lower.ordinal == -1 and upper.ordinal == 1)):
            continue
        if lower.elevation_m is None or upper.elevation_m is None:
            continue
        height = round(upper.elevation_m - lower.elevation_m, 3)
        if height > 0:
            result[lower.key] = height
    return result


def group_by_section(
    levels: list[LevelPoint], section_of: dict[str, str]
) -> dict[str, list[LevelPoint]]:
    """Уровни по секциям: `section_of` - ключ уровня → ключ секции."""
    groups: dict[str, list[LevelPoint]] = defaultdict(list)
    for item in levels:
        groups[section_of[item.key]].append(item)
    return dict(groups)
