"""Сборка модели этажа для 3D-вида по walls.json и данным человека (ADR-0039).

Чистые функции без базы и хранилища: на входе разобранные `walls.json` и его дополнение
(`WallsFloorExtras`), параметры конструкций, переопределения высот листа, толщина плиты проекта,
решения по отверстиям и двери-зоны в мм DXF; на выходе призмы в мм системы DXF и высоты с
источником. Фронт геометрию не выводит. Величин, кроме справочной площади плиты и отверстий,
нет: вид в итоги обмера, calc и MEP не входит. Не определено — `None` и предупреждение, не 0.

Высоты (мм): база `b` — верх плиты: `heights.slab_top_elevation_mm` из walls.json v1.9 (отметка
листа АР — чистый пол минус пирог пола), иначе отметка листа (старый файл и ручная отметка этажа
человека — без вычета пирога), иначе 0. Плита — от `b - t` до `b`; стена — от `b` до
`b + (высота этажа - t)` (или своя высота конструкции от человека; у внутриквартирной перегородки
при принятом ответе «Вопросов к документации» - `b +` высота маячного ряда). Проёмы отсчитываются от
чистого пола `f` (= `b` + пирог пола, если база взята из верха плиты, иначе `f = b`): перемычка
над проёмом — от `f + высота проёма` до верха стены; полотно двери — от `f` до
`f + высота проёма`. Высота проёма — зона двери человека, содержащая середину перемычки
(полотна), у разрыва `gap` затем `opening_height_mm` из walls.json, иначе действующая высота
двери листа. У двери без разрыва (`no_data`) перемычки и полотна нет: предупреждение
`door_without_gap` берётся из walls.json.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.contracts.cad_constructions import (
    CadConstructionKind,
    CadConstructionProps,
    CadSheetLevelsRead,
    CadValueSource,
    WallsDocument,
)
from app.contracts.cad_floor3d import (
    CadFloor3dDoorRead,
    CadFloor3dFamily,
    CadFloor3dHoleRead,
    CadFloor3dHoleState,
    CadFloor3dLintelRead,
    CadFloor3dRead,
    CadFloor3dSlabRead,
    CadFloor3dWallRead,
    CadFloor3dWarningRead,
    WallsFloorExtras,
)
from app.services import cad_constructions
from app.services.cad_constructions import PartitionContext, ProjectSlab
from app.services.cad_walls_version import walls_outdated

_MM2_IN_M2: Final = 1e6
_KEY_CENTROID_STEP_MM: Final = 10
_KEY_LENGTH: Final = 12
# Допуск: расстояние от середины перемычки до отрезка зоны двери. Человек рисует отрезок двери
# по ширине проёма, а середина перемычки лежит на оси стены; допуск покрывает полтолщины стены.
DOOR_ZONE_TOLERANCE_MM: Final = 300.0
# Код предупреждения cad_walls: дверь без разрыва стены (перемычки и полотна нет).
DOOR_WITHOUT_GAP: Final = "door_without_gap"
# Код предупреждения cad_walls v1.9: плита по стенам, без зон помещений (контур требует проверки).
SLAB_WITHOUT_ZONES: Final = "slab_without_zones"
# Код предупреждения cad_walls v1.12: пролёт остекления без стены-хозяина (окно не построено).
WINDOW_BAY_WITHOUT_HOST: Final = "window_bay_without_host"
# Код предупреждения cad_walls v1.13: в пролёте балконная дверь, окно урезано или снято.
WINDOW_BAY_DOOR_OVERLAP: Final = "window_bay_door_overlap"
_PASSED_WARNING_CODES: Final = frozenset(
    {DOOR_WITHOUT_GAP, SLAB_WITHOUT_ZONES, WINDOW_BAY_WITHOUT_HOST, WINDOW_BAY_DOOR_OVERLAP}
)

Point = tuple[float, float]
Ring = list[list[float]]


@dataclass(frozen=True, slots=True)
class DoorZoneMm:
    """Зона двери человека, переведённая в мм DXF: отрезок и высота проёма."""

    a: Point
    b: Point
    height_mm: int


@dataclass(frozen=True, slots=True)
class DoorZoneNormalized:
    """Зона двери как хранится: две точки в [0, 1] от левого верхнего угла страницы."""

    points: Sequence[Sequence[float]]
    height_mm: int


@dataclass(frozen=True, slots=True)
class RoomZoneNormalized:
    """Зона помещения (квартира, МОП) как хранится: контур в [0, 1] от левого верхнего угла."""

    kind: str
    points: Sequence[Sequence[float]]


@dataclass(frozen=True, slots=True)
class RoomZoneMm:
    """Зона помещения в мм DXF: вход контура плиты скрипта конструкций."""

    kind: str
    shell: list[Point]


# --------------------------------------------------------------------------- геометрия


def ring_centroid(shell: Sequence[Sequence[float]]) -> Point:
    """Центроид многоугольника (по площади); у вырожденного кольца — среднее вершин."""
    n = len(shell)
    twice_area = 0.0
    cx = 0.0
    cy = 0.0
    for i in range(n):
        x0, y0 = shell[i][0], shell[i][1]
        x1, y1 = shell[(i + 1) % n][0], shell[(i + 1) % n][1]
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(twice_area) < 1e-9:
        return (
            math.fsum(p[0] for p in shell) / max(n, 1),
            math.fsum(p[1] for p in shell) / max(n, 1),
        )
    return (cx / (3.0 * twice_area), cy / (3.0 * twice_area))


def hole_key(shell: Sequence[Sequence[float]], area_mm2: float) -> str:
    """Стабильный ключ отверстия: хеш центроида (до 10 мм) и площади (до 0,01 м2), 12 hex.

    Не зависит от порядка отверстий в файле и от повторного расчёта с той же геометрией.
    """
    cx, cy = ring_centroid(shell)
    rx = round(cx / _KEY_CENTROID_STEP_MM) * _KEY_CENTROID_STEP_MM
    ry = round(cy / _KEY_CENTROID_STEP_MM) * _KEY_CENTROID_STEP_MM
    area = round(area_mm2 / _MM2_IN_M2, 2)
    raw = f"{rx}:{ry}:{area:.2f}"
    return hashlib.sha1(raw.encode("ascii"), usedforsecurity=False).hexdigest()[:_KEY_LENGTH]


def _distance_to_segment(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _point_to_mm(
    nx: float,
    ny: float,
    *,
    page_width_pt: float,
    page_height_pt: float,
    origin_pt: Point,
    mm_per_pdf_point: float,
) -> Point:
    """Нормализованная точка ([0, 1] от левого верхнего угла страницы) -> мм DXF по кадру вида.

    Кадр вида: `pt = origin_pt + (x_mm, -y_mm) / mm_per_pdf_point`, где `pt` — отображаемые
    точки PDF от левого верхнего угла. Нормализованная точка -> `pt` умножением на отображаемый
    размер страницы (тем же, что нормализует обмер, ADR-0008); обратно — по формуле кадра.
    """
    pt_x, pt_y = nx * page_width_pt, ny * page_height_pt
    return (
        (pt_x - origin_pt[0]) * mm_per_pdf_point,
        -(pt_y - origin_pt[1]) * mm_per_pdf_point,
    )


def door_zones_to_mm(
    zones: Sequence[DoorZoneNormalized],
    *,
    page_width_pt: float,
    page_height_pt: float,
    origin_pt: Point,
    mm_per_pdf_point: float,
) -> list[DoorZoneMm]:
    """Точки зон двери ([0, 1] от левого верхнего угла страницы) -> мм DXF по кадру вида."""
    result: list[DoorZoneMm] = []
    for zone in zones:
        if len(zone.points) != 2:
            continue
        a, b = (
            _point_to_mm(
                nx,
                ny,
                page_width_pt=page_width_pt,
                page_height_pt=page_height_pt,
                origin_pt=origin_pt,
                mm_per_pdf_point=mm_per_pdf_point,
            )
            for nx, ny in zone.points
        )
        result.append(DoorZoneMm(a, b, zone.height_mm))
    return result


def room_zones_to_mm(
    zones: Sequence[RoomZoneNormalized],
    *,
    page_width_pt: float,
    page_height_pt: float,
    origin_pt: Point,
    mm_per_pdf_point: float,
) -> list[RoomZoneMm]:
    """Контуры зон помещений -> мм DXF по кадру вида (тот же перевод, что у зон двери)."""
    return [
        RoomZoneMm(
            zone.kind,
            [
                _point_to_mm(
                    nx,
                    ny,
                    page_width_pt=page_width_pt,
                    page_height_pt=page_height_pt,
                    origin_pt=origin_pt,
                    mm_per_pdf_point=mm_per_pdf_point,
                )
                for nx, ny in zone.points
            ],
        )
        for zone in zones
        if len(zone.points) >= 3
    ]


def _zone_height_at(point: Point, zones: Sequence[DoorZoneMm]) -> int | None:
    """Высота ближайшей зоны двери, отрезок которой лежит не дальше допуска от точки."""
    best: tuple[float, int] | None = None
    for zone in zones:
        distance = _distance_to_segment(point, zone.a, zone.b)
        if distance <= DOOR_ZONE_TOLERANCE_MM and (best is None or distance < best[0]):
            best = (distance, zone.height_mm)
    return None if best is None else best[1]


# --------------------------------------------------------------------------- сборка


def _family(kind: CadConstructionKind) -> CadFloor3dFamily:
    if kind == "masonry":
        return "masonry"
    if kind == "frame_partition":
        return "frame_partition"
    return "monolith"


def _bbox(rings: Sequence[Sequence[Sequence[float]]]) -> list[float] | None:
    xs = [p[0] for ring in rings for p in ring]
    ys = [p[1] for ring in rings for p in ring]
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def _keyed_holes(
    extras: WallsFloorExtras, decisions: Mapping[str, bool]
) -> list[CadFloor3dHoleRead]:
    """Отверстия плиты с ключом геометрии; совпавший ключ получает числовой суффикс."""
    seen: dict[str, int] = {}
    holes: list[CadFloor3dHoleRead] = []
    for hole in extras.slab_holes:
        base = hole_key(hole.shell, hole.area_mm2)
        seen[base] = seen.get(base, 0) + 1
        key = base if seen[base] == 1 else f"{base}-{seen[base]}"
        decision = decisions.get(key)
        # Без решения человека отверстие включено; «Не отверстие» - решение enabled=false.
        state: CadFloor3dHoleState = "disabled" if decision is False else "enabled"
        holes.append(
            CadFloor3dHoleRead(
                key=key,
                shell=hole.shell,
                area_m2=round(hole.area_mm2 / _MM2_IN_M2, 3),
                state=state,
            )
        )
    return holes


def hole_keys(extras: WallsFloorExtras) -> list[str]:
    """Ключи отверстий файла в порядке файла (для проверки адреса решения)."""
    return [hole.key for hole in _keyed_holes(extras, {})]


def build_floor3d(
    document: WallsDocument,
    extras: WallsFloorExtras,
    *,
    props_by_key: Mapping[str, tuple[CadConstructionProps, bool]],
    overrides: CadSheetLevelsRead,
    project_slab: ProjectSlab | None,
    hole_decisions: Mapping[str, bool],
    door_zones: Sequence[DoorZoneMm],
    extra_warnings: Sequence[CadFloor3dWarningRead] = (),
    current_generator: str | None = None,
    partition: PartitionContext | None = None,
) -> CadFloor3dRead:
    """Модель этажа: плита с отверстиями, стены, перемычки, высоты с источниками, предупреждения.

    `partition` - зоны помещений листа и принятая высота маячного ряда; без него перегородки
    строятся на высоту стены листа.
    """
    levels = cad_constructions.effective_levels(document.heights, overrides, project_slab)
    warnings: list[CadFloor3dWarningRead] = list(extra_warnings)
    warnings.extend(
        CadFloor3dWarningRead(code=w.code, message=w.message)
        for w in document.checks.warnings
        if w.code in _PASSED_WARNING_CODES
    )
    outdated = walls_outdated(document.generator, extras.has_slab_key, current_generator)
    if outdated:
        warnings.append(
            CadFloor3dWarningRead(
                code="walls_outdated",
                message=(
                    "Результат конструкций построен прежней версией генератора или без плиты, "
                    "отверстий и перемычек. Пересчитайте конструкции."
                ),
            )
        )

    base = levels.base_z_mm
    opening_floor = levels.opening_floor_z_mm
    thickness = levels.slab_thickness.value_mm
    wall_height = levels.wall_height_mm

    slab: CadFloor3dSlabRead | None = None
    if extras.slab is not None:
        if thickness is None:
            warnings.append(
                CadFloor3dWarningRead(
                    code="slab_thickness_missing",
                    message="Толщина плиты не определена: низ плиты не построен.",
                )
            )
        slab = CadFloor3dSlabRead(
            shell=extras.slab.shell,
            z_bottom_mm=None if thickness is None else base - thickness,
            z_top_mm=base,
            area_m2=round(extras.slab.area_mm2 / _MM2_IN_M2, 3),
        )
    elif not outdated:
        warnings.append(
            CadFloor3dWarningRead(
                code="slab_missing", message="Контур плиты не построен: в результате нет стен."
            )
        )

    classes = cad_constructions.classify_partitions(
        document.constructions, props_by_key, () if partition is None else partition.zones
    )
    document = cad_constructions.rehost_openings_to_full_height(document, classes, props_by_key)
    candidates = cad_constructions.partition_candidate_ids(classes)
    partition_heights = cad_constructions.partition_heights_by_id(classes, partition)
    warnings.extend(
        CadFloor3dWarningRead(code=code, message=message)
        for code, message in cad_constructions.partition_warnings(
            partition, candidates, props_by_key
        )
    )

    walls: list[CadFloor3dWallRead] = []
    top_by_id: dict[str, int | None] = {}
    # Стены с маячным рядом: проёмы в них не считаются, до верха стены они «достают» всегда.
    beacon_row_ids: set[str] = set()
    wall_height_missing = False
    # Каркасные перегородки ГКЛ лежат отдельно от конструкций; в 3D строятся так же, как стены.
    wall_items = [*document.constructions, *document.frame_partitions]
    for item in wall_items:
        props = props_by_key.get(item.id, (CadConstructionProps(), False))[0]
        chosen = cad_constructions.construction_height(
            props, levels, partition_heights.get(item.id)
        )
        if chosen.basis == "apartment_partition":
            beacon_row_ids.add(item.id)
        z_top = None if chosen.height_mm is None else base + chosen.height_mm
        wall_height_missing = wall_height_missing or z_top is None
        top_by_id[item.id] = z_top
        walls.append(
            CadFloor3dWallRead(
                construction_key=item.id,
                kind=item.kind,
                family=_family(item.kind),
                thickness_nominal_mm=item.thickness_nominal_mm,
                shell=item.polygon.shell,
                holes=item.polygon.holes,
                z_bottom_mm=base,
                z_top_mm=z_top,
                height_basis=chosen.basis,
            )
        )

    lintels: list[CadFloor3dLintelRead] = []
    doors: list[CadFloor3dDoorRead] = []
    lintel_by_id = {o.id: o.lintel for o in extras.openings}
    leaf_by_id = {o.id: o.leaf for o in extras.openings}
    lintel_material_by_id = {o.id: o.lintel_material for o in extras.openings}
    sheet_top = None if wall_height is None else base + wall_height
    door_height_missing = False
    no_contour = 0
    no_lintel_room = 0
    windows_without_height = 0
    for opening in document.openings:
        if outdated:
            break
        if opening.kind == "window" and opening.opening_height_mm is None:
            # окно без высоты: проём не строится, стена сплошная; высоту двери не подставляем
            windows_without_height += 1
            continue
        shell = lintel_by_id.get(opening.id)
        if shell is None:
            # дверь без разрыва: причина — предупреждение `door_without_gap` из walls.json
            if not (opening.kind == "door" and opening.status == "no_data"):
                no_contour += 1
            continue
        top = top_by_id.get(opening.host_id, sheet_top) if opening.host_id else sheet_top
        if top is None:
            wall_height_missing = True
            continue
        # зона двери человека - только для дверей и разрывов; высота окна - из walls.json
        zone_height = (
            None if opening.kind == "window" else _zone_height_at(ring_centroid(shell), door_zones)
        )
        height_mm: int | None
        source: CadValueSource | None
        if zone_height is not None:
            height_mm, source = zone_height, "manual"
        elif opening.kind != "door" and opening.opening_height_mm is not None:
            height_mm = opening.opening_height_mm
            source = cad_constructions.source_of(opening.opening_height_status or "assumption")
        else:
            height_mm, source = levels.door_height.value_mm, levels.door_height.source
        if height_mm is None:
            door_height_missing = True
            continue
        z_bottom = opening_floor + height_mm
        # проём до верха стены и выше: перемычки нет, полотно — до верха стены
        reaches_top = z_bottom >= top
        leaf = leaf_by_id.get(opening.id)
        if leaf is not None and top > opening_floor:
            doors.append(
                CadFloor3dDoorRead(
                    opening_id=opening.id,
                    host_id=opening.host_id,
                    shell=leaf,
                    z_bottom_mm=opening_floor,
                    z_top_mm=min(z_bottom, top),
                    door_height_mm=height_mm,
                    door_height_source=source,
                )
            )
        if reaches_top:
            if opening.host_id not in beacon_row_ids:
                no_lintel_room += 1
            continue
        lintels.append(
            CadFloor3dLintelRead(
                opening_id=opening.id,
                host_id=opening.host_id,
                kind=opening.kind,
                shell=shell,
                z_bottom_mm=z_bottom,
                z_top_mm=top,
                door_height_mm=height_mm,
                door_height_source=source,
                material=lintel_material_by_id.get(opening.id),
            )
        )

    if wall_height_missing:
        warnings.append(
            CadFloor3dWarningRead(
                code="wall_height_missing",
                message="Высота этажа не определена: высота стен и перемычек не построена.",
            )
        )
    if windows_without_height:
        warnings.append(
            CadFloor3dWarningRead(
                code=cad_constructions.WINDOW_HEIGHT_UNKNOWN,
                message="Высота окна неизвестна: окна не построены, стена сплошная.",
            )
        )
    if door_height_missing:
        warnings.append(
            CadFloor3dWarningRead(
                code="door_height_missing",
                message="Высота двери не определена: перемычки без высоты не построены.",
            )
        )
    if no_lintel_room:
        warnings.append(
            CadFloor3dWarningRead(
                code="opening_reaches_wall_top",
                message=(
                    f"Проёмов до верха стены и выше (перемычки нет, полотно обрезано по стене): "
                    f"{no_lintel_room}."
                ),
            )
        )
    if no_contour:
        warnings.append(
            CadFloor3dWarningRead(
                code="lintel_missing",
                message=f"Проёмов без контура перемычки (нет направления): {no_contour}.",
            )
        )

    rings: list[Sequence[Sequence[float]]] = [item.polygon.shell for item in wall_items]
    if extras.slab is not None:
        rings.append(extras.slab.shell)
    return CadFloor3dRead(
        units="mm",
        generator=document.generator,
        heights=cad_constructions.heights_read(
            document.heights, levels, None if partition is None else partition.height
        ),
        title=document.heights.title,
        base_z_mm=base,
        elevation_known=levels.elevation_mm is not None,
        slab=slab,
        slab_holes=_keyed_holes(extras, hole_decisions),
        walls=walls,
        lintels=lintels,
        doors=doors,
        bbox=_bbox(rings),
        warnings=warnings,
    )
