"""Отметки этажей проекта по заголовкам схем КР: корпус -> этаж -> верх плиты (объект 346).

Планы АР корпуса часто без отметки в заголовке («Корпус 7. План 5-16 этажа»), а схемы несущих
конструкций КР того же корпуса называют отметку каждого этажа: «Схема расположения несущих
конструкций 5-16 этажей на отм. +21.800...+61.400», «30, 31 этажей на отм. +116.300, +119.900».
Паспорт листа (ADR-0043) уже разобрал этажи схемы (`level_from_ordinal` ... `level_to_ordinal`),
корпус - в имени файла («КР2.ГЧ.К7») или в паспорте. Отметки - из заголовка, мм верха плиты.

Чистые функции разбора и сборки таблицы; чтение паспортов - `load_project_levels`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SheetPassport
from app.services import sheet_passports
from app.services.consistency.dictionaries import SheetKind

# Отметка с тремя знаками после запятой: «+21.800», «-6,850», «112.700» (знак не обязателен).
MARK: Final = re.compile(r"(?<![\d.,])([+\-−–]?)\s?(\d{1,3})[.,](\d{3})(?![\d])")
# Многоточие между отметками - этажи диапазона через равный шаг: «+21.800...+61.400»,
# «+32,600, ..., +57,800».
ELLIPSIS: Final = re.compile(r"\.\s*\.\s*\.|…")
# Корпус в шифре или имени файла раздела КР: «КР2.ГЧ.К7», «КР2.ГЧ.К12».
CORPS_IN_CODE: Final = re.compile(r"\.К(\d{1,3})(?![\d])")


@dataclass(frozen=True, slots=True)
class ProjectLevel:
    """Отметка этажа корпуса и откуда она взята (`source` - для текста «по …»)."""

    z_mm: int
    ref: str
    source: str = "схеме КР"


# (корпус, номер этажа) -> отметка; корпус - как в заголовке плана («7»), без регистра.
ProjectLevels = Mapping[tuple[str, int], ProjectLevel]


@dataclass(frozen=True, slots=True)
class SchemeTitle:
    """Паспорт схемы КР, из которого берутся отметки этажей."""

    building: str | None
    file_name: str
    code: str | None
    title: str | None
    floor_from: int | None
    floor_to: int | None
    page_index: int


def corps_key(value: str | None) -> str | None:
    """Ключ корпуса для сравнения: без пробелов по краям и без регистра; пусто - `None`."""
    text = " ".join(value.split()).casefold() if value else ""
    return text or None


def marks_of(title: str) -> tuple[list[int], bool]:
    """Отметки заголовка после «отм.», мм, и есть ли между ними многоточие (равный шаг)."""
    at = title.casefold().find("отм")
    if at < 0:
        return [], False
    tail = title[at:]
    marks: list[int] = []
    for sign, whole, part in MARK.findall(tail):
        value = int(whole) * 1000 + int(part)
        marks.append(-value if sign in ("-", "−", "–") else value)
    return marks, bool(ELLIPSIS.search(tail))


def floor_marks(first: int, last: int, marks: list[int], ellipsis: bool) -> dict[int, int]:
    """Отметки этажей схемы: один этаж - первая отметка; по отметке на этаж - по порядку;
    две отметки через многоточие - равный шаг. Иначе (отметок больше или меньше этажей без
    многоточия) - только первый этаж: сопоставлять остальные не с чем.
    """
    count = last - first + 1
    if count <= 0 or not marks:
        return {}
    if count == 1:
        return {first: marks[0]}
    if len(marks) == count:
        return {first + i: mark for i, mark in enumerate(marks)}
    if len(marks) == 2 and ellipsis:
        step = (marks[1] - marks[0]) / (count - 1)
        return {first + i: round(marks[0] + i * step) for i in range(count)}
    return {first: marks[0]}


def scheme_corps(scheme: SchemeTitle) -> str | None:
    """Корпус схемы: из паспорта, иначе из шифра или имени файла («КР2.ГЧ.К7»)."""
    if scheme.building:
        return corps_key(scheme.building)
    for text in (scheme.code, scheme.file_name):
        found = CORPS_IN_CODE.search(text or "")
        if found:
            return found.group(1)
    return None


def collect_levels(schemes: Iterable[SchemeTitle]) -> dict[tuple[str, int], ProjectLevel]:
    """Таблица отметок: схема на меньшее число этажей важнее (точнее), затем по порядку листов."""
    ordered = sorted(
        (s for s in schemes if s.title and s.floor_from is not None),
        key=lambda s: (
            (s.floor_to or s.floor_from or 0) - (s.floor_from or 0),
            s.file_name,
            s.page_index,
        ),
    )
    levels: dict[tuple[str, int], ProjectLevel] = {}
    for scheme in ordered:
        corps = scheme_corps(scheme)
        title = scheme.title or ""
        if corps is None or scheme.floor_from is None:
            continue
        last = scheme.floor_to if scheme.floor_to is not None else scheme.floor_from
        marks, ellipsis = marks_of(title)
        ref = f"{scheme.file_name} · лист {scheme.page_index + 1}"
        for floor, z_mm in floor_marks(scheme.floor_from, last, marks, ellipsis).items():
            levels.setdefault((corps, floor), ProjectLevel(z_mm, ref))
    return levels


async def load_project_levels(
    session: AsyncSession, *, project_id: uuid.UUID
) -> dict[tuple[str, int], ProjectLevel]:
    """Таблица отметок по паспортам схем КР последних ревизий PDF проекта (кроме отклонённых)."""
    revisions = [
        revision.id
        for revision in await sheet_passports.latest_pdf_revisions(session, project_id=project_id)
    ]
    if not revisions:
        return {}
    rows = (
        await session.execute(
            select(
                SheetPassport.building,
                SheetPassport.file_name,
                SheetPassport.code,
                SheetPassport.title,
                SheetPassport.level_from_ordinal,
                SheetPassport.level_to_ordinal,
                SheetPassport.page_index,
            ).where(
                SheetPassport.project_id == project_id,
                SheetPassport.revision_id.in_(revisions),
                SheetPassport.sheet_kind == SheetKind.SCHEME.value,
                SheetPassport.section_mark.ilike("КР%"),
                SheetPassport.status != "rejected",
            )
        )
    ).all()
    return collect_levels(
        SchemeTitle(
            building=row.building,
            file_name=row.file_name,
            code=row.code,
            title=row.title,
            floor_from=row.level_from_ordinal,
            floor_to=row.level_to_ordinal,
            page_index=row.page_index,
        )
        for row in rows
    )
