"""Проверки «ведомость листов ↔ листы» (ADR-0043, С2): `consistency.checks.register.v1`.

Входы - подтверждённые человеком ведомости и паспорта листов той же ревизии PDF. Ведомость
описывает листы своего документа: сравнение идёт только внутри ревизии. Листы текстовой части
(тип «текст») не сравниваются: у них своя нумерация страниц, не номера листов графической части.
Паспорт-кандидат с нужным номером не делает строку совпавшей: итог - «не проверено», пока его не
подтвердит человек. Модуль чистый; результаты считаются при чтении и не хранятся.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Final

from app.services.consistency.dictionaries import SheetKind
from app.services.consistency.frame_checks import (
    CheckCode,
    CheckRef,
    CheckResult,
    CheckStatus,
    RefKind,
)
from app.services.consistency.sheet_register import (
    TITLE_SIMILARITY_MIN,
    RegisterEntry,
    normalize_number,
    titles_agree,
)

REGISTER_CHECKS_VERSION: Final = "consistency.checks.register.v1"

REGISTER_REFS_MAX: Final = 20
NUMBERS_LISTED_MAX: Final = 30
TITLES_LISTED_MAX: Final = 5

_CODES: Final = (
    CheckCode.REGISTER_SHEETS,
    CheckCode.SHEETS_IN_REGISTER,
    CheckCode.REGISTER_TITLES,
)


@dataclass(frozen=True, slots=True)
class RegisterView:
    """Подтверждённая ведомость: строки всех её страниц (с продолжениями)."""

    id: str
    revision_id: str
    file_name: str
    page_index: int
    entries: tuple[RegisterEntry, ...]
    duplicates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SheetView:
    """Не отклонённый паспорт листа последней ревизии."""

    id: str
    revision_id: str
    file_name: str
    page_index: int
    sheet_number: str | None
    sheet_kind: str | None
    section_mark: str | None
    title: str | None
    confirmed: bool


# --------------------------------------------------------------------------- служебное


def _natural(number: str) -> tuple[int, str]:
    head = "".join(ch for ch in number.split(".")[0] if ch.isdigit())
    return (int(head) if head else 0, number)


def _numbers(values: list[str]) -> str:
    ordered = sorted(dict.fromkeys(values), key=_natural)
    shown = ", ".join(ordered[:NUMBERS_LISTED_MAX])
    rest = len(ordered) - NUMBERS_LISTED_MAX
    return f"{shown} и ещё {rest}" if rest > 0 else shown


def _register_ref(register: RegisterView) -> CheckRef:
    return CheckRef(
        RefKind.REGISTER, register.id, "Ведомость листов", register.file_name, register.page_index
    )


def _sheet_ref(sheet: SheetView) -> CheckRef:
    number = f"Лист {sheet.sheet_number}" if sheet.sheet_number else None
    label = " · ".join(
        part for part in (sheet.section_mark, number, sheet.title or sheet.file_name) if part
    )
    return CheckRef(RefKind.PASSPORT, sheet.id, label, sheet.file_name, sheet.page_index)


def _refs(head: CheckRef, sheets: list[SheetView]) -> tuple[CheckRef, ...]:
    return (head, *(_sheet_ref(sheet) for sheet in sheets[: REGISTER_REFS_MAX - 1]))


def _drawing(sheet: SheetView) -> bool:
    return sheet.sheet_kind != SheetKind.TEXT.value


def _by_revision(sheets: list[SheetView]) -> dict[str, list[SheetView]]:
    grouped: dict[str, list[SheetView]] = defaultdict(list)
    for sheet in sheets:
        if _drawing(sheet):
            grouped[sheet.revision_id].append(sheet)
    return grouped


def _by_number(sheets: list[SheetView]) -> dict[str, list[SheetView]]:
    grouped: dict[str, list[SheetView]] = defaultdict(list)
    for sheet in sheets:
        number = None if sheet.sheet_number is None else normalize_number(sheet.sheet_number)
        if number is not None:
            grouped[number].append(sheet)
    return grouped


def _unnumbered(sheets: list[SheetView]) -> list[SheetView]:
    return [
        sheet
        for sheet in sheets
        if sheet.sheet_number is None or normalize_number(sheet.sheet_number) is None
    ]


def _sentence(parts: list[str]) -> str:
    return " ".join(part if part.endswith(".") else f"{part}." for part in parts)


# --------------------------------------------------------------------------- ведомость → листы


def check_register_sheets(register: RegisterView, sheets: list[SheetView]) -> CheckResult:
    """У каждой строки ведомости есть ровно один подтверждённый лист документа с этим номером."""
    by_number = _by_number(sheets)
    missing: list[str] = []
    repeated: list[str] = []
    unconfirmed: list[str] = []
    attention: list[SheetView] = []
    for entry in register.entries:
        found = by_number.get(entry.number, [])
        confirmed = [sheet for sheet in found if sheet.confirmed]
        if not found:
            missing.append(entry.number)
        elif len(confirmed) > 1:
            repeated.append(entry.number)
            attention.extend(confirmed)
        elif not confirmed:
            unconfirmed.append(entry.number)
            attention.extend(found)
    parts = [f"Строк в ведомости: {len(register.entries)}"]
    if missing:
        parts.append(f"Нет листа с номером: {_numbers(missing)}")
    if repeated:
        parts.append(f"Номер стоит на нескольких подтверждённых листах: {_numbers(repeated)}")
    if register.duplicates:
        parts.append(f"Номер повторяется в самой ведомости: {_numbers(list(register.duplicates))}")
    if unconfirmed:
        parts.append(f"Паспорт листа не подтверждён: {_numbers(unconfirmed)}")
    unnumbered = _unnumbered(sheets)
    if missing and unnumbered:
        parts.append(f"Страниц без номера листа в паспорте: {len(unnumbered)}")
        attention.extend(unnumbered)
    if missing or repeated or register.duplicates:
        status = CheckStatus.MISMATCH
    elif unconfirmed:
        status = CheckStatus.NOT_RUN
    else:
        status = CheckStatus.MATCH
        parts.append("Все листы ведомости есть в документе")
    return CheckResult(
        CheckCode.REGISTER_SHEETS,
        status,
        _sentence(parts),
        refs=_refs(_register_ref(register), attention),
    )


# --------------------------------------------------------------------------- листы → ведомость


def check_sheets_in_register(registers: list[RegisterView], sheets: list[SheetView]) -> CheckResult:
    """Каждый подтверждённый лист документа с номером есть в ведомости (одной из ведомостей)."""
    head = _register_ref(registers[0])
    listed = {entry.number for register in registers for entry in register.entries}
    confirmed = [sheet for sheet in sheets if sheet.confirmed]
    numbered = [
        (sheet, number)
        for sheet in confirmed
        if sheet.sheet_number is not None
        and (number := normalize_number(sheet.sheet_number)) is not None
    ]
    unnumbered = len(confirmed) - len(numbered)
    extra = [(sheet, number) for sheet, number in numbered if number not in listed]
    parts: list[str] = []
    if not numbered:
        parts.append("Нет подтверждённых листов с номером")
        status = CheckStatus.NOT_RUN
    elif extra:
        parts.append(f"Листов нет в ведомости: {_numbers([number for _, number in extra])}")
        status = CheckStatus.MISMATCH
    else:
        parts.append(f"Все подтверждённые листы есть в ведомости: {len(numbered)}")
        status = CheckStatus.MATCH
    if unnumbered:
        parts.append(f"Подтверждённых листов без номера не проверено: {unnumbered}")
    return CheckResult(
        CheckCode.SHEETS_IN_REGISTER,
        status,
        _sentence(parts),
        refs=_refs(head, [sheet for sheet, _ in extra]),
    )


# --------------------------------------------------------------------------- наименования


def _quote(text: str, limit: int = 80) -> str:
    return f"«{text if len(text) <= limit else text[: limit - 1] + '…'}»"


def check_register_titles(register: RegisterView, sheets: list[SheetView]) -> CheckResult:
    """Наименование строки ведомости совпадает с наименованием подтверждённого листа по словам."""
    by_number = _by_number(sheets)
    agreed = 0
    unknown = 0
    differ: list[tuple[RegisterEntry, SheetView]] = []
    for entry in register.entries:
        confirmed = [sheet for sheet in by_number.get(entry.number, []) if sheet.confirmed]
        if len(confirmed) != 1:
            continue
        sheet = confirmed[0]
        verdict = None if sheet.title is None else titles_agree(entry.title, sheet.title)
        if verdict is None:
            unknown += 1
        elif verdict:
            agreed += 1
        else:
            differ.append((entry, sheet))
    parts: list[str] = []
    if differ:
        shown = "; ".join(
            f"лист {entry.number}: в ведомости {_quote(entry.title)}, "
            f"на листе {_quote(sheet.title or '')}"
            for entry, sheet in differ[:TITLES_LISTED_MAX]
        )
        rest = len(differ) - TITLES_LISTED_MAX
        parts.append(f"Наименования расходятся: {shown}" + (f" и ещё {rest}" if rest > 0 else ""))
        status = CheckStatus.MISMATCH
    elif agreed:
        parts.append(f"Наименования совпадают: {agreed}")
        status = CheckStatus.MATCH
    else:
        parts.append("Нет пар «строка ведомости - подтверждённый лист» с наименованием")
        status = CheckStatus.NOT_RUN
    if differ and agreed:
        parts.append(f"Совпадают: {agreed}")
    if unknown:
        parts.append(f"Без наименования на листе: {unknown}")
    parts.append(f"Совпадение - не меньше {round(TITLE_SIMILARITY_MIN * 100)} % слов")
    return CheckResult(
        CheckCode.REGISTER_TITLES,
        status,
        _sentence(parts),
        refs=_refs(_register_ref(register), [sheet for _, sheet in differ]),
    )


# --------------------------------------------------------------------------- каталог


def run_register_checks(
    registers: list[RegisterView], sheets: list[SheetView], *, candidates: int
) -> list[CheckResult]:
    """Все проверки каталога по подтверждённым ведомостям; без них - «не проверено» с причиной.

    `candidates` - число найденных, но ещё не подтверждённых ведомостей последних ревизий.
    """
    if not registers:
        reason = (
            f"Найдено ведомостей листов: {candidates}, ни одна не подтверждена."
            if candidates
            else "Ведомости листов не найдены: запустите разбор ведомостей."
        )
        return [CheckResult(code, CheckStatus.NOT_RUN, reason) for code in _CODES]
    by_revision = _by_revision(sheets)
    ordered = sorted(registers, key=lambda item: (item.file_name, item.page_index, item.id))
    grouped: dict[str, list[RegisterView]] = defaultdict(list)
    for register in ordered:
        grouped[register.revision_id].append(register)
    results: list[CheckResult] = []
    for register in ordered:
        results.append(check_register_sheets(register, by_revision.get(register.revision_id, [])))
    for revision_id, group in grouped.items():
        results.append(check_sheets_in_register(group, by_revision.get(revision_id, [])))
    for register in ordered:
        results.append(check_register_titles(register, by_revision.get(register.revision_id, [])))
    return results
