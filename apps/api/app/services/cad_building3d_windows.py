"""Окна этажей в общем 3D здания (ADR-0048 п. 6): подоконная часть, стекло и перемычка.

Высоты окон листа - тот же общий расчёт, что в 3D этажа и в объёме кладки
(`cad_facade_windows.sheet_window_heights`): принятый вид фасада, ручной ввод листа, вид-кандидат
(`accepted = false`), иначе высоты нет и окно не выдаётся. Окно живёт в этаже в мм системы DXF
листа и вместе с этажом проходит совмещение, поворот и постановку на объект (как стены).

Две стадии: `floor_windows` - до совмещения этажей (высоты от чистого пола листа, абсолютные z,
верх окна не обрезан), `finalize_windows` - после высот по стопке: верх стены этажа известен, окно
обрезается по нему, перемычка получает верх стены (как в 3D этажа). Чистый расчёт без I/O;
виды фасадов проекта грузятся один раз на запрос здания.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.contracts.cad_building3d import CadBuilding3dFloorRead, CadBuilding3dWindowRead
from app.services import cad_building3d as b3d
from app.services import cad_facade_windows as facades

# Контур окна в ответе: открытое кольцо (контур перемычки - четыре точки).
MAX_WINDOW_POINTS = 16
CODE_WITHOUT_HEIGHT = "building_windows_without_height"
CODE_ABOVE_WALL = "building_windows_above_wall"
CODE_UNACCEPTED = "building_windows_unaccepted"
CODE_FAILED = "building_windows_failed"
CODE_NO_CONTOUR = "building_windows_no_contour"
CODE_WALL_HEIGHT_UNKNOWN = "building_windows_wall_height_unknown"
CODE_VIEWS_FAILED = "building_windows_views_failed"
# Верх стены этажа не ниже этого от верха плиты: то же, что `wallHeightMm` в просмотрщике.
MIN_WALL_HEIGHT_MM = 100


@dataclass(frozen=True, slots=True)
class FloorWindows:
    """Окна этажа с высотой, число окон без высоты и замечания сопоставления с фасадами."""

    windows: list[CadBuilding3dWindowRead]
    without_height: int = 0
    issues: tuple[facades.MatchIssue, ...] = ()
    # Окна с высотой, у которых нет пригодного контура проёма (нет `lintel`, вырожденное кольцо).
    no_contour: int = 0
    # Расчёт окон этажа не удался: окон нет, причина - в журнале.
    failed: bool = False


def _axes_of(source: b3d.WindowSource) -> facades.SheetAxes:
    if source.frame_problem is not None:
        return facades.SheetAxes(
            issue=facades.MatchIssue(
                "facade_windows_no_frame",
                f"Окна по фасадам не сопоставлены: {source.frame_problem}",
            )
        )
    if not source.axes.vertical and not source.axes.horizontal:
        return facades.SheetAxes(
            issue=facades.MatchIssue(
                "facade_windows_no_axes",
                "Окна по фасадам не сопоставлены: на плане нет осей "
                f"({source.axes.message or 'нет осей'}).",
            )
        )
    return facades.SheetAxes(source.axes.vertical, source.axes.horizontal)


def _shell(ring: Sequence[Sequence[float]] | None) -> list[list[int]] | None:
    if ring is None:
        return None
    points = b3d._open_ring(ring)
    if not 3 <= len(points) <= MAX_WINDOW_POINTS:
        return None
    return [[b3d._round_mm(x), b3d._round_mm(y)] for x, y in points]


def floor_windows(
    source: b3d.WindowSource, base_z_mm: int, loaded: facades.LoadedViews
) -> FloorWindows:
    """Окна этажа с высотой; верх стекла пока не обрезан по верху стены (`finalize_windows`)."""
    match = facades.sheet_window_heights(
        loaded=loaded,
        openings=source.openings,
        extras=source.extras,
        slab_shell=source.slab_shell,
        axes=_axes_of(source) if loaded.views else None,
        corps=source.corps,
        section=source.section,
        level=source.level,
        manual_sill_mm=source.manual_sill_mm,
        manual_head_mm=source.manual_head_mm,
    )
    lintel_by_id = {item.id: item.lintel for item in source.extras}
    reads: list[CadBuilding3dWindowRead] = []
    without_height = 0
    no_contour = 0
    for opening in source.openings:
        if opening.opening_height_mm is not None:
            continue
        height = match.heights.get(opening.id)
        if height is None:
            without_height += 1
            continue
        shell = _shell(lintel_by_id.get(opening.id))
        if shell is None:
            no_contour += 1
            continue
        glass_bottom = source.opening_floor_z_mm + height.sill_mm
        head = source.opening_floor_z_mm + height.head_mm
        has_sill = height.sill_mm > 0 and glass_bottom > base_z_mm
        reads.append(
            CadBuilding3dWindowRead(
                opening_id=opening.id,
                shell=shell,
                sill_z_bottom_mm=base_z_mm if has_sill else glass_bottom,
                glass_z_bottom_mm=glass_bottom,
                glass_z_top_mm=head,
                lintel_z_top_mm=head,
                accepted=height.accepted,
                source=height.source,
            )
        )
    return FloorWindows(reads, without_height, match.issues, no_contour)


def wall_top_mm(floor: CadBuilding3dFloorRead) -> int:
    """Верх стен этажа, мм: верх плиты плюс высота этажа без плиты (как у просмотрщика)."""
    return floor.base_z_mm + max(
        MIN_WALL_HEIGHT_MM, floor.floor_height_mm - floor.slab_thickness_mm
    )


def wall_height_known(floor: CadBuilding3dFloorRead) -> bool:
    """Верх стены этажа определён: высота этажа и толщина плиты не типовые по умолчанию.

    Высота, выведенная из отметок соседних этажей (`derived_stack`), определена.
    """
    height_known = floor.floor_height_known or floor.floor_height_source == "derived_stack"
    return height_known and floor.slab_thickness_known


def finalize_windows(floor: CadBuilding3dFloorRead) -> CadBuilding3dFloorRead:
    """Окна этажа по верху стены: выше верха - окна нет, верх окна обрезается, перемычка - до верха.

    Окно с верхом не ниже верха стены перемычки не имеет: `lintel_z_top_mm = glass_z_top_mm`.
    Вызывается один раз, когда высота этажа уже определена (после высот по стопке).
    """
    if not floor.windows:
        return floor
    if not wall_height_known(floor):
        # Как 3D этажа: верха стены нет - окна не строятся (типовое значение не из документации).
        return floor.model_copy(update={"windows": []})
    top = wall_top_mm(floor)
    result: list[CadBuilding3dWindowRead] = []
    for window in floor.windows:
        if window.glass_z_bottom_mm >= top:
            continue
        glass_top = min(window.glass_z_top_mm, top)
        lintel_top = top if window.glass_z_top_mm < top else glass_top
        result.append(
            window.model_copy(update={"glass_z_top_mm": glass_top, "lintel_z_top_mm": lintel_top})
        )
    return floor.model_copy(update={"windows": result})


def lift_windows(
    windows: Sequence[CadBuilding3dWindowRead] | None, dz: int
) -> list[CadBuilding3dWindowRead] | None:
    """Окна этажа типового листа на другой отметке: все z сдвигаются на `dz`."""
    if windows is None:
        return None
    return [
        window.model_copy(
            update={
                "sill_z_bottom_mm": window.sill_z_bottom_mm + dz,
                "glass_z_bottom_mm": window.glass_z_bottom_mm + dz,
                "glass_z_top_mm": window.glass_z_top_mm + dz,
                "lintel_z_top_mm": window.lintel_z_top_mm + dz,
            }
        )
        for window in windows
    ]


@dataclass(frozen=True, slots=True)
class WindowNotes:
    """Свод замечаний по окнам всех этажей: код -> (текст, число этажей)."""

    without_height: int
    floors_without_height: int
    issues: dict[str, tuple[str, int]]
    failed: int = 0
    no_contour: int = 0


def summarize(results: Sequence[FloorWindows]) -> WindowNotes:
    """Замечания сопоставления по кодам, не по строке на этаж: число этажей с каждым случаем."""
    counts: Counter[str] = Counter()
    first: dict[str, str] = {}
    for result in results:
        for issue in result.issues:
            first.setdefault(issue.code, issue.message)
        for code in {issue.code for issue in result.issues}:
            counts[code] += 1
    return WindowNotes(
        without_height=sum(r.without_height for r in results),
        floors_without_height=sum(1 for r in results if r.without_height),
        issues={code: (first[code], counts[code]) for code in first},
        failed=sum(1 for r in results if r.failed),
        no_contour=sum(r.no_contour for r in results),
    )
