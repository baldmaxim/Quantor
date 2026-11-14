"""Проверки комплектности и «ПЗ ↔ каркас» (ADR-0043, С2): `consistency.checks.frame.v1`.

Входы - только подтверждённое человеком: уровни каркаса, паспорта листов и ответы к
документации. Итог проверки - `match` / `mismatch` / `not_run` с причиной: «нет данных» не
равно «совпадает». Допуски - параметры каталога с версией. Модуль чистый: не импортирует БД,
calc и CAD; результаты не хранятся, а считаются при чтении каркаса.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import Final

from app.services.consistency.building_frame import (
    ABOVE_GROUND_NAMED,
    PassportRow,
    covers_level,
    level_rank,
    scope_matches,
)
from app.services.consistency.dictionaries import (
    SECTION_MARKS,
    SYSTEM_CODES,
    SectionGroup,
    SheetKind,
    normalize_mark,
)

FRAME_CHECKS_VERSION: Final = "consistency.checks.frame.v1"

# Высота этажа по ПЗ и по отметкам каркаса считаются равными в пределах допуска.
FLOOR_HEIGHT_TOLERANCE_MM: Final = 10
# Высоты уровней группируются с этим шагом, чтобы найти типовую.
FLOOR_HEIGHT_BUCKET_MM: Final = 10
REFS_MAX: Final = 5

# Разделы, к которым относятся коды систем словаря: ИОС2 по ПП № 87 и его марки по ГОСТ 21.101.
SYSTEM_SECTION_MARKS: Final[dict[str, frozenset[str]]] = {
    "ИОС2": frozenset({"ИОС2", "ВК", "ВС", "АПТ", "АУПТ"}),
    "ИОС3": frozenset({"ИОС3", "ВК", "ВО"}),
}
_MEP_MARKS: Final = frozenset(item.mark for item in SECTION_MARKS if item.group is SectionGroup.MEP)


class CheckCode(StrEnum):
    AR_PLAN_PER_LEVEL = "ar_plan_per_level"
    SCHEME_PER_SYSTEM = "scheme_per_system"
    LEVEL_SEQUENCE = "level_sequence"
    LEVEL_ELEVATIONS = "level_elevations"
    PZ_STOREYS = "pz_storeys"
    PZ_FLOORS_TOTAL = "pz_floors_total"
    PZ_FLOOR_HEIGHT = "pz_floor_height"
    # Ведомость листов ↔ листы: каталог `consistency.checks.register.v1` (register_checks.py).
    REGISTER_SHEETS = "register_sheets"
    SHEETS_IN_REGISTER = "sheets_in_register"
    REGISTER_TITLES = "register_titles"


CHECK_TITLES: Final[dict[CheckCode, str]] = {
    CheckCode.AR_PLAN_PER_LEVEL: "План АР на каждый уровень",
    CheckCode.SCHEME_PER_SYSTEM: "Схема на каждую систему ИОС",
    CheckCode.LEVEL_SEQUENCE: "Уровни без пропусков",
    CheckCode.LEVEL_ELEVATIONS: "Отметки уровней",
    CheckCode.PZ_STOREYS: "ПЗ ↔ этажность",
    CheckCode.PZ_FLOORS_TOTAL: "ПЗ ↔ количество этажей",
    CheckCode.PZ_FLOOR_HEIGHT: "ПЗ ↔ высота этажа",
    CheckCode.REGISTER_SHEETS: "Ведомость → листы",
    CheckCode.SHEETS_IN_REGISTER: "Листы → ведомость",
    CheckCode.REGISTER_TITLES: "Наименования в ведомости и на листах",
}


class CheckStatus(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_RUN = "not_run"


class RefKind(StrEnum):
    PASSPORT = "passport"
    ANSWER = "answer"
    LEVEL = "level"
    REGISTER = "register"


@dataclass(frozen=True, slots=True)
class CheckRef:
    """Ссылка замечания на источник: паспорт листа, ответ к документации или уровень каркаса."""

    kind: RefKind
    id: str
    label: str
    file_name: str | None = None
    page_index: int | None = None


@dataclass(frozen=True, slots=True)
class CheckResult:
    code: CheckCode
    status: CheckStatus
    message: str
    building: str | None = None
    section: str | None = None
    level: str | None = None
    refs: tuple[CheckRef, ...] = ()


@dataclass(frozen=True, slots=True)
class LevelView:
    """Подтверждённый уровень каркаса (предки не отклонены) с действующими значениями."""

    id: str
    building: str | None
    section: str | None
    code: str
    ordinal: int | None
    elevation_m: float | None
    height_m: float | None  # ручная или выведенная из отметок
    elevation_values: tuple[float, ...] = ()  # разные отметки источников, если их больше одной


@dataclass(frozen=True, slots=True)
class AnswerView:
    """Подтверждённый ответ к документации с числом (документ или ручной ввод)."""

    id: str
    question_code: str
    scope_building: str | None
    scope_section: str | None
    number: int
    value_text: str
    file_name: str | None
    page_index: int | None


# --------------------------------------------------------------------------- подписи


def place(building: str | None, section: str | None = None) -> str:
    parts = [
        "корпус не указан" if building is None else f"корпус {building}",
    ]
    if section is not None:
        parts.append(f"секция {section}")
    return ", ".join(parts)


def _passport_ref(row: PassportRow) -> CheckRef:
    label = " · ".join(part for part in (row.section_mark, row.title or row.file_name) if part)
    return CheckRef(RefKind.PASSPORT, row.id, label, row.file_name, row.page_index)


def _answer_ref(answer: AnswerView) -> CheckRef:
    return CheckRef(
        RefKind.ANSWER, answer.id, answer.value_text, answer.file_name, answer.page_index
    )


def _level_ref(level: LevelView) -> CheckRef:
    return CheckRef(
        RefKind.LEVEL, level.id, f"{place(level.building, level.section)}: {level.code}"
    )


def _is(row: PassportRow, kind: SheetKind) -> bool:
    return row.sheet_kind == kind.value


def _mark(row: PassportRow) -> str | None:
    return None if row.section_mark is None else normalize_mark(row.section_mark)


def _ordered(levels: list[LevelView]) -> list[LevelView]:
    return sorted(
        levels,
        key=lambda item: (
            item.building or "",
            item.section or "",
            level_rank(item.ordinal, item.code),
            item.code,
        ),
    )


# --------------------------------------------------------------------------- комплектность


def check_ar_plan_per_level(
    levels: list[LevelView], passports: list[PassportRow]
) -> list[CheckResult]:
    """У каждого подтверждённого уровня есть подтверждённый план АР своего корпуса и секции."""
    code = CheckCode.AR_PLAN_PER_LEVEL
    if not levels:
        return [CheckResult(code, CheckStatus.NOT_RUN, "В каркасе нет подтверждённых уровней.")]
    plans = [row for row in passports if _is(row, SheetKind.FLOOR_PLAN)]
    results = []
    for level in _ordered(levels):
        covering = [
            row
            for row in plans
            if scope_matches(row.building, level.building)
            and scope_matches(row.section, level.section)
            and covers_level(row, code=level.code, ordinal=level.ordinal)
        ]
        ar = [row for row in covering if _mark(row) == "АР"]
        if ar:
            status, message = CheckStatus.MATCH, f"План АР есть: {len(ar)} лист(ов)."
            refs = tuple(_passport_ref(row) for row in ar[:REFS_MAX])
        else:
            others = sorted({row.section_mark or "раздел не указан" for row in covering})
            hint = f" Уровень есть на планах: {', '.join(others)}." if others else ""
            status, message = CheckStatus.MISMATCH, f"Нет подтверждённого плана АР.{hint}"
            refs = tuple(_passport_ref(row) for row in covering[:REFS_MAX])
        results.append(
            CheckResult(code, status, message, level.building, level.section, level.code, refs)
        )
    return results


def _system_pattern(system_code: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9A-ZА-ЯЁ]){re.escape(normalize_mark(system_code))}(?![0-9A-ZА-ЯЁ])")


_SYSTEM_PATTERNS: Final = tuple((item, _system_pattern(item.code)) for item in SYSTEM_CODES)


def _systems_in(title: str | None, mark: str) -> set[str]:
    """Коды систем словаря в заголовке листа раздела; системы чужого раздела не ищутся."""
    if not title:
        return set()
    text = normalize_mark(title)
    found = set()
    for system, pattern in _SYSTEM_PATTERNS:
        marks = SYSTEM_SECTION_MARKS.get(system.default_section, frozenset())
        if mark in marks and pattern.search(text):
            found.add(system.code)
    return found


def check_scheme_per_system(passports: list[PassportRow]) -> list[CheckResult]:
    """У раздела ИОС с планами есть схемы; у каждой системы с плана (В1, Т3, К1…) - своя схема.

    Группа - корпус и марка раздела планов. Схема без корпуса подходит любому корпусу.
    Системы ищутся в заголовках планов по словарю кодов систем.
    """
    code = CheckCode.SCHEME_PER_SYSTEM
    groups: dict[tuple[str | None, str], list[PassportRow]] = defaultdict(list)
    for row in passports:
        mark = _mark(row)
        if mark in _MEP_MARKS and _is(row, SheetKind.FLOOR_PLAN):
            groups[(row.building, mark)].append(row)
    if not groups:
        return [
            CheckResult(code, CheckStatus.NOT_RUN, "Нет подтверждённых планов инженерных разделов.")
        ]
    results = []
    for (building, mark), plans in sorted(
        groups.items(), key=lambda item: (item[0][0] or "", item[0][1])
    ):
        schemes = [
            row
            for row in passports
            if _mark(row) == mark
            and _is(row, SheetKind.SCHEME)
            and (row.building is None or building is None or row.building == building)
        ]
        where = f"{mark}, {place(building)}"
        if not schemes:
            results.append(
                CheckResult(
                    code,
                    CheckStatus.MISMATCH,
                    f"{where}: планы есть ({len(plans)}), подтверждённых схем нет.",
                    building,
                    refs=tuple(_passport_ref(row) for row in plans[:REFS_MAX]),
                )
            )
            continue
        systems = sorted(set().union(*(_systems_in(row.title, mark) for row in plans)))
        if not systems:
            results.append(
                CheckResult(
                    code,
                    CheckStatus.MATCH,
                    f"{where}: схемы есть ({len(schemes)}); "
                    "коды систем в заголовках планов не найдены.",
                    building,
                    refs=tuple(_passport_ref(row) for row in schemes[:REFS_MAX]),
                )
            )
            continue
        for system in systems:
            with_system = [row for row in schemes if system in _systems_in(row.title, mark)]
            on_plans = [row for row in plans if system in _systems_in(row.title, mark)]
            if with_system:
                results.append(
                    CheckResult(
                        code,
                        CheckStatus.MATCH,
                        f"{where}, система {system}: схема есть.",
                        building,
                        refs=tuple(_passport_ref(row) for row in with_system[:REFS_MAX]),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        code,
                        CheckStatus.MISMATCH,
                        f"{where}, система {system}: есть на планах, схемы с этой системой нет.",
                        building,
                        refs=tuple(_passport_ref(row) for row in on_plans[:REFS_MAX]),
                    )
                )
    return results


def _by_section(levels: list[LevelView]) -> dict[tuple[str | None, str | None], list[LevelView]]:
    groups: dict[tuple[str | None, str | None], list[LevelView]] = defaultdict(list)
    for level in levels:
        groups[(level.building, level.section)].append(level)
    return dict(sorted(groups.items(), key=lambda item: (item[0][0] or "", item[0][1] or "")))


def check_level_sequence(levels: list[LevelView]) -> list[CheckResult]:
    """Номерные надземные уровни секции идут с 1 до верхнего без пропусков."""
    code = CheckCode.LEVEL_SEQUENCE
    if not levels:
        return [CheckResult(code, CheckStatus.NOT_RUN, "В каркасе нет подтверждённых уровней.")]
    results = []
    for (building, section), group in _by_section(levels).items():
        numbers = {item.ordinal for item in group if item.ordinal is not None and item.ordinal >= 1}
        if not numbers:
            results.append(
                CheckResult(
                    code,
                    CheckStatus.NOT_RUN,
                    "Нет номерных надземных уровней.",
                    building,
                    section,
                )
            )
            continue
        missing = [number for number in range(1, max(numbers) + 1) if number not in numbers]
        if missing:
            listed = ", ".join(str(number) for number in missing[:20])
            more = "…" if len(missing) > 20 else ""
            results.append(
                CheckResult(
                    code,
                    CheckStatus.MISMATCH,
                    f"Нет уровней: {listed}{more} (всего {max(numbers)} по верхнему номеру).",
                    building,
                    section,
                )
            )
        else:
            results.append(
                CheckResult(
                    code,
                    CheckStatus.MATCH,
                    f"Уровни 1-{max(numbers)} без пропусков.",
                    building,
                    section,
                )
            )
    return results


def check_level_elevations(levels: list[LevelView]) -> list[CheckResult]:
    """Отметка уровня однозначна, и отметки растут снизу вверх."""
    code = CheckCode.LEVEL_ELEVATIONS
    if not levels:
        return [CheckResult(code, CheckStatus.NOT_RUN, "В каркасе нет подтверждённых уровней.")]
    results = []
    for (building, section), group in _by_section(levels).items():
        problems = 0
        for level in _ordered(group):
            if len(level.elevation_values) > 1:
                problems += 1
                values = "; ".join(f"{value:+.3f}" for value in level.elevation_values)
                results.append(
                    CheckResult(
                        code,
                        CheckStatus.MISMATCH,
                        f"Разные отметки на планах: {values}. Отметку выбирает человек.",
                        building,
                        section,
                        level.code,
                        (_level_ref(level),),
                    )
                )
        known = [item for item in _ordered(group) if item.elevation_m is not None]
        for lower, upper in pairwise(known):
            if (
                lower.elevation_m is not None
                and upper.elevation_m is not None
                and upper.elevation_m <= lower.elevation_m
            ):
                problems += 1
                results.append(
                    CheckResult(
                        code,
                        CheckStatus.MISMATCH,
                        f"Отметка {upper.code} ({upper.elevation_m:+.3f}) не выше отметки "
                        f"{lower.code} ({lower.elevation_m:+.3f}).",
                        building,
                        section,
                        upper.code,
                        (_level_ref(lower), _level_ref(upper)),
                    )
                )
        if problems:
            continue
        if not known:
            results.append(
                CheckResult(code, CheckStatus.NOT_RUN, "Отметок уровней нет.", building, section)
            )
        else:
            results.append(
                CheckResult(
                    code,
                    CheckStatus.MATCH,
                    f"Отметки {len(known)} уровней однозначны и растут снизу вверх.",
                    building,
                    section,
                )
            )
    return results


# --------------------------------------------------------------------------- ПЗ ↔ каркас


@dataclass(frozen=True, slots=True)
class _SectionCount:
    building: str | None
    section: str | None
    above: int  # верхний номер надземного уровня
    named_above: int  # цоколь и технический этаж
    underground: int  # подземные номерные уровни


def _in_scope(level: LevelView, answer: AnswerView) -> bool:
    if answer.scope_building is not None and level.building != answer.scope_building:
        return False
    return answer.scope_section is None or level.section == answer.scope_section


def _section_counts(levels: list[LevelView]) -> list[_SectionCount]:
    counts = []
    for (building, section), group in _by_section(levels).items():
        numbers = [item.ordinal for item in group if item.ordinal is not None]
        named = {item.code.strip().lower() for item in group if item.ordinal is None}
        counts.append(
            _SectionCount(
                building,
                section,
                above=max((number for number in numbers if number >= 1), default=0),
                named_above=len(named & ABOVE_GROUND_NAMED),
                underground=len({number for number in numbers if number < 0}),
            )
        )
    return counts


def _answer_scope(answer: AnswerView) -> str:
    if answer.scope_building is None and answer.scope_section is None:
        return "весь проект"
    return place(answer.scope_building, answer.scope_section)


def _check_count(
    code: CheckCode,
    question: str,
    title: str,
    levels: list[LevelView],
    answers: list[AnswerView],
    *,
    with_underground: bool,
) -> list[CheckResult]:
    """Число этажей по ответу ПЗ против каркаса области ответа.

    Каркас: верхний номер надземного уровня (+ подземные для «количества этажей»). Нормы могут
    включать в число этажей цоколь и технический этаж, поэтому совпадением считается и счёт с
    ними; в сообщении видно, какой.
    """
    mine = [item for item in answers if item.question_code == question]
    if not mine:
        return [
            CheckResult(
                code,
                CheckStatus.NOT_RUN,
                f"Нет подтверждённого ответа «{title}» в вопросах к документации.",
            )
        ]
    results = []
    for answer in mine:
        scoped = [level for level in levels if _in_scope(level, answer)]
        where = _answer_scope(answer)
        if not scoped:
            results.append(
                CheckResult(
                    code,
                    CheckStatus.NOT_RUN,
                    f"По ПЗ {answer.number} ({where}); "
                    "в каркасе нет подтверждённых уровней области.",
                    answer.scope_building,
                    answer.scope_section,
                    refs=(_answer_ref(answer),),
                )
            )
            continue
        counts = _section_counts(scoped)
        variants: set[int] = set()
        described = []
        for item in counts:
            base = item.above + (item.underground if with_underground else 0)
            variants.update({base, base + item.named_above})
            extra = f", с цоколем и техэтажом {base + item.named_above}" if item.named_above else ""
            described.append(f"{place(item.building, item.section)}: {base}{extra}")
        frame_text = "; ".join(described)
        status = CheckStatus.MATCH if answer.number in variants else CheckStatus.MISMATCH
        verdict = "совпадает" if status is CheckStatus.MATCH else "не совпадает"
        results.append(
            CheckResult(
                code,
                status,
                f"По ПЗ {answer.number} ({where}); по каркасу - {frame_text}. "
                f"{verdict.capitalize()}.",
                answer.scope_building,
                answer.scope_section,
                refs=(_answer_ref(answer),),
            )
        )
    return results


def check_pz_floor_height(levels: list[LevelView], answers: list[AnswerView]) -> list[CheckResult]:
    """Высота типового этажа по ПЗ против самой частой высоты уровней области."""
    code = CheckCode.PZ_FLOOR_HEIGHT
    mine = [item for item in answers if item.question_code == "floor_height"]
    if not mine:
        return [
            CheckResult(
                code,
                CheckStatus.NOT_RUN,
                "Нет подтверждённого ответа «Высота типового этажа» в вопросах к документации.",
            )
        ]
    results = []
    for answer in mine:
        where = _answer_scope(answer)
        heights = [
            round(level.height_m * 1000)
            for level in levels
            if _in_scope(level, answer) and level.height_m is not None
        ]
        if not heights:
            results.append(
                CheckResult(
                    code,
                    CheckStatus.NOT_RUN,
                    f"По ПЗ {answer.number} мм ({where}); у уровней области нет высот "
                    "(нужны отметки соседних уровней или высота, введённая человеком).",
                    answer.scope_building,
                    answer.scope_section,
                    refs=(_answer_ref(answer),),
                )
            )
            continue
        buckets = Counter(
            round(value / FLOOR_HEIGHT_BUCKET_MM) * FLOOR_HEIGHT_BUCKET_MM for value in heights
        )
        typical, count = max(buckets.items(), key=lambda item: (item[1], -item[0]))
        ok = abs(typical - answer.number) <= FLOOR_HEIGHT_TOLERANCE_MM
        others = sorted(value for value in buckets if value != typical)
        tail = f"; другие высоты: {', '.join(str(v) for v in others[:6])} мм" if others else ""
        results.append(
            CheckResult(
                code,
                CheckStatus.MATCH if ok else CheckStatus.MISMATCH,
                f"По ПЗ {answer.number} мм ({where}); по отметкам каркаса чаще всего {typical} мм "
                f"({count} из {len(heights)} уровней){tail}. "
                f"{'Совпадает' if ok else 'Не совпадает'} (допуск {FLOOR_HEIGHT_TOLERANCE_MM} мм).",
                answer.scope_building,
                answer.scope_section,
                refs=(_answer_ref(answer),),
            )
        )
    return results


# --------------------------------------------------------------------------- каталог


def run_frame_checks(
    levels: list[LevelView], passports: list[PassportRow], answers: list[AnswerView]
) -> list[CheckResult]:
    """Все проверки каталога v1 по подтверждённым данным; порядок результатов детерминирован."""
    return [
        *check_ar_plan_per_level(levels, passports),
        *check_level_sequence(levels),
        *check_level_elevations(levels),
        *check_scheme_per_system(passports),
        *_check_count(
            CheckCode.PZ_STOREYS, "storeys", "Этажность", levels, answers, with_underground=False
        ),
        *_check_count(
            CheckCode.PZ_FLOORS_TOTAL,
            "floors_total",
            "Количество этажей",
            levels,
            answers,
            with_underground=True,
        ),
        *check_pz_floor_height(levels, answers),
    ]
