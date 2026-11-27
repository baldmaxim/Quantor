"""Сборка общего вида здания: стопка этажей из листов проекта (ADR-0039 п. 7).

`cad_building3d` строит этаж листа, совмещает этажи группы по осям и ставит группы на объект.
Здесь - что из этого попадает в здание и как оно собрано:

1. в стопку идут только планы этажей и уровней; разрезы и дубли планов - «служебные листы»;
   туда же - сводный лист планов нескольких секций, не вставший на площадку: планы на нём
   разложены по листу, а не по объекту, и отдельным блоком в 3D он только мешает;
2. дубль плана в группе на одной отметке (монолит меньшего листа лежит на монолите большего) -
   остаётся лист большей площади;
3. группы одного корпуса, разведённые текстом заголовка («Корп. 8 · сек. 1-2» и «сек. 1-2»),
   сводятся по общей сетке осей;
4. типовой лист на несколько этажей показывается на отметке каждого своего этажа;
5. высота этажа без данных - разность отметок до следующего этажа здания;
6. планы по паспортам листов, которых в 3D нет, называются предупреждением.

Чистый расчёт (`build_stack`) - в потоке; в итоги обмера, calc и MEP вид не входит.
"""

from __future__ import annotations

import asyncio
import bisect
import contextlib
import dataclasses
import math
import re
import statistics
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_building3d import (
    CadBuilding3dFloorRead,
    CadBuilding3dGroupRead,
    CadBuilding3dRead,
    CadBuilding3dServiceReason,
    CadBuilding3dServiceSheetRead,
    CadBuilding3dWallRead,
    CadBuilding3dWarningRead,
)
from app.contracts.cad_constructions import CadSheetFloorTitle
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.models import Job, SheetPassport
from app.services import cad as cad_service
from app.services import (
    cad_axis_coordination_jobs,
    cad_building3d_grid,
    cad_facade_windows,
    cad_project_levels,
    cad_site_cores,
    cad_site_pins,
    cad_views,
    sheet_passports,
)
from app.services import cad_building3d as b3d
from app.services import cad_building3d_windows as b3d_windows
from app.services.cad_floor_title import floors_text, format_floor_title
from app.services.cad_site_pins_math import SitePin
from app.services.consistency.dictionaries import SheetKind
from app.storage.base import ObjectStorage

log = get_logger(__name__)

# Ключ группы сводного листа планов нескольких секций (`cad_building3d.build_floor`).
SUMMARY_PREFIX: Final = "summary-"
# Дубль плана: доля монолита меньшего листа, лежащая на монолите большего на той же отметке.
DUPLICATE_SHARE: Final = 0.9
# Сведение групп одного корпуса: согласных общих марок осей не меньше этого числа и этой доли
# осей меньшей из двух сеток.
MERGE_MIN_AXES: Final = 8
MERGE_MIN_SHARE: Final = 0.8
# Марка с номером секции («3.1», «1/2.4», «12-14.Г») одна на весь объект.
MERGE_PREFIXED_LABEL: Final = re.compile(r"\d{1,2}(?:[/\-]\d{1,2})?[.\-]")
# Фрагмент плана рядом с планом этажа на листе корпуса («Фрагмент плана 6-14 этажей», объект 346):
# стены целиком дальше этого от пятна корпуса (медиана габаритов его этажей) - не этаж.
FRAGMENT_MARGIN_MM: Final = 8000
# Отбрасывается только меньшинство стен этажа: большее - не фрагмент, а сдвинутый этаж.
FRAGMENT_MAX_SHARE: Final = 0.4
# Высота этажа по стопке: разность отметок до следующего этажа здания в этих пределах, мм.
STACK_HEIGHT_MIN_MM: Final = 2000
STACK_HEIGHT_MAX_MM: Final = 6000


# --------------------------------------------------------------------------- дубли планов


def _site_rings(item: b3d.BuiltFloor, floor: CadBuilding3dFloorRead) -> list[b3d.CoreRing]:
    dx, dy = floor.offset_mm
    return [b3d._moved_ring(ring, floor.rotation_deg, dx, dy) for ring in item.cores]


def monolith_share(base: Sequence[b3d.CoreRing], other: Sequence[b3d.CoreRing]) -> float:
    """Доля монолита `other` (клетки сетки ядер), лежащая на монолите `base`; мало монолита - 0."""
    samples = cad_site_cores.raster(other)
    if len(samples) < cad_site_cores.MIN_SAMPLES:
        return 0.0
    cells = b3d.base_index(base).cells
    cell = cad_site_cores.CELL_MM
    hits = sum(1 for x, y in samples if (math.floor(x / cell), math.floor(y / cell)) in cells)
    return hits / len(samples)


def find_superseded(
    items: Sequence[b3d.BuiltFloor], aligned: Sequence[CadBuilding3dFloorRead]
) -> dict[int, int]:
    """Дубли планов: индекс лишнего листа -> индекс оставленного (листа большей площади).

    Дубль - лист той же группы на той же отметке, совмещённый по осям, чей монолит лежит на
    монолите большего листа не меньше чем на `DUPLICATE_SHARE` (подземная автостоянка «Этап 1» -
    часть листа «Этапы 1 и 2»). Без осей и без монолита сравнить нечем - лист остаётся.
    """
    by_group: dict[str, list[int]] = {}
    for index, floor in enumerate(aligned):
        if (
            floor.elevation_known
            and floor.alignment != "none"
            and floor.bbox is not None
            and len(items[index].cores) >= b3d.CORE_MIN_RINGS
        ):
            by_group.setdefault(floor.group_key, []).append(index)
    superseded: dict[int, int] = {}
    for indexes in by_group.values():
        kept: list[int] = []
        for index in sorted(indexes, key=lambda i: (-b3d._floor_area_m2(aligned[i]), i)):
            floor, box = aligned[index], aligned[index].bbox
            keeper = next(
                (
                    k
                    for k in kept
                    if abs(aligned[k].base_z_mm - floor.base_z_mm) <= b3d.SITE_SAME_LEVEL_MM
                    and box is not None
                    and (base_box := aligned[k].bbox) is not None
                    and b3d._overlap_share(base_box, box) > 0
                    and monolith_share(
                        _site_rings(items[k], aligned[k]), _site_rings(items[index], floor)
                    )
                    >= DUPLICATE_SHARE
                ),
                None,
            )
            if keeper is None:
                kept.append(index)
            else:
                superseded[index] = keeper
    return superseded


# --------------------------------------------------------------------------- сведение групп


@dataclass(frozen=True, slots=True)
class _Group:
    key: str
    label: str
    size: int
    axes: b3d.FloorAxes
    # Корпус и секция: из заголовков планов, иначе из паспортов листов; разные у листов - `None`.
    corps: str | None
    section: str | None
    # Корпус назван в заголовке плана: такая группа даёт имя сведённому зданию.
    named: bool
    mergeable: bool


def section_count(section: str | None) -> int:
    """Число секций в подписи: «3» - 1, «1-2» - 2, «12-14» - 3, «8, 9, 10» - 3."""
    if not section:
        return 0
    total = 0
    for part in re.split(r"[,;]", section):
        numbers = [int(n) for n in re.findall(r"\d+", part)]
        if len(numbers) == 2 and numbers[0] < numbers[1] and re.search(r"\d\s*[-–]\s*\d", part):
            total += numbers[1] - numbers[0] + 1
        else:
            total += max(len(numbers), 1)
    return total


def _single(values: Sequence[str | None]) -> str | None:
    found = {value.casefold() for value in values if value}
    return next(iter(found)) if len(found) == 1 else None


def _groups(
    items: Sequence[b3d.BuiltFloor], aligned: Sequence[CadBuilding3dFloorRead]
) -> list[_Group]:
    by_group: dict[str, list[int]] = {}
    for index, floor in enumerate(aligned):
        by_group.setdefault(floor.group_key, []).append(index)
    groups: list[_Group] = []
    for key, indexes in by_group.items():
        floors = [aligned[i] for i in indexes]
        axes = b3d._group_axes([items[i] for i in indexes], floors)
        corps = _single([f.corps for f in floors]) or _single([items[i].hint[0] for i in indexes])
        section = _single([f.section for f in floors]) or _single(
            [items[i].hint[1] for i in indexes]
        )
        underground = any(f.elevation_known and f.base_z_mm < 0 for f in floors)
        groups.append(
            _Group(
                key=key,
                label=floors[0].group_label,
                size=len(indexes),
                axes=axes,
                corps=corps,
                section=section,
                named=any(f.corps for f in floors),
                # Сводный план нескольких секций и подземная часть - не здание корпуса: их место
                # относительно корпусов - постановка на объект, а не одна стопка.
                mergeable=axes.usable
                and not underground
                and not key.startswith(SUMMARY_PREFIX)
                and section_count(section) < b3d.SUMMARY_MIN_SECTIONS,
            )
        )
    return groups


def _same_building(first: _Group, second: _Group) -> bool:
    """Две группы - одно здание: одна сетка осей с одним сдвигом и нет спора о корпусе и секции."""
    along_x = b3d._match_orient(first.axes.vertical, second.axes.vertical, "")
    along_y = b3d._match_orient(first.axes.horizontal, second.axes.horizontal, "")
    if isinstance(along_x, str) or isinstance(along_y, str):
        return False
    agreed = [*along_x.labels, *along_y.labels]
    smaller = min(
        len(first.axes.vertical) + len(first.axes.horizontal),
        len(second.axes.vertical) + len(second.axes.horizontal),
    )
    if len(agreed) < MERGE_MIN_AXES or len(agreed) < MERGE_MIN_SHARE * smaller:
        return False
    if first.corps and second.corps and first.corps != second.corps:
        return False
    if first.section and second.section and first.section != second.section:
        return False
    if first.corps and second.corps and first.section and second.section:
        return True
    # Корпус или секция одной из групп неизвестны: марки без номера секции («1», «А») повторяются
    # у типовых секций, поэтому совпасть должны марки с номером секции.
    return sum(1 for label in agreed if MERGE_PREFIXED_LABEL.match(label)) >= MERGE_MIN_AXES


def merge_groups(
    items: Sequence[b3d.BuiltFloor], aligned: Sequence[CadBuilding3dFloorRead]
) -> dict[str, tuple[str, str]]:
    """Группы одного корпуса: ключ группы -> ключ и подпись здания, в которое она входит.

    Заголовок плана называет здание по-разному («Корп. 8 · сек. 1-2», «сек. 1-2», без корпуса и
    секции), и корпус дробится на несколько «зданий» с общей сеткой осей. Группы сводятся, если
    согласных общих марок не меньше `MERGE_MIN_AXES` и это не меньше `MERGE_MIN_SHARE` осей меньшей
    сетки; корпус и секция паспортов листов - подсказка: разные корпуса или секции не сводятся.
    Имя даёт группа с корпусом в заголовке, затем большая. Сводные планы (от трёх секций) и
    подземная часть не сводятся.
    """
    groups = [group for group in _groups(items, aligned) if group.mergeable]
    parent = {group.key: group.key for group in groups}

    def root(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for i, first in enumerate(groups):
        for second in groups[i + 1 :]:
            if root(first.key) != root(second.key) and _same_building(first, second):
                parent[root(second.key)] = root(first.key)
    families: dict[str, list[_Group]] = {}
    for group in groups:
        families.setdefault(root(group.key), []).append(group)
    merged: dict[str, tuple[str, str]] = {}
    for family in families.values():
        if len(family) < 2:
            continue
        target = min(family, key=lambda g: (not g.named, -g.size, b3d._natural_key(g.label), g.key))
        for group in family:
            if group.key != target.key:
                merged[group.key] = (target.key, target.label)
    return merged


# --------------------------------------------------------------------------- типовые листы


def _lifted(floor: CadBuilding3dFloorRead, dz: int) -> CadBuilding3dFloorRead:
    """Та же геометрия на другой отметке: этаж типового листа."""
    walls = (
        None
        if floor.walls is None
        else [
            wall
            if wall.top_mm is None
            else CadBuilding3dWallRead.model_construct(
                id=wall.id, kind=wall.kind, shell=wall.shell, top_mm=wall.top_mm + dz
            )
            for wall in floor.walls
        ]
    )
    levels = [
        zone.model_copy(
            update={
                "top_mm": zone.top_mm + dz,
                "mark_mm": None if zone.mark_mm is None else zone.mark_mm + dz,
                "max_mm": None if zone.max_mm is None else zone.max_mm + dz,
            }
        )
        for zone in floor.levels
    ]
    return floor.model_copy(
        update={
            "base_z_mm": floor.base_z_mm + dz,
            "walls": walls,
            "windows": b3d_windows.lift_windows(floor.windows, dz),
            "levels": levels,
        }
    )


def expand_typical(
    items: Sequence[b3d.BuiltFloor], floors: Sequence[CadBuilding3dFloorRead]
) -> tuple[list[CadBuilding3dFloorRead], list[tuple[CadBuilding3dFloorRead, b3d.BuiltFloor]]]:
    """Этажи типовых листов: этаж листа с подписью своего этажа и копии на остальных отметках.

    Копия (`typical_of`) - только для 3D: геометрия листа на отметке другого его этажа, в объёмы
    листа она не входит. Лист без отметки не размножается: ставить копии не от чего. Копия не
    ставится на отметку, где в здании уже есть этаж своего листа («3-7 эт.» и отдельный лист
    6 этажа) или копия другого листа.
    """
    taken: dict[str, list[int]] = {}
    for floor in floors:
        if floor.elevation_known:
            taken.setdefault(floor.group_key, []).append(floor.base_z_mm)
    real: list[CadBuilding3dFloorRead] = []
    copies: list[tuple[CadBuilding3dFloorRead, b3d.BuiltFloor]] = []
    for item, floor in zip(items, floors, strict=True):
        plan = item.typical
        if plan is None or not floor.elevation_known:
            real.append(floor)
            continue
        real.append(floor.model_copy(update={"label": plan.own}))
        levels = taken[floor.group_key]
        for label, delta in plan.others:
            base_z = floor.base_z_mm + delta
            if any(abs(z - base_z) <= b3d.SITE_SAME_LEVEL_MM for z in levels):
                continue
            levels.append(base_z)
            copy = _lifted(floor, delta).model_copy(
                update={"label": label, "typical_of": floor.label}
            )
            copies.append((copy, item))
    return real, copies


# --------------------------------------------------------------------------- отметки проекта

# Отметка по паспорту или схеме КР заменяет отметку по знакам плана, только если они расходятся
# больше этого: пирог пола и местные перепады плиты - сотни мм, ошибочный знак плана - метры
# (объект 346: выход на кровлю корпуса 5 на -23,26 м при +112,95 в заголовке).
PROJECT_LEVEL_TOLERANCE_MM: Final = 400
# Типовой лист шире этого по паспорту - не перечень этажей, а ошибка разбора: не размножается.
PROJECT_FLOORS_MAX: Final = 60


def _sheet_floors(sheet: b3d.SheetRef, item: b3d._SheetFloor) -> list[int]:
    """Номера этажей листа: из заголовка плана (cad_walls), иначе «от - до» паспорта."""
    numbers = [int(f) for f in item.title_floors if f.lstrip("-").isdigit()]
    if numbers:
        return numbers
    first, last = sheet.passport_floor_from, sheet.passport_floor_to
    if first is None:
        return []
    last = first if last is None else last
    if not 0 <= last - first <= PROJECT_FLOORS_MAX:
        return []
    return [n for n in range(first, last + 1) if n != 0]


def _own_floor(
    floors: Sequence[int],
    corps: str,
    floor: CadBuilding3dFloorRead,
    levels: cad_project_levels.ProjectLevels,
) -> int | None:
    """Этаж самого листа среди его этажей с отметкой КР: ближайший по отметке, иначе первый."""
    known = [f for f in floors if (corps, f) in levels]
    if not known:
        return None
    if not floor.elevation_known:
        return known[0]
    return min(
        known, key=lambda f: (abs(levels[(corps, f)].z_mm - floor.base_z_mm), floors.index(f))
    )


def _typical_label(floor: CadBuilding3dFloorRead, number: int, sheet_floors: str) -> str:
    title = CadSheetFloorTitle(
        corps=floor.corps, section=floor.section, floors=[str(number)], kind=floor.kind
    )
    return f"{format_floor_title(title, floor.label)} (по листу «{sheet_floors} эт.»)"


def apply_project_levels(
    sheets: Sequence[b3d.SheetRef],
    loaded: Sequence[b3d._SheetFloor],
    levels: cad_project_levels.ProjectLevels,
) -> list[b3d._SheetFloor]:
    """Отметки этажей и типовые этажи по паспортам, когда в заголовке плана отметок нет.

    Отметка этажа: из заголовка листа по паспорту, иначе из схемы КР корпуса для этажа листа;
    отметку по знакам плана она заменяет при расхождении больше `PROJECT_LEVEL_TOLERANCE_MM`
    (с предупреждением). Типовой лист («5-16 этажа») разносится по отметкам КР своих этажей.
    Лист с отметками в заголовке плана не трогается: там отметки дал сам лист.
    """
    out: list[b3d._SheetFloor] = []
    for sheet, item in zip(sheets, loaded, strict=True):
        floor = item.floor
        if floor is None or item.title_marked:
            out.append(item)
            continue
        corps = cad_project_levels.corps_key(floor.corps or sheet.passport_building)
        floors = _sheet_floors(sheet, item)
        warnings = list(item.warnings)
        target: int | None = None
        why = ""
        if sheet.passport_elevation_mm is not None:
            target, why = sheet.passport_elevation_mm, "по заголовку листа"
        elif corps is not None and floors:
            own = _own_floor(floors, corps, floor, levels)
            if own is not None:
                level = levels[(corps, own)]
                target, why = level.z_mm, f"по {level.source} ({level.ref})"
        if target is not None and (
            not floor.elevation_known or abs(floor.base_z_mm - target) > PROJECT_LEVEL_TOLERANCE_MM
        ):
            before = floor.base_z_mm if floor.elevation_known else None
            floor = _lifted(floor, target - floor.base_z_mm).model_copy(
                update={"elevation_known": True}
            )
            text = f"{floor.label}: отметка этажа {target / 1000:+.3f} {why}"
            if before is not None:
                text += f" вместо {before / 1000:+.3f} по знакам отметок плана"
            warnings.append(
                CadBuilding3dWarningRead(code="floor_elevation_project", message=f"{text}.")
            )
        typical = item.typical
        if typical is None and corps is not None and len(floors) > 1 and floor.elevation_known:
            own = _own_floor(floors, corps, floor, levels)
            if own is not None:
                base = levels[(corps, own)].z_mm
                sheet_floors = floors_text([str(f) for f in floors]) or ""
                others = tuple(
                    (_typical_label(floor, f, sheet_floors), levels[(corps, f)].z_mm - base)
                    for f in floors
                    if f != own and (corps, f) in levels and levels[(corps, f)].z_mm != base
                )
                if others:
                    typical = b3d.TypicalPlan(_typical_label(floor, own, sheet_floors), others)
                    warnings = [w for w in warnings if w.code != "typical_floors_unplaced"]
                    missing = [str(f) for f in floors if f != own and (corps, f) not in levels]
                    if missing:
                        warnings.append(
                            CadBuilding3dWarningRead(
                                code="typical_floors_unplaced",
                                message=f"{floor.label}: этажи {', '.join(missing)} - отметок в "
                                "схемах КР нет, не показаны.",
                            )
                        )
        out.append(
            dataclasses.replace(item, floor=floor, typical=typical, warnings=tuple(warnings))
        )
    return out


# --------------------------------------------------------------------------- высота по стопке


def stack_heights(floors: Sequence[CadBuilding3dFloorRead]) -> list[CadBuilding3dFloorRead]:
    """Высота этажа без данных - разность отметок до следующего этажа здания.

    Следующий - ближайший этаж группы выше этого (лист того же уровня, в пределах
    `SITE_SAME_LEVEL_MM`, - не следующий этаж). Разность вне `STACK_HEIGHT_MIN_MM` ...
    `STACK_HEIGHT_MAX_MM` (техпространство ниже этажа, этажи между ними в 3D не попали, спорная
    отметка соседа) или соседа нет - типовая высота. Высота остаётся неизвестной
    (`floor_height_known = false`): это значение для отрисовки, с источником.
    """
    marks: dict[str, list[int]] = {}
    for floor in floors:
        if floor.elevation_known:
            marks.setdefault(floor.group_key, []).append(floor.base_z_mm)
    for values in marks.values():
        values.sort()
    result: list[CadBuilding3dFloorRead] = []
    for floor in floors:
        if floor.floor_height_known:
            result.append(floor)
            continue
        update: dict[str, object] = {"floor_height_source": "default"}
        if floor.elevation_known:
            values = marks[floor.group_key]
            at = bisect.bisect_right(values, floor.base_z_mm + b3d.SITE_SAME_LEVEL_MM)
            step = values[at] - floor.base_z_mm if at < len(values) else None
            if step is not None and STACK_HEIGHT_MIN_MM <= step <= STACK_HEIGHT_MAX_MM:
                update = {"floor_height_mm": step, "floor_height_source": "derived_stack"}
        result.append(floor.model_copy(update=update))
    return result


# --------------------------------------------------------------------------- стопка


@dataclass(frozen=True, slots=True)
class Stack:
    """Собранное здание. `kept` - индексы входных этажей, вошедших в стопку, `real` - их этажи в том
    же порядке (после постановки и высот); `superseded` - индекс дубля -> индекс оставленного;
    `summaries` - индексы этажей сводных листов, не вставших на площадку (в стопку не входят)."""

    floors: list[CadBuilding3dFloorRead]
    groups: list[CadBuilding3dGroupRead]
    kept: list[int]
    real: list[CadBuilding3dFloorRead]
    superseded: dict[int, int]
    # Ручные привязки корпусов к площадке (ADR-0052), которые не применены, с причиной.
    ignored_pins: tuple[b3d.PinIgnored, ...] = ()
    summaries: tuple[int, ...] = ()
    # Этажи, у которых отброшен фрагмент плана вне пятна корпуса: подпись этажа и число стен.
    fragments: tuple[tuple[str, int], ...] = ()


def _box_of(shell: Sequence[Sequence[int]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in shell]
    ys = [p[1] for p in shell]
    return min(xs), min(ys), max(xs), max(ys)


def drop_fragments(
    floors: Sequence[CadBuilding3dFloorRead],
) -> tuple[list[CadBuilding3dFloorRead], list[tuple[str, int]]]:
    """Стены этажа корпуса целиком вне пятна корпуса - фрагмент плана на том же листе, не этаж.

    Пятно - медиана габаритов этажей группы (в системе группы, до постановки) с запасом
    `FRAGMENT_MARGIN_MM`: фрагменты есть на немногих листах и медиану не сдвигают, выходы на
    кровлю и террасы лежат внутри. Только группы корпусов (ключ «k…»), этажи со стенами, и только
    если отброшенных стен меньше `FRAGMENT_MAX_SHARE` - иначе сдвинут весь этаж, и это не фрагмент.
    """
    by_group: dict[str, list[int]] = {}
    for i, floor in enumerate(floors):
        if floor.group_key.startswith("k") and floor.walls and floor.bbox:
            by_group.setdefault(floor.group_key, []).append(i)
    out = list(floors)
    notes: list[tuple[str, int]] = []
    for members in by_group.values():
        if len(members) < 3:
            continue
        boxes = [floors[i].bbox for i in members if floors[i].bbox is not None]
        median = [statistics.median(b[k] for b in boxes if b is not None) for k in range(4)]
        x0, y0 = median[0] - FRAGMENT_MARGIN_MM, median[1] - FRAGMENT_MARGIN_MM
        x1, y1 = median[2] + FRAGMENT_MARGIN_MM, median[3] + FRAGMENT_MARGIN_MM
        for i in members:
            floor = floors[i]
            walls = floor.walls or []
            kept = []
            for wall in walls:
                bx0, by0, bx1, by1 = _box_of(wall.shell)
                if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
                    continue
                kept.append(wall)
            dropped = len(walls) - len(kept)
            if not dropped or not kept or dropped > FRAGMENT_MAX_SHARE * len(walls):
                continue
            boxes_kept = [_box_of(w.shell) for w in kept]
            bbox = [
                min(b[0] for b in boxes_kept),
                min(b[1] for b in boxes_kept),
                max(b[2] for b in boxes_kept),
                max(b[3] for b in boxes_kept),
            ]
            out[i] = floor.model_copy(update={"walls": kept, "bbox": bbox})
            notes.append((floor.label, dropped))
    return out, notes


def build_stack(
    built: Sequence[b3d.BuiltFloor],
    pins: Sequence[SitePin] = (),
    grid_version: int | None = None,
) -> Stack:
    """Здание из этажей листов: совмещение, дубли, сведение групп, постановка, типовые, высоты.

    `grid_version` - номер утверждённой версии модели, к сетке осей которой подогнаны этажи
    (`BuiltFloor.grid`): не вставшие на объект здания ставятся по ней (`cad_building3d_grid`).
    """
    items = list(built)
    kept = list(range(len(items)))
    aligned = b3d.align_floors(items)
    superseded = find_superseded(items, aligned)
    if superseded:
        # Этажи остаются в системе прежнего эталона группы: для сведения групп этого достаточно.
        kept = [i for i in kept if i not in superseded]
        items = [items[i] for i in kept]
        aligned = [aligned[i] for i in kept]
    merged = merge_groups(items, aligned)
    if merged:
        renamed: list[b3d.BuiltFloor] = []
        for item, floor in zip(items, aligned, strict=True):
            # Ключ - по итогу совмещения: «Корпус не указан» уже разделён на здания по сеткам осей.
            # Остальные этажи остаются со своим исходным ключом: деление повторится так же.
            target = merged.get(floor.group_key)
            renamed.append(
                item
                if target is None
                else dataclasses.replace(
                    item,
                    floor=item.floor.model_copy(
                        update={"group_key": target[0], "group_label": target[1]}
                    ),
                )
            )
        items = renamed
    if superseded or merged:
        aligned = b3d.align_floors(items)
    aligned, fragments = drop_fragments(aligned)
    if grid_version is not None:
        aligned = cad_building3d_grid.split_unaligned_unnamed(items, aligned)
    site = b3d.place_site_report(items, aligned, pins)
    placements = site.placements
    if grid_version is not None:
        placements, aligned = cad_building3d_grid.place_and_align_by_grid(
            items, aligned, placements, grid_version
        )
    lost = unplaced_summaries(placements)
    summaries: tuple[int, ...] = ()
    if lost:
        drop = {i for i, floor in enumerate(aligned) if floor.group_key in lost}
        summaries = tuple(kept[i] for i in sorted(drop))
        keep = [i for i in range(len(items)) if i not in drop]
        kept = [kept[i] for i in keep]
        items = [items[i] for i in keep]
        aligned = [aligned[i] for i in keep]
        placements = {k: p for k, p in placements.items() if k not in lost}
    placed = b3d.apply_placements(aligned, placements)
    real, copies = expand_typical(items, placed)
    # Верх стены этажа известен только после высот по стопке: окна обрезаются по нему здесь.
    heights = [
        b3d_windows.finalize_windows(floor)
        for floor in stack_heights([*real, *(copy for copy, _item in copies)])
    ]
    real = heights[: len(real)]
    floors = b3d.sort_floors(
        [
            *((floor, item.order) for floor, item in zip(real, items, strict=True)),
            *(
                (floor, item.order)
                for floor, (_copy, item) in zip(heights[len(real) :], copies, strict=True)
            ),
        ]
    )
    return Stack(
        floors,
        b3d.build_groups(floors, placements),
        kept,
        real,
        superseded,
        site.ignored,
        summaries,
        tuple(fragments),
    )


def unplaced_summaries(placements: dict[str, b3d.GroupPlacement]) -> frozenset[str]:
    """Сводные листы (`summary-…`), не вставшие на площадку, когда на объекте есть другие здания.

    Вставший по ядрам сводный лист остаётся в здании: он стоит на своём месте и служит опорой.
    """
    if len(placements) <= 1:
        return frozenset()
    return frozenset(
        key
        for key, placement in placements.items()
        if key.startswith(SUMMARY_PREFIX) and placement.placement == "none"
    )


def review_warnings(groups: Sequence[CadBuilding3dGroupRead]) -> list[CadBuilding3dWarningRead]:
    """Предупреждения о посадке по ядрам «на проверку» (согласие этажей, отсев мест)."""
    return [
        CadBuilding3dWarningRead(
            code="group_placement_review", message=f"{g.label}: {g.placement_message}"
        )
        for g in groups
        if g.placement == "cores" and g.placement_message
    ]


# --------------------------------------------------------------------------- планов нет в 3D


def _convert_failure(job: Job, page_index: int) -> str:
    """Код причины, по которой задание не дало DXF страницы: из итога вида, иначе из задания."""
    for page in cad_service.result_of(job).get("pages", []):
        if not isinstance(page, dict) or page.get("index") != page_index:
            continue
        for view in page.get("views", []):
            if not isinstance(view, dict):
                continue
            for field in ("failure_code", "scale_status", "status"):
                code = view.get(field)
                if isinstance(code, str) and code and code not in cad_views.SCALE_PASSED_STATUSES:
                    return code
    return job.error_code or job.status.value


def _requested_pages(job: Job) -> list[Any]:
    params = job.payload.get("params")
    pages = params.get("pages") if isinstance(params, dict) else None
    return pages if isinstance(pages, list) else []


async def collect_missing_plans(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    sheets: Sequence[b3d.SheetRef],
) -> list[CadBuilding3dWarningRead]:
    """Планы этажей по паспортам листов, которых в 3D нет: название листа и код конвертации.

    Паспорт `floor_plan` последней ревизии документа без успешной конвертации страницы в DXF
    (лист с DXF, но без конструкций называет предупреждение `walls_not_ready`). Код - из итога
    последнего задания `cad_pdf_convert` этой страницы; задания не было - так и сказано.
    """
    revisions = {
        revision.id: revision
        for revision in await sheet_passports.latest_pdf_revisions(session, project_id=project_id)
    }
    if not revisions:
        return []
    rows = (
        await session.execute(
            select(
                SheetPassport.revision_id,
                SheetPassport.page_index,
                SheetPassport.file_name,
                SheetPassport.title,
            )
            .where(
                SheetPassport.project_id == project_id,
                SheetPassport.revision_id.in_(list(revisions)),
                SheetPassport.sheet_kind == SheetKind.FLOOR_PLAN.value,
                SheetPassport.status != "rejected",
            )
            .order_by(SheetPassport.file_name, SheetPassport.page_index)
        )
    ).all()
    covered = {(sheet.document_id, sheet.page_index) for sheet in sheets}
    missing = [
        row
        for row in rows
        if (revisions[row.revision_id].document_id, row.page_index) not in covered
    ]
    if not missing:
        return []
    wanted = {str(row.revision_id) for row in missing}
    jobs = list(
        await session.scalars(
            select(Job)
            .where(
                Job.workspace_id == workspace_id,
                Job.project_id == project_id,
                Job.job_type == JobType.CAD_PDF_CONVERT,
                Job.payload["revision_id"].astext.in_(wanted),
            )
            .order_by(Job.created_at.desc(), Job.id)
        )
    )
    warnings: list[CadBuilding3dWarningRead] = []
    for row in missing:
        last = next(
            (
                job
                for job in jobs
                if job.payload.get("revision_id") == str(row.revision_id)
                and row.page_index in _requested_pages(job)
            ),
            None,
        )
        name = f"{row.file_name} · лист {row.page_index + 1}"
        if row.title:
            name = f"{name} «{row.title}»"
        if last is None:
            reason = "конвертация листа в DXF не запускалась"
        elif last.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            reason = "конвертация листа в DXF ещё идёт"
        else:
            reason = f"последняя конвертация листа в DXF: {_convert_failure(last, row.page_index)}"
        warnings.append(
            CadBuilding3dWarningRead(
                code="floor_missing", message=f"{name}: плана этажа нет в 3D - {reason}."
            )
        )
    return warnings


# --------------------------------------------------------------------------- ответ


def _service_sheet(
    sheet: b3d.SheetRef, reason: CadBuilding3dServiceReason, message: str
) -> CadBuilding3dServiceSheetRead:
    return CadBuilding3dServiceSheetRead(
        job_id=sheet.job_id,
        revision_id=sheet.revision_id,
        page_index=sheet.page_index,
        view=sheet.view,
        document_id=sheet.document_id,
        label=sheet.label,
        reason=reason,
        message=message,
    )


def _drift(permille: float) -> str:
    return f"{permille:+.1f}".replace(".", ",")


async def _with_windows(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    loaded: list[b3d._SheetFloor],
) -> tuple[list[b3d._SheetFloor], list[b3d_windows.FloorWindows | None], bool]:
    """Окна этажей с высотами по фасадам и ручному вводу (ADR-0048 п. 6).

    Виды фасадов проекта грузятся один раз на запрос; этажи в кеше не меняются: окна кладутся в
    копию этажа. Результат по каждому листу (`None` - лист пропущен или окон в плане нет) отдаётся
    отдельно: замечания считаются только по этажам, вошедшим в стопку. Любая ошибка расчёта этажа
    даёт ему пустой список окон и `failed`; ошибка чтения видов - пустые окна всего здания и
    `views_failed` (последнее значение), ответ здания не падает.
    """
    has_sources = any(item.floor is not None and item.windows is not None for item in loaded)
    views = cad_facade_windows.LoadedViews([])
    views_failed = False
    if has_sources:
        try:
            views = await cad_facade_windows.load_views(
                session, workspace_id=workspace_id, project_id=project_id
            )
        except Exception as error:
            log.warning("cad_building3d_windows_views_failed", error=type(error).__name__)
            views_failed = True
            if isinstance(error, SQLAlchemyError):
                # Прерванная ошибкой транзакция не должна ломать дальнейшие чтения запроса.
                with contextlib.suppress(Exception):
                    await session.rollback()

    def compute() -> tuple[list[b3d._SheetFloor], list[b3d_windows.FloorWindows | None]]:
        out: list[b3d._SheetFloor] = []
        results: list[b3d_windows.FloorWindows | None] = []
        for item in loaded:
            floor = item.floor
            if floor is None:
                out.append(item)
                results.append(None)
                continue
            result: b3d_windows.FloorWindows | None = None
            if item.windows is not None and not views_failed:
                try:
                    result = b3d_windows.floor_windows(item.windows, floor.base_z_mm, views)
                except Exception as error:
                    log.warning("cad_building3d_windows_failed", error=type(error).__name__)
                    result = b3d_windows.FloorWindows([], failed=True)
            results.append(result)
            shown = [] if result is None else result.windows
            out.append(dataclasses.replace(item, floor=floor.model_copy(update={"windows": shown})))
        return out, results

    out, results = await asyncio.to_thread(compute)
    return out, results, views_failed


def _window_warnings(
    notes: b3d_windows.WindowNotes,
    *,
    views_failed: bool,
    unknown_wall_floors: int,
    dropped: int,
    floors: Sequence[CadBuilding3dFloorRead],
) -> list[CadBuilding3dWarningRead]:
    """Замечания по окнам: без высоты, без контура, фасады, кандидаты, верх стены, сбои."""
    warnings: list[CadBuilding3dWarningRead] = []
    if views_failed:
        warnings.append(
            CadBuilding3dWarningRead(
                code=b3d_windows.CODE_VIEWS_FAILED,
                message="Окна не построены: виды фасадов проекта не прочитаны.",
            )
        )
    if notes.failed:
        warnings.append(
            CadBuilding3dWarningRead(
                code=b3d_windows.CODE_FAILED,
                message=f"Окна не построены из-за ошибки расчёта на этажах: {notes.failed}.",
            )
        )
    if notes.without_height:
        warnings.append(
            CadBuilding3dWarningRead(
                code=b3d_windows.CODE_WITHOUT_HEIGHT,
                message="Окна без высоты (фасад или ручной ввод листа) не построены, проём "
                f"остаётся открытым: {notes.without_height} (этажей: "
                f"{notes.floors_without_height}).",
            )
        )
    if notes.no_contour:
        warnings.append(
            CadBuilding3dWarningRead(
                code=b3d_windows.CODE_NO_CONTOUR,
                message=f"Окна с высотой без контура проёма не показаны: {notes.no_contour}.",
            )
        )
    if unknown_wall_floors:
        warnings.append(
            CadBuilding3dWarningRead(
                code=b3d_windows.CODE_WALL_HEIGHT_UNKNOWN,
                message="Высота этажа или толщина плиты не определены (показана типовая): окна "
                f"этажей не построены. Этажей: {unknown_wall_floors}.",
            )
        )
    warnings.extend(
        CadBuilding3dWarningRead(
            code=code, message=f"{message} Этажей: {count}." if count > 1 else message
        )
        for code, (message, count) in notes.issues.items()
    )
    candidates = sum(1 for floor in floors for w in floor.windows or () if not w.accepted)
    if candidates:
        warnings.append(
            CadBuilding3dWarningRead(
                code=b3d_windows.CODE_UNACCEPTED,
                message=f"Окна по непринятым видам фасадов: {candidates}, показаны как кандидаты.",
            )
        )
    if dropped > 0:
        warnings.append(
            CadBuilding3dWarningRead(
                code=b3d_windows.CODE_ABOVE_WALL,
                message=f"Окно выше верха стены этажа: {dropped}; окно не построено.",
            )
        )
    return warnings


async def build_building3d(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    include_walls: bool = False,
) -> CadBuilding3dRead:
    sheets, warnings, project_slab = await b3d.collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    missing = await collect_missing_plans(
        session, workspace_id=workspace_id, project_id=project_id, sheets=sheets
    )
    gate = asyncio.Semaphore(b3d.READ_CONCURRENCY)
    generation = b3d.floor_cache.begin()
    loaded = await asyncio.gather(
        *(
            b3d._load_sheet_floor(storage, sheet, project_slab, include_walls, gate, generation)
            for sheet in sheets
        )
    )
    # Отметки этажей по паспортам (заголовок листа, схемы КР) - до окон: окна ставятся от базы.
    # Утверждённая модель здания добавляет отметки этажей, которых в КР нет, и сетку осей.
    reference = await cad_building3d_grid.load_model_reference(
        session, storage, workspace_id=workspace_id, project_id=project_id
    )
    project_levels = await cad_project_levels.load_project_levels(session, project_id=project_id)
    loaded = apply_project_levels(
        sheets, loaded, cad_building3d_grid.merged_levels(project_levels, reference)
    )
    window_results: list[b3d_windows.FloorWindows | None] = []
    views_failed = False
    if include_walls:
        loaded, window_results, views_failed = await _with_windows(
            session, workspace_id=workspace_id, project_id=project_id, loaded=loaded
        )
    # Смещения из координации ИИ - один запрос на сборку, по заданию конструкций цели.
    hints = await cad_axis_coordination_jobs.load_hints(
        session, workspace_id=workspace_id, project_id=project_id
    )
    built: list[b3d.BuiltFloor] = []
    sources: list[tuple[b3d.SheetRef, tuple[CadBuilding3dWarningRead, ...]]] = []
    built_windows: list[b3d_windows.FloorWindows | None] = []
    service: list[CadBuilding3dServiceSheetRead] = []
    for position, (sheet, item) in enumerate(zip(sheets, loaded, strict=True)):
        if item.floor is None:
            warnings.extend(item.warnings)
            if item.service is not None:
                service.append(_service_sheet(sheet, "not_plan", f"{sheet.label}: {item.service}."))
            continue
        built.append(
            b3d.BuiltFloor(
                item.floor,
                sheet.order,
                item.axes,
                item.cores,
                item.typical,
                (sheet.passport_building, sheet.passport_section),
                None
                if reference is None
                else cad_building3d_grid.floor_fit(item.axes, reference.axes),
                item.coord_axes,
            )
        )
        sources.append((sheet, item.warnings))
        built_windows.append(window_results[position] if window_results else None)
    # Сохранённые пары координации ИИ - к текущим осям, смещение пересчитывает код.
    built = cad_axis_coordination_jobs.apply_hints(built, hints)
    # Совмещение, дубли и постановка по ядрам - чистый расчёт на тысячах точек: в потоке.
    pins = await cad_site_pins.active_site_pins(session, project_id=project_id)
    grid_version = reference.number if reference is not None and reference.axes else None
    stack = await asyncio.to_thread(build_stack, built, pins, grid_version)
    for index, floor in zip(stack.kept, stack.real, strict=True):
        derived = floor.floor_height_source == "derived_stack"
        warnings.extend(
            w for w in sources[index][1] if not (derived and w.code == "floor_height_default")
        )
        drift = floor.alignment_scale_permille
        if floor.alignment == "axes" and drift is not None and abs(drift) > b3d.SCALE_WARN_PERMILLE:
            warnings.append(
                CadBuilding3dWarningRead(
                    code="floor_scale_drift",
                    message=f"{floor.label}: расстояния между осями расходятся с эталоном здания "
                    f"на {_drift(drift)} ‰ - проверьте калибровку масштаба листа.",
                )
            )
    for index, keeper in sorted(stack.superseded.items()):
        sheet = sources[index][0]
        service.append(
            _service_sheet(
                sheet,
                "superseded",
                f"{sheet.label}: дубль плана на той же отметке - в здании оставлен лист большей "
                f"площади «{sources[keeper][0].label}».",
            )
        )
    for index in stack.summaries:
        sheet = sources[index][0]
        service.append(
            _service_sheet(
                sheet,
                "summary_unplaced",
                f"{sheet.label}: сводный лист с планами нескольких секций не встал на площадку - "
                "планы на нём разложены по листу, а не по объекту; в 3D объекта не показывается.",
            )
        )
    lost = [g.label for g in stack.groups if g.placement == "none"]
    if len(stack.groups) > 1 and lost:
        warnings.append(
            CadBuilding3dWarningRead(
                code="groups_not_placed",
                message="Не поставлены на объект по осям и ядрам: "
                f"{', '.join(lost)}. В виде «Весь объект» они показаны отдельным блоком.",
            )
        )
    warnings.extend(review_warnings(stack.groups))
    warnings.extend(
        CadBuilding3dWarningRead(
            code="floor_fragment_dropped",
            message=f"{label}: {count} стен вне пятна корпуса (фрагмент плана на том же листе) - "
            "в 3D не показаны.",
        )
        for label, count in stack.fragments
    )
    warnings.extend(
        CadBuilding3dWarningRead(
            code="site_pin_ignored",
            message=f"Ручная привязка корпуса к площадке не применена: {ignored.message}.",
        )
        for ignored in stack.ignored_pins
    )
    if include_walls:
        # Замечания и счётчики - только по этажам, оставшимся в стопке (без дублей `superseded`).
        kept_results = [r for index in stack.kept if (r := built_windows[index]) is not None]
        unknown_wall_floors = 0
        dropped = 0
        for index, floor in zip(stack.kept, stack.real, strict=True):
            before = len(built[index].floor.windows or ())
            if before and not b3d_windows.wall_height_known(floor):
                unknown_wall_floors += 1
            else:
                dropped += before - len(floor.windows or ())
        warnings.extend(
            _window_warnings(
                b3d_windows.summarize(kept_results),
                views_failed=views_failed,
                unknown_wall_floors=unknown_wall_floors,
                dropped=dropped,
                floors=stack.real,
            )
        )
    warnings.extend(missing)
    return CadBuilding3dRead(
        units="mm",
        floors=stack.floors,
        groups=stack.groups,
        warnings=warnings,
        service_sheets=service,
    )
