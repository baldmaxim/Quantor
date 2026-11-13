"""Расчёт величин конструкций по walls.json и данным человека (ADR-0038 п. 3).

Чистые функции без базы и хранилища: на входе разобранный `walls.json`, параметры конструкций и
переопределения высот листа, на выходе конструкции с величинами и итоги по группам. Модель нигде
не участвует; стоимости нет. Не определено — `None`, а не 0: «не определено» не превращается в
молчаливое умолчание.

Формулы (мм, результат в м, м2, м3):

- толщина `t` = переопределение человека, иначе номинал скрипта; номинала нет — `thickness_check`;
- высота `H` = переопределение человека, иначе высота маячного ряда (внутриквартирная
  перегородка, ответ принят в «Вопросах к документации»), иначе (высота этажа - толщина плиты);
  стены санузлов и обстройка шахт маячным рядом не ограничены: у них высота стены листа;
  высота этажа и толщина плиты — переопределение листа, иначе значение из walls.json; нет
  высоты — `height_missing`;
- материал: ввод человека (`props.material`), иначе подсказка из условных обозначений листа, если
  она однозначна (`matched`); props автоматически не заполняются; нет материала при подсказке
  `not_in_legend` или `conflict` — предупреждение `material_check` (на статус не влияет);
- длина = длина оси из walls.json (площадь в плане / измеренная толщина);
- объём = длина x `t` x `H` (по номиналу: штриховка бывает шире номинала) плюс по
  каждой двери конструкции ширина x `t` x max(0, `H` - высота двери): дверь стоит в разрыве стены
  на плане, и надпроёмная часть в площадь плана не попадает. Монолитная перемычка над дверью
  в кладке или перегородке в объём хозяина не идёт: она отдельная группа итогов (`lintel`);
  дверь без разрыва в стене (`no_data`) надпроёмной части не даёт;
- площадь стены = длина x `H` плюс по каждой двери ширина x max(0, `H` - высота двери): это
  поверхность под отделку, монолитная перемычка в ней остаётся;
- монолитные перемычки (`lintel_material == monolith`) над проёмами (двери не `no_data` и разрывы
  `gap`) стен-хозяев не из монолита: объём = площадь контура `lintel` в плане x max(0, высота
  стены хозяина - высота двери); у монолитного хозяина перемычка уже в его объёме; нет высоты,
  толщины или хозяина — в итог не идёт, считается в `lintels_without_volume`;
- каркасная перегородка ГКЛ (`frame_partition`) меряется площадью: длина и площадь стены как у
  кладки, объём не определён (`None`);
- разрыв (`gap`) с высотой проёма из walls.json v1.9 (`opening_height_mm`) даёт надпроёмную
  часть как дверь: ширина x `t` x max(0, `H` - высота проёма); перемычка на не-монолитном
  хозяине в объём не идёт; происхождение высоты - `sources.gap_opening_height`. Разрыв без высоты
  (старый файл) в объём и площадь не входит и даёт предупреждение `opening_no_data` у несущей
  конструкции и счёт в `unaccounted_gap_openings`;
- окно (`window`, cad_walls v1.12): высота по плану не определяется. Окно без высоты не вычитается
  из кладки, надоконная часть и перемычка не строятся (допущений нет): счёт в
  `unaccounted_gap_openings`, предупреждение листа `window_height_unknown`. Окно с высотой
  (`opening_height_mm`) считается как разрыв с известной высотой;
- плита перекрытия (`floor_slab`, одна на лист): площадь нетто = контур минус включённые
  отверстия; толщина = переопределение человека, иначе толщина плиты листа; объём = нетто x
  толщина; нет толщины — `thickness_check`, в итоги не входит.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from app.contracts.cad_constructions import (
    CadComputedSourcesRead,
    CadComputedStatus,
    CadConstructionComputedRead,
    CadConstructionGroupRead,
    CadConstructionKind,
    CadConstructionMaterialRead,
    CadConstructionProps,
    CadConstructionRead,
    CadConstructionsSummaryRead,
    CadConstructionWarning,
    CadGroupElement,
    CadHeightBasis,
    CadHeightsRead,
    CadLevelValueRead,
    CadMaterial,
    CadOpeningRead,
    CadPartitionHeightRead,
    CadSheetLevelsRead,
    CadValueSource,
    WallsConstruction,
    WallsDocument,
    WallsHeights,
    WallsOpening,
    WallsPolygon,
)

KIND_ORDER: Final[tuple[CadConstructionKind, ...]] = (
    "masonry",
    "monolith_wall",
    "monolith_pylon",
    "monolith_column",
    "frame_partition",
    "floor_slab",
)

_MM2_IN_M2: Final = 1e6
_MM3_IN_M3: Final = 1e9

# Материал монолитной перемычки в итогах: монолит у перемычки определяет движок (`monolith`).
LINTEL_MONOLITH: Final = "monolith"
LINTEL_GROUP_KIND: Final[CadConstructionKind] = "monolith_wall"
LINTEL_GROUP_MATERIAL: Final[CadMaterial] = "monolith_concrete"


def source_of(raw: str) -> CadValueSource | None:
    """Статус из walls.json -> происхождение величины; `missing` и неизвестное — не определено."""
    match raw:
        case "observed":
            return "observed"
        case "derived":
            return "derived"
        case "assumption" | "assumed":
            return "assumption"
        case "manual" | "operator":
            return "manual"
        case "missing" | "":
            return None
    return "derived"


@dataclass(frozen=True, slots=True)
class LevelValue:
    value_mm: int | None
    source: CadValueSource | None
    default_mm: int | None

    def read(self) -> CadLevelValueRead:
        return CadLevelValueRead(
            value_mm=self.value_mm, source=self.source, default_mm=self.default_mm
        )


@dataclass(frozen=True, slots=True)
class EffectiveLevels:
    """Высоты листа после переопределений человека."""

    floor_height: LevelValue
    slab_thickness: LevelValue
    door_height: LevelValue
    wall_height_mm: int | None
    wall_height_source: CadValueSource | None
    elevation_mm: int | None = None
    elevation_source: CadValueSource | None = None
    # Лист разреза, если толщина плиты взята из уровня проекта.
    slab_sheet_ref: str | None = None
    # Верх плиты из walls.json v1.9 (отметка листа - пирог пола); при ручной отметке - `None`.
    slab_top_mm: int | None = None
    # Пирог пола (чистый пол - верх плиты) из walls.json; нужен, пока база взята из `slab_top_mm`.
    floor_finish_mm: int | None = None

    @property
    def base_z_mm(self) -> int:
        """База z этажа (верх плиты): верх плиты из walls.json, иначе отметка листа, иначе 0.

        Ручная отметка этажа - без вычета пирога (как отметка верха плиты, что и было прежде).
        """
        if self.slab_top_mm is not None:
            return self.slab_top_mm
        return self.elevation_mm if self.elevation_mm is not None else 0

    @property
    def opening_floor_z_mm(self) -> int:
        """Чистый пол этажа - отсчёт низа проёмов и высоты проёма.

        База взята из верха плиты - прибавляем пирог пола (по умолчанию возвращаемся к отметке
        листа); иначе база и есть отметка.
        """
        if self.slab_top_mm is None:
            return self.base_z_mm
        if self.floor_finish_mm is not None:
            return self.slab_top_mm + self.floor_finish_mm
        return self.elevation_mm if self.elevation_mm is not None else self.slab_top_mm


@dataclass(frozen=True, slots=True)
class ProjectSlab:
    """Толщина плиты проекта из разрезов, введённая человеком (ADR-0039 п. 4)."""

    thickness_mm: int
    sheet_ref: str | None


def _level(default: int | None, default_source: str, override: int | None) -> LevelValue:
    if override is not None:
        return LevelValue(override, "manual", default)
    return LevelValue(default, source_of(default_source) if default is not None else None, default)


def effective_levels(
    heights: WallsHeights,
    overrides: CadSheetLevelsRead,
    project_slab: ProjectSlab | None = None,
) -> EffectiveLevels:
    """Действующие высоты листа.

    Толщина плиты: переопределение листа, затем уровень проекта (ввод человека), затем walls.json.
    Отметка этажа: переопределение листа, затем walls.json. Верх плиты (`slab_top_mm`) берётся из
    walls.json v1.9 только без ручной отметки: отметку человека не поправляем на пирог пола.
    """
    floor = _level(heights.floor_height_mm, heights.height_status, overrides.floor_height_mm)
    slab_ref: str | None = None
    if overrides.slab_thickness_mm is None and project_slab is not None:
        slab = LevelValue(project_slab.thickness_mm, "manual", heights.slab_thickness_mm)
        slab_ref = project_slab.sheet_ref
    else:
        slab = _level(heights.slab_thickness_mm, heights.slab_status, overrides.slab_thickness_mm)
    elevation: int | None
    elevation_source: CadValueSource | None
    slab_top: int | None = None
    if overrides.floor_elevation_mm is not None:
        elevation, elevation_source = overrides.floor_elevation_mm, "manual"
    else:
        elevation = heights.floor_elevation_mm
        slab_top = heights.slab_top_elevation_mm if elevation is not None else None
        elevation_source = source_of(heights.elevation_status) if elevation is not None else None
    door = _level(heights.door_height_mm, heights.door_height_status, overrides.door_height_mm)
    wall: int | None = None
    wall_source: CadValueSource | None = None
    if floor.value_mm is not None and slab.value_mm is not None:
        candidate = floor.value_mm - slab.value_mm
        if candidate > 0:
            wall = candidate
            wall_source = "manual" if floor.source == "manual" else "derived"
    return EffectiveLevels(
        floor,
        slab,
        door,
        wall,
        wall_source,
        elevation,
        elevation_source,
        slab_ref,
        slab_top_mm=slab_top,
        floor_finish_mm=heights.floor_finish_mm,
    )


def heights_read(
    heights: WallsHeights,
    levels: EffectiveLevels,
    partition_height: PartitionHeight | None = None,
) -> CadHeightsRead:
    return CadHeightsRead(
        floor_elevation_mm=levels.elevation_mm,
        floor_elevation_source=levels.elevation_source,
        floor_height=levels.floor_height.read(),
        slab_thickness=levels.slab_thickness.read(),
        door_height=levels.door_height.read(),
        slab_thickness_sheet_ref=levels.slab_sheet_ref,
        wall_height_mm=levels.wall_height_mm,
        wall_height_source=levels.wall_height_source,
        evidence=heights.evidence,
        message=heights.message,
        apartment_partition_height=None if partition_height is None else partition_height.read(),
    )


def _is_monolith_kind(kind: CadConstructionKind) -> bool:
    return kind.startswith("monolith")


def _ring_area_mm2(shell: list[list[float]]) -> float:
    """Площадь многоугольника по формуле шнуровки, мм2."""
    n = len(shell)
    twice = math.fsum(
        shell[i][0] * shell[(i + 1) % n][1] - shell[(i + 1) % n][0] * shell[i][1] for i in range(n)
    )
    return abs(twice) / 2.0


def is_monolith_lintel(opening: WallsOpening) -> bool:
    """Над проёмом монолитная перемычка с контуром в плане."""
    return (
        opening.lintel_material == LINTEL_MONOLITH
        and opening.lintel is not None
        and len(opening.lintel) >= 3
    )


def effective_material(
    construction: WallsConstruction, props: CadConstructionProps
) -> CadConstructionMaterialRead:
    """Материал: ввод человека, иначе однозначная подсказка из условных обозначений (ADR-0040)."""
    hint = construction.material_hint
    status = None if hint is None else hint.status
    if props.material is not None:
        return CadConstructionMaterialRead(
            value=props.material, source="manual", hint_status=status, evidence=[]
        )
    if hint is not None and hint.status == "matched" and hint.value is not None:
        return CadConstructionMaterialRead(
            value=hint.value, source="document", hint_status=status, evidence=hint.evidence
        )
    return CadConstructionMaterialRead(
        value=None, source=None, hint_status=status, evidence=[] if hint is None else hint.evidence
    )


# --------------------------------------------------------------------------- маячный ряд

# Внутриквартирная перегородка: тонкая кладка между помещениями одной квартиры. Её выкладывает
# подрядчик только «маячным рядом» (ПЗ АР), на всю высоту её возводит собственник.
PARTITION_MAX_THICKNESS_MM: Final = 100.0
# Зона «касается» конструкции, если расстояние между контурами не больше этого значения: контуры
# зон идут по внутренним граням стен, перегородка до них не доходит на толщину отделки.
PARTITION_ZONE_REACH_MM: Final = 150.0
# Назначение, заданное человеком, при котором конструкция - не внутриквартирная перегородка.
_NOT_PARTITION_PURPOSES: Final = frozenset({"external", "inter_apartment", "mop", "shaft"})
APARTMENT_ROOM_KIND: Final = "room_apartment"
# Санитарные («мокрые») типы помещений квартиры: перегородка, касающаяся такой зоны, - стена
# санузла из ПГП 80 (ПЗ АР), её возводят на полную высоту, а не маячным рядом.
WET_ROOM_TYPES: Final = frozenset({"bath", "wc"})
# Пробы сторон стены: доли длины каждой длинной грани контура; грань короче порога пробами не
# проверяется (торец и косой срез). Сторона без зон - если большинство проб вне всех зон.
SIDE_PROBE_FRACTIONS: Final = (0.25, 0.5, 0.75)
SIDE_MIN_EDGE_MM: Final = 300.0
# Доля длины граней контура без зон, с которой стена - обстройка шахты. Решает длина, а не
# наличие одной грани без зон: короткая грань-ниша у длинной перегородки шахтой её не делает.
SHAFT_EMPTY_LENGTH_SHARE: Final = 0.5

WARNING_PARTITION_HEIGHT_UNKNOWN: Final = "apartment_partition_height_unknown"
WARNING_APARTMENT_ZONES_MISSING: Final = "apartment_zones_missing"
MESSAGE_PARTITION_HEIGHT_UNKNOWN: Final = (
    "Высота маячного ряда внутриквартирных перегородок не подтверждена в «Вопросах к "
    "документации»: перегородки посчитаны на высоту этажа"
)
MESSAGE_APARTMENT_ZONES_MISSING: Final = (
    "На листе нет зон квартир: внутриквартирные перегородки не определены, высота маячного ряда "
    "к ним не применена"
)


@dataclass(frozen=True, slots=True)
class PartitionZone:
    """Зона помещения (квартира или МОП) в мм DXF листа: контур и номер квартиры."""

    kind: str
    apartment_no: str | None
    shell: list[list[float]]
    # Действующий тип помещения (`lift_hall`, `bath`, ...); нужен распознаванию лифтовых дверей и
    # стен санузлов.
    room_type: str | None = None


@dataclass(frozen=True, slots=True)
class PartitionHeight:
    """Принятая высота маячного ряда: ответ «Вопросов к документации» и его происхождение."""

    height_mm: int
    # observed - ответ из документа; manual - значение ввёл человек.
    source: CadValueSource
    answer_id: uuid.UUID
    file_name: str | None = None
    page_index: int | None = None
    quote: str | None = None

    def read(self) -> CadPartitionHeightRead:
        return CadPartitionHeightRead(
            height_mm=self.height_mm,
            source=self.source,
            answer_id=self.answer_id,
            file_name=self.file_name,
            page_index=self.page_index,
            quote=self.quote,
        )


@dataclass(frozen=True, slots=True)
class PartitionFullHeight:
    """Перегородка на полную высоту стены листа с названной причиной (не маячный ряд)."""

    basis: CadHeightBasis


@dataclass(frozen=True, slots=True)
class PartitionContext:
    """Вход классификации перегородок листа: зоны помещений в мм листа и принятый ответ."""

    zones: Sequence[PartitionZone] = ()
    height: PartitionHeight | None = None
    # Принятая высота проёма двери шахты лифта (LIFT_DOOR_HEIGHT); применяет `cad_lift_openings`.
    lift_door_height: PartitionHeight | None = None


@dataclass(frozen=True, slots=True)
class ConstructionHeight:
    """Высота конструкции с происхождением и основанием."""

    height_mm: int | None
    source: CadValueSource | None
    basis: CadHeightBasis


def construction_height(
    props: CadConstructionProps,
    levels: EffectiveLevels,
    partition_height: PartitionHeight | PartitionFullHeight | None = None,
) -> ConstructionHeight:
    """Высота конструкции: ввод человека, затем маячный ряд, затем высота стены листа.

    `partition_height` передаётся только внутриквартирной перегородке при принятом ответе;
    `PartitionFullHeight` (стена санузла, обстройка шахты) даёт высоту стены листа с основанием
    этого правила. Общая функция расчёта, 3D этажа и перемычек.
    """
    if props.height_override_mm is not None:
        return ConstructionHeight(props.height_override_mm, "manual", "manual")
    if isinstance(partition_height, PartitionFullHeight):
        return ConstructionHeight(
            levels.wall_height_mm, levels.wall_height_source, partition_height.basis
        )
    if partition_height is not None:
        return ConstructionHeight(
            partition_height.height_mm, partition_height.source, "apartment_partition"
        )
    return ConstructionHeight(levels.wall_height_mm, levels.wall_height_source, "sheet")


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _point_segment_distance(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def _segments_distance(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], d: tuple[float, float]
) -> float:
    if _cross(a, b, c) * _cross(a, b, d) < 0 and _cross(c, d, a) * _cross(c, d, b) < 0:
        return 0.0  # отрезки пересекаются
    return min(
        _point_segment_distance(a, c, d),
        _point_segment_distance(b, c, d),
        _point_segment_distance(c, a, b),
        _point_segment_distance(d, a, b),
    )


def _rings_within(a: list[list[float]], b: list[list[float]], reach: float) -> bool:
    """Расстояние между многоугольниками не больше `reach` (ноль, если они пересекаются)."""
    if len(a) < 3 or len(b) < 3:
        return False
    if _in_ring((a[0][0], a[0][1]), b) or _in_ring((b[0][0], b[0][1]), a):
        return True  # один внутри другого
    for i in range(len(a)):
        p0, p1 = (a[i][0], a[i][1]), (a[(i + 1) % len(a)][0], a[(i + 1) % len(a)][1])
        lo_x, hi_x = min(p0[0], p1[0]) - reach, max(p0[0], p1[0]) + reach
        lo_y, hi_y = min(p0[1], p1[1]) - reach, max(p0[1], p1[1]) + reach
        for j in range(len(b)):
            q0, q1 = (b[j][0], b[j][1]), (b[(j + 1) % len(b)][0], b[(j + 1) % len(b)][1])
            if (
                max(q0[0], q1[0]) < lo_x
                or min(q0[0], q1[0]) > hi_x
                or max(q0[1], q1[1]) < lo_y
                or min(q0[1], q1[1]) > hi_y
            ):
                continue
            if _segments_distance(p0, p1, q0, q1) <= reach:
                return True
    return False


def _touched_zones(shell: list[list[float]], zones: Sequence[PartitionZone]) -> list[PartitionZone]:
    """Зоны, до контура которых от контура конструкции не дальше `PARTITION_ZONE_REACH_MM`."""
    if len(shell) < 3:
        return []
    box = _bbox(shell)
    reach = PARTITION_ZONE_REACH_MM
    touched: list[PartitionZone] = []
    for zone in zones:
        if len(zone.shell) < 3:
            continue
        zone_box = _bbox(zone.shell)
        if (
            zone_box[2] < box[0] - reach
            or zone_box[0] > box[2] + reach
            or zone_box[3] < box[1] - reach
            or zone_box[1] > box[3] + reach
        ):
            continue
        if _rings_within(shell, zone.shell, reach):
            touched.append(zone)
    return touched


def _point_in_any_zone(point: tuple[float, float], zones: Sequence[PartitionZone]) -> bool:
    return any(len(zone.shell) >= 3 and _in_ring(point, zone.shell) for zone in zones)


def _wall_side_lengths(
    shell: list[list[float]], zones: Sequence[PartitionZone]
) -> tuple[float, float]:
    """Суммарная длина граней контура с зоной и без зон: `(с_зоной_мм, без_зон_мм)`.

    Учитываются длинные грани (не короче `SIDE_MIN_EDGE_MM`); пробы лежат на 150 мм от грани
    наружу, по 25/50/75 % её длины. Грань «без зон» - большинство проб вне всех зон помещений.
    """
    with_zone = 0.0
    without_zone = 0.0
    n = len(shell)
    for i in range(n):
        ax, ay = shell[i][0], shell[i][1]
        bx, by = shell[(i + 1) % n][0], shell[(i + 1) % n][1]
        length = math.hypot(bx - ax, by - ay)
        if length < SIDE_MIN_EDGE_MM:
            continue
        nx, ny = -(by - ay) / length, (bx - ax) / length
        mid = ((ax + bx) / 2, (ay + by) / 2)
        if _in_ring((mid[0] + nx, mid[1] + ny), shell):
            nx, ny = -nx, -ny  # нормаль смотрит внутрь контура - разворачиваем наружу
        probes = [
            (
                ax + (bx - ax) * fraction + nx * PARTITION_ZONE_REACH_MM,
                ay + (by - ay) * fraction + ny * PARTITION_ZONE_REACH_MM,
            )
            for fraction in SIDE_PROBE_FRACTIONS
        ]
        empty = sum(1 for probe in probes if not _point_in_any_zone(probe, zones))
        if empty * 2 > len(probes):
            without_zone += length
        else:
            with_zone += length
    return with_zone, without_zone


def classify_partition(
    construction: WallsConstruction,
    props: CadConstructionProps,
    zones: Sequence[PartitionZone],
) -> CadHeightBasis | None:
    """Класс внутриквартирной перегородки или `None`, если конструкция - не она.

    Кладка (не монолит и не каркасная перегородка) номинальной толщины не более 100 мм; все
    помещения, которых касается её контур (с запасом 150 мм), - квартира с одним и тем же
    непустым номером. Назначение, заданное человеком (наружная, межквартирная, МОП, шахта),
    правило отменяет; «внутренняя» его не отменяет. Нет зон - не перегородка. Класс:

    - `bathroom_wall` - касается зоны санузла или ванной (ПГП 80): полная высота стены листа;
    - `shaft_enclosure` - грани контура без зон составляют не менее `SHAFT_EMPTY_LENGTH_SHARE`
      суммарной длины граней, и есть грани с зоной квартиры (шахта): полная высота; стена, у
      которой все грани без зон, - не перегородка;
    - `apartment_partition` - остальные: маячный ряд.
    """
    if construction.kind != "masonry":
        return None
    nominal = construction.thickness_nominal_mm
    if nominal is None or nominal > PARTITION_MAX_THICKNESS_MM:
        return None
    if props.purpose in _NOT_PARTITION_PURPOSES:
        return None
    touched = _touched_zones(construction.polygon.shell, zones)
    if not touched or any(zone.kind != APARTMENT_ROOM_KIND for zone in touched):
        return None
    numbers = {(zone.apartment_no or "").strip() for zone in touched}
    if len(numbers) != 1 or "" in numbers:
        return None
    with_zone, without_zone = _wall_side_lengths(construction.polygon.shell, zones)
    if without_zone > 0 and with_zone == 0:
        return None  # все грани без зон: не квартирная стена
    if any(zone.room_type in WET_ROOM_TYPES for zone in touched):
        return "bathroom_wall"
    if without_zone >= SHAFT_EMPTY_LENGTH_SHARE * (with_zone + without_zone) > 0:
        return "shaft_enclosure"
    return "apartment_partition"


def is_apartment_partition(
    construction: WallsConstruction,
    props: CadConstructionProps,
    zones: Sequence[PartitionZone],
) -> bool:
    """Перегородка с маячным рядом: `classify_partition` даёт `apartment_partition`."""
    return classify_partition(construction, props, zones) == "apartment_partition"


def classify_partitions(
    items: Sequence[WallsConstruction],
    props_by_key: PropsByKey,
    zones: Sequence[PartitionZone],
) -> dict[str, CadHeightBasis]:
    """Класс перегородок листа по адресам (по геометрии и зонам, без учёта ответа)."""
    if not zones:
        return {}
    result: dict[str, CadHeightBasis] = {}
    for item in items:
        basis = classify_partition(
            item, props_by_key.get(item.id, (CadConstructionProps(), False))[0], zones
        )
        if basis is not None:
            result[item.id] = basis
    return result


def partition_candidate_ids(classes: Mapping[str, CadHeightBasis]) -> frozenset[str]:
    """Адреса перегородок с маячным рядом (без стен санузлов и обстройки шахт)."""
    return frozenset(key for key, basis in classes.items() if basis == "apartment_partition")


def partition_heights_by_id(
    classes: Mapping[str, CadHeightBasis], partition: PartitionContext | None
) -> dict[str, PartitionHeight | PartitionFullHeight]:
    """Высота по адресам перегородок: маячный ряд (ответ принят) или полная с причиной."""
    result: dict[str, PartitionHeight | PartitionFullHeight] = {}
    for key, basis in classes.items():
        if basis == "apartment_partition":
            if partition is not None and partition.height is not None:
                result[key] = partition.height
        else:
            result[key] = PartitionFullHeight(basis)
    return result


def _is_beacon_row_wall(
    key: str,
    partition_heights: Mapping[str, PartitionHeight | PartitionFullHeight],
    props_by_key: PropsByKey,
) -> bool:
    """Стена с действующим маячным рядом: ответ принят, ручной высоты нет."""
    if not isinstance(partition_heights.get(key), PartitionHeight):
        return False
    return props_by_key.get(key, (CadConstructionProps(), False))[0].height_override_mm is None


def marker_row_gap_ids(
    document: WallsDocument,
    partition_heights: Mapping[str, PartitionHeight | PartitionFullHeight],
    props_by_key: PropsByKey,
) -> frozenset[str]:
    """Проёмы маячного ряда: проём, у которого хотя бы один откос - маячный ряд.

    Откос - хозяин или примыкающая конструкция с действующим маячным рядом (ответ принят, ручной
    высоты нет). По проекту такая стена - один блок высотой ряда: перемычка над проёмом
    бесполезна, поэтому в проёме нет ни полотна, ни перемычки, ни надпроёмной части, из кладки он
    не вычитается. Относится к двери, разрыву и окну, в том числе к проёму между рядом и стеной на
    полную высоту. Перемычка остаётся, когда оба откоса - стены на полную высоту или проём в оси
    такой стены (дверь в стене санузла). Дверь без разрыва в контуре (`no_data`) сюда не входит.
    Чистая функция.
    """
    result: set[str] = set()
    for opening in document.openings:
        if opening.kind == "door" and opening.status == "no_data":
            continue
        jambs = set(opening.adjacent_ids)
        if opening.host_id is not None:
            jambs.add(opening.host_id)
        if any(_is_beacon_row_wall(key, partition_heights, props_by_key) for key in jambs):
            result.add(opening.id)
    return frozenset(result)


def partition_warnings(
    partition: PartitionContext | None, candidates: Collection[str], props_by_key: PropsByKey
) -> list[tuple[str, str]]:
    """Предупреждения о маячном ряде: `(код, текст)`; без входа классификации их нет.

    Ответ принят, а зон квартир на листе нет - классифицировать нельзя. Ответа нет, а
    перегородки-кандидаты (без ручной высоты) есть - они посчитаны на высоту этажа.
    """
    if partition is None:
        return []
    if partition.height is not None:
        if not any(zone.kind == APARTMENT_ROOM_KIND for zone in partition.zones):
            return [(WARNING_APARTMENT_ZONES_MISSING, MESSAGE_APARTMENT_ZONES_MISSING)]
        return []
    pending = [
        key
        for key in candidates
        if props_by_key.get(key, (CadConstructionProps(), False))[0].height_override_mm is None
    ]
    if pending:
        return [(WARNING_PARTITION_HEIGHT_UNKNOWN, MESSAGE_PARTITION_HEIGHT_UNKNOWN)]
    return []


@dataclass(frozen=True, slots=True)
class Computed:
    """Величины конструкции без округления (для итогов) и их представление для ответа."""

    thickness_mm: float | None
    height_mm: int | None
    length_m: float | None
    wall_area_m2: float | None
    volume_m3: float | None
    status: CadComputedStatus
    sources: CadComputedSourcesRead
    warnings: list[CadConstructionWarning] = field(default_factory=list)
    # Площадь плиты нетто, м2; у стен `None`.
    area_m2: float | None = None
    height_basis: CadHeightBasis | None = None

    def read(self) -> CadConstructionComputedRead:
        return CadConstructionComputedRead(
            thickness_mm=self.thickness_mm,
            height_mm=self.height_mm,
            length_m=_round(self.length_m, 3),
            wall_area_m2=_round(self.wall_area_m2, 3),
            volume_m3=_round(self.volume_m3, 4),
            status=self.status,
            sources=self.sources,
            warnings=self.warnings,
            area_m2=_round(self.area_m2, 3),
            height_basis=self.height_basis,
        )


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


WINDOW_HEIGHT_UNKNOWN: Final = "window_height_unknown"
WINDOW_HEIGHT_UNKNOWN_MESSAGE: Final = "Высота окна неизвестна: окна не вычтены из кладки"


def has_opening_height(opening: WallsOpening) -> bool:
    """Разрыв или окно с высотой проёма из walls.json (дверь высоту из файла не берёт)."""
    return opening.kind in ("gap", "window") and opening.opening_height_mm is not None


def windows_without_height(openings: Sequence[WallsOpening]) -> int:
    """Окна без высоты: в объём не входят, надоконная часть не строится."""
    return sum(1 for o in openings if o.kind == "window" and o.opening_height_mm is None)


def _gap_above_mm(opening: WallsOpening, wall_height_mm: int) -> float:
    """Надпроёмная часть разрыва или окна: высота стены минус высота проёма (она задана)."""
    return max(0.0, float(wall_height_mm) - float(opening.opening_height_mm or 0))


# Надёжность происхождения: у разрывов с разным статусом в ответ идёт наименее надёжный.
_SOURCE_RANK: Final[tuple[CadValueSource, ...]] = ("assumption", "derived", "observed", "manual")


def _gap_height_source(gaps: Sequence[WallsOpening]) -> CadValueSource:
    sources = [source_of(o.opening_height_status or "assumption") or "assumption" for o in gaps]
    return min(sources, key=_SOURCE_RANK.index)


def compute_construction(
    construction: WallsConstruction,
    host_openings: list[WallsOpening],
    props: CadConstructionProps,
    levels: EffectiveLevels,
    material: CadConstructionMaterialRead | None = None,
    partition_height: PartitionHeight | PartitionFullHeight | None = None,
) -> Computed:
    """Величины одной конструкции; `host_openings` — проёмы, чья несущая стена — она.

    `material` — действующий материал (по умолчанию из `effective_material`).
    `partition_height` — высота маячного ряда, если это внутриквартирная перегородка и ответ
    принят, либо полная высота с причиной (стена санузла, обстройка шахты); приоритет: ввод
    человека, маячный ряд, высота стены листа.
    """
    if material is None:
        material = effective_material(construction, props)
    thickness: float | None
    thickness_source: CadValueSource | None
    if props.thickness_override_mm is not None:
        thickness, thickness_source = float(props.thickness_override_mm), "manual"
    elif construction.thickness_nominal_mm is not None:
        thickness, thickness_source = construction.thickness_nominal_mm, "derived"
    else:
        thickness, thickness_source = None, None

    chosen = construction_height(props, levels, partition_height)
    height, height_source = chosen.height_mm, chosen.source

    # Дверь без разрыва (`no_data`): полигон стены сплошной, надпроёмной части нет вовсе.
    doors = (
        [o for o in host_openings if o.kind == "door" and o.status != "no_data"]
        if props.count_openings
        else []
    )
    # В объём хозяина не идут монолитные перемычки в кладке и перегородках: у них своя группа.
    host_is_monolith = _is_monolith_kind(construction.kind)
    volume_doors = [o for o in doors if host_is_monolith or not is_monolith_lintel(o)]
    # Разрыв или окно с заданной высотой (v1.9, v1.12): надпроёмная часть считается как у двери;
    # без высоты — нет.
    gaps = [o for o in host_openings if has_opening_height(o)] if props.count_openings else []
    volume_gaps = [o for o in gaps if host_is_monolith or not is_monolith_lintel(o)]
    door_height = levels.door_height.value_mm
    warnings: list[CadConstructionWarning] = []
    if thickness is None:
        warnings.append("thickness_check")
    door_height_missing = bool(doors) and door_height is None
    if height is None or door_height_missing:
        warnings.append("height_missing")
    if any(
        o.opening_height_mm is None if o.kind != "door" else o.status == "no_data"
        for o in host_openings
    ):
        warnings.append("opening_no_data")
    if any(o.kind == "door" and o.status == "estimate" for o in host_openings):
        warnings.append("opening_estimate")
    if material.value is None and material.hint_status in ("not_in_legend", "conflict"):
        warnings.append("material_check")

    status: CadComputedStatus = "ok"
    if thickness is None:
        status = "thickness_check"
    elif height is None or door_height_missing:
        status = "height_missing"

    length_m: float | None = None
    wall_area_m2: float | None = None
    volume_m3: float | None = None
    if thickness is not None:
        # Длина — по оси из скрипта (площадь / измеренная толщина), объём — по номиналу:
        # штриховка бывает шире номинала (отделка, линии), площадь в плане завышает объём.
        length_mm = construction.length_axis_mm
        base_mm3_per_h = length_mm * thickness
        length_m = length_mm / 1000
        if height is not None and not door_height_missing:
            above_h = max(0.0, float(height) - float(door_height or 0))
            volume_above = math.fsum(o.width_mm * thickness * above_h for o in volume_doors)
            area_above = math.fsum(o.width_mm * above_h for o in doors)
            volume_above += math.fsum(
                o.width_mm * thickness * _gap_above_mm(o, height) for o in volume_gaps
            )
            area_above += math.fsum(o.width_mm * _gap_above_mm(o, height) for o in gaps)
            if construction.kind != "frame_partition":
                volume_m3 = (base_mm3_per_h * height + volume_above) / _MM3_IN_M3
            wall_area_m2 = length_m * height / 1000 + area_above / _MM2_IN_M2
    return Computed(
        thickness_mm=thickness,
        height_mm=height,
        length_m=length_m,
        wall_area_m2=wall_area_m2,
        volume_m3=volume_m3,
        status=status,
        sources=CadComputedSourcesRead(
            thickness=thickness_source,
            height=height_source,
            door_height=levels.door_height.source if doors else None,
            gap_opening_height=_gap_height_source(gaps) if gaps else None,
        ),
        warnings=warnings,
        height_basis=chosen.basis,
    )


@dataclass(frozen=True, slots=True)
class SheetResult:
    heights: CadHeightsRead
    constructions: list[CadConstructionRead]
    openings: list[CadOpeningRead]
    totals: list[CadConstructionGroupRead]
    summary: CadConstructionsSummaryRead
    # Предупреждения листа (маячный ряд перегородок, окна без высоты): `(код, текст)`.
    partition_warnings: list[tuple[str, str]] = field(default_factory=list)


PropsByKey = Mapping[str, tuple[CadConstructionProps, bool]]

# Адрес плиты листа в параметрах конструкций (у файла без `id` у плиты — он же).
SLAB_ID: Final = "slab"


@dataclass(frozen=True, slots=True)
class SlabInput:
    """Плита перекрытия листа: контур, площадь и только ВКЛЮЧЁННЫЕ отверстия (shell, area_mm2)."""

    id: str
    shell: list[list[float]]
    area_mm2: float
    holes: list[tuple[list[list[float]], float]] = field(default_factory=list)

    @property
    def net_area_mm2(self) -> float:
        """Площадь нетто: контур минус включённые отверстия, не меньше нуля."""
        return max(0.0, self.area_mm2 - math.fsum(area for _shell, area in self.holes))


def _ring_centroid(shell: list[list[float]]) -> list[float]:
    """Центроид многоугольника по формуле площади; у вырожденного кольца — среднее вершин."""
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
        return [
            math.fsum(p[0] for p in shell) / max(n, 1),
            math.fsum(p[1] for p in shell) / max(n, 1),
        ]
    return [cx / (3.0 * twice_area), cy / (3.0 * twice_area)]


def _bbox(shell: list[list[float]]) -> list[float]:
    xs = [p[0] for p in shell]
    ys = [p[1] for p in shell]
    return [min(xs), min(ys), max(xs), max(ys)] if xs else [0.0, 0.0, 0.0, 0.0]


def _slab_material(props: CadConstructionProps) -> CadConstructionMaterialRead:
    """Материал плиты: только ввод человека; подсказки из условных обозначений у плиты нет."""
    if props.material is not None:
        return CadConstructionMaterialRead(
            value=props.material, source="manual", hint_status=None, evidence=[]
        )
    return CadConstructionMaterialRead(value=None, source=None, hint_status=None, evidence=[])


def compute_slab(slab: SlabInput, props: CadConstructionProps, levels: EffectiveLevels) -> Computed:
    """Величины плиты: площадь нетто и объём = нетто x толщина (мм -> м2, м3)."""
    thickness: float | None
    source: CadValueSource | None
    if props.thickness_override_mm is not None:
        thickness, source = float(props.thickness_override_mm), "manual"
    elif levels.slab_thickness.value_mm is not None:
        thickness, source = float(levels.slab_thickness.value_mm), levels.slab_thickness.source
    else:
        thickness, source = None, None
    net_mm2 = slab.net_area_mm2
    return Computed(
        thickness_mm=thickness,
        height_mm=None,
        length_m=None,
        wall_area_m2=None,
        volume_m3=None if thickness is None else net_mm2 * thickness / _MM3_IN_M3,
        status="ok" if thickness is not None else "thickness_check",
        sources=CadComputedSourcesRead(thickness=source, height=None, door_height=None),
        warnings=[] if thickness is not None else ["thickness_check"],
        area_m2=net_mm2 / _MM2_IN_M2,
    )


def slab_read(
    slab: SlabInput,
    computed: Computed,
    props: CadConstructionProps,
    material: CadConstructionMaterialRead,
    accepted: bool,
) -> CadConstructionRead:
    thickness = computed.thickness_mm
    return CadConstructionRead(
        id=slab.id,
        kind="floor_slab",
        source_layers=[],
        polygon=WallsPolygon(shell=slab.shell, holes=[shell for shell, _area in slab.holes]),
        centroid=_ring_centroid(slab.shell),
        bbox=_bbox(slab.shell),
        area_plan_m2=round(slab.net_area_mm2 / _MM2_IN_M2, 4),
        thickness_measured_mm=thickness if thickness is not None else 0.0,
        thickness_nominal_mm=thickness,
        thickness_status="matched" if thickness is not None else "check",
        computed=computed.read(),
        props=props,
        material=material,
        accepted=accepted,
    )


@dataclass(frozen=True, slots=True)
class LintelGroup:
    """Монолитные перемычки одной толщины хозяина: ширины проёмов и объёмы, мм и м3."""

    widths_mm: list[float] = field(default_factory=list)
    volumes_m3: list[float] = field(default_factory=list)


def compute_lintels(
    document: WallsDocument,
    items: list[WallsConstruction],
    props_by_key: PropsByKey,
    levels: EffectiveLevels,
    partition_heights: Mapping[str, PartitionHeight | PartitionFullHeight] | None = None,
) -> tuple[dict[float, LintelGroup], int]:
    """Монолитные перемычки над проёмами стен не из монолита: группы по толщине хозяина.

    Объём = площадь контура в плане x (высота хозяина - высота двери). Высота хозяина - как у
    `construction_height` (у внутриквартирной перегородки - маячный ряд). Возвращает группы и
    число перемычек без определимого объёма (нет хозяина, толщины или высоты).
    """
    hosts = {c.id: c for c in items}
    groups: dict[float, LintelGroup] = defaultdict(LintelGroup)
    without_volume = 0
    door_height = levels.door_height.value_mm
    for opening in document.openings:
        if opening.kind == "door" and opening.status == "no_data":
            continue
        if opening.kind == "window" and opening.opening_height_mm is None:
            continue  # окно без высоты: перемычка не строится, допущения о высоте нет
        if not is_monolith_lintel(opening) or opening.lintel is None:
            continue
        host = hosts.get(opening.host_id) if opening.host_id is not None else None
        if host is not None and _is_monolith_kind(host.kind):
            continue  # перемычка уже в объёме монолитного хозяина
        if host is None:
            without_volume += 1
            continue
        props = props_by_key.get(host.id, (CadConstructionProps(), False))[0]
        if not props.count_openings:
            continue
        thickness = (
            float(props.thickness_override_mm)
            if props.thickness_override_mm is not None
            else host.thickness_nominal_mm
        )
        height = construction_height(
            props, levels, None if partition_heights is None else partition_heights.get(host.id)
        ).height_mm
        opening_height = (
            opening.opening_height_mm
            if opening.kind != "door" and opening.opening_height_mm is not None
            else door_height
        )
        if thickness is None or height is None or opening_height is None:
            without_volume += 1
            continue
        above = float(height) - float(opening_height)
        if above <= 0:
            continue
        group = groups[thickness]
        group.widths_mm.append(opening.width_mm)
        group.volumes_m3.append(_ring_area_mm2(opening.lintel) * above / _MM3_IN_M3)
    return groups, without_volume


def compute_sheet(
    document: WallsDocument,
    props_by_key: PropsByKey,
    overrides: CadSheetLevelsRead,
    project_slab: ProjectSlab | None = None,
    slab: SlabInput | None = None,
    partition: PartitionContext | None = None,
) -> SheetResult:
    """Конструкции листа с величинами и итоги по группам (вид x толщина x материал).

    `slab` — плита перекрытия листа; её добавляют в конец списка и считают как конструкцию.
    Без неё (3D-вид, общий вид здания) поведение прежнее. `partition` — зоны помещений и принятая
    высота маячного ряда; без него высота перегородок - как у остальных стен листа.
    """
    levels = effective_levels(document.heights, overrides, project_slab)
    items_all = [*document.constructions, *document.frame_partitions]
    classes = classify_partitions(
        document.constructions, props_by_key, () if partition is None else partition.zones
    )
    candidates = partition_candidate_ids(classes)
    partition_heights = partition_heights_by_id(classes, partition)
    # Проёмы маячного ряда - разрыв выкладки: в расчёт хозяев, перемычек и сводку не входят.
    marker_gaps = marker_row_gap_ids(document, partition_heights, props_by_key)
    counted = (
        document.model_copy(
            update={"openings": [o for o in document.openings if o.id not in marker_gaps]}
        )
        if marker_gaps
        else document
    )
    known = {c.id for c in items_all}
    by_host: dict[str, list[WallsOpening]] = defaultdict(list)
    for opening in counted.openings:
        if opening.host_id is not None and opening.host_id in known:
            by_host[opening.host_id].append(opening)

    constructions: list[CadConstructionRead] = []
    groups: dict[tuple[CadConstructionKind, float, CadMaterial | None], list[Computed]] = (
        defaultdict(list)
    )
    check_count = 0
    height_missing_count = 0
    for item in items_all:
        props, accepted = props_by_key.get(item.id, (CadConstructionProps(), False))
        material = effective_material(item, props)
        computed = compute_construction(
            item,
            by_host.get(item.id, []),
            props,
            levels,
            material,
            partition_heights.get(item.id),
        )
        if computed.status == "thickness_check":
            check_count += 1
        elif computed.status == "height_missing":
            height_missing_count += 1
        elif computed.thickness_mm is not None:
            groups[(item.kind, computed.thickness_mm, material.value)].append(computed)
        constructions.append(
            CadConstructionRead(
                id=item.id,
                kind=item.kind,
                source_layers=item.source_layers,
                polygon=item.polygon,
                centroid=item.centroid,
                bbox=item.bbox,
                area_plan_m2=round(item.area_plan_mm2 / _MM2_IN_M2, 4),
                thickness_measured_mm=item.thickness_measured_mm,
                thickness_nominal_mm=item.thickness_nominal_mm,
                thickness_status=item.thickness_status,
                computed=computed.read(),
                props=props,
                material=material,
                accepted=accepted,
            )
        )
    if slab is not None:
        slab_props, slab_accepted = props_by_key.get(slab.id, (CadConstructionProps(), False))
        slab_material = _slab_material(slab_props)
        slab_computed = compute_slab(slab, slab_props, levels)
        if slab_computed.status == "thickness_check":
            check_count += 1
        elif slab_computed.thickness_mm is not None:
            groups[("floor_slab", slab_computed.thickness_mm, slab_material.value)].append(
                slab_computed
            )
        constructions.append(
            slab_read(slab, slab_computed, slab_props, slab_material, slab_accepted)
        )

    def order(key: tuple[CadConstructionKind, float, CadMaterial | None]) -> tuple[int, float, str]:
        return (KIND_ORDER.index(key[0]), key[1], key[2] or "")

    lintel_groups, lintels_without_volume = compute_lintels(
        counted, items_all, props_by_key, levels, partition_heights
    )
    lintel_element: CadGroupElement = "lintel"
    lintel_totals = [
        CadConstructionGroupRead(
            kind=LINTEL_GROUP_KIND,
            element=lintel_element,
            thickness_mm=thickness,
            material=LINTEL_GROUP_MATERIAL,
            count=len(group.widths_mm),
            length_m=round(math.fsum(group.widths_mm) / 1000, 3),
            wall_area_m2=0.0,
            volume_m3=round(math.fsum(group.volumes_m3), 4),
        )
        for thickness, group in sorted(lintel_groups.items())
    ]
    totals = [
        CadConstructionGroupRead(
            kind=kind,
            thickness_mm=thickness,
            material=material,
            count=len(items),
            length_m=round(math.fsum(c.length_m or 0.0 for c in items), 3),
            wall_area_m2=round(math.fsum(c.wall_area_m2 or 0.0 for c in items), 3),
            volume_m3=(
                None
                if kind == "frame_partition"
                else round(math.fsum(c.volume_m3 or 0.0 for c in items), 4)
            ),
            area_m2=(
                round(math.fsum(c.area_m2 or 0.0 for c in items), 3)
                if kind == "floor_slab"
                else None
            ),
        )
        for (kind, thickness, material), items in sorted(
            groups.items(), key=lambda kv: order(kv[0])
        )
    ]
    # Перемычки — сразу после групп монолита, перед каркасными перегородками и плитой.
    after_monolith = next(
        (
            i
            for i, total in enumerate(totals)
            if KIND_ORDER.index(total.kind) > KIND_ORDER.index("monolith_column")
        ),
        len(totals),
    )
    totals[after_monolith:after_monolith] = lintel_totals
    summary = CadConstructionsSummaryRead(
        total_count=len(items_all) + (0 if slab is None else 1),
        thickness_check_count=check_count,
        height_missing_count=height_missing_count,
        unaccounted_gap_openings=sum(
            1 for o in counted.openings if o.kind != "door" and o.opening_height_mm is None
        ),
        door_openings_without_host=sum(
            1
            for o in counted.openings
            if o.kind == "door" and (o.host_id is None or o.host_id not in known)
        ),
        lintels_without_volume=lintels_without_volume,
        apartment_partition_count=sum(
            1 for c in constructions if c.computed.height_basis == "apartment_partition"
        ),
    )
    openings = [
        CadOpeningRead(
            id=o.id,
            kind=o.kind,
            status=o.status,
            host_id=o.host_id,
            adjacent_ids=o.adjacent_ids,
            width_mm=o.width_mm,
            width_source=o.width_source,
            thickness_mm=o.thickness_mm,
            block_name=o.block_name,
            handle=o.handle,
            center=o.center,
            marker_row_gap=o.id in marker_gaps,
        )
        for o in document.openings
    ]
    return SheetResult(
        heights=heights_read(
            document.heights, levels, None if partition is None else partition.height
        ),
        constructions=constructions,
        openings=openings,
        totals=totals,
        summary=summary,
        partition_warnings=[
            *partition_warnings(partition, candidates, props_by_key),
            *(
                [(WINDOW_HEIGHT_UNKNOWN, WINDOW_HEIGHT_UNKNOWN_MESSAGE)]
                if windows_without_height(document.openings)
                else []
            ),
        ],
    )


# --------------------------------------------------------------------------- перенос параметров

# Допустимое изменение площади конструкции между пересчётами при переносе параметров.
CARRY_AREA_RATIO_MIN: Final = 0.5
CARRY_AREA_RATIO_MAX: Final = 2.0
_NOMINAL_TOLERANCE_MM: Final = 1e-6


def _in_ring(point: tuple[float, float], ring: list[list[float]]) -> bool:
    """Точка в кольце: чётно-нечётное правило (луч вправо)."""
    x, y = point
    inside = False
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _in_polygon(point: list[float], polygon: WallsPolygon) -> bool:
    """Точка внутри внешнего кольца и вне отверстий."""
    if len(point) < 2 or len(polygon.shell) < 3:
        return False
    pt = (point[0], point[1])
    if not _in_ring(pt, polygon.shell):
        return False
    return not any(len(hole) >= 3 and _in_ring(pt, hole) for hole in polygon.holes)


def _polygon_area_mm2(polygon: WallsPolygon) -> float:
    if len(polygon.shell) < 3:
        return 0.0
    holes = math.fsum(_ring_area_mm2(hole) for hole in polygon.holes if len(hole) >= 3)
    return max(0.0, _ring_area_mm2(polygon.shell) - holes)


def _same_nominal(old: float | None, new: float | None) -> bool:
    if old is None or new is None:
        return old is None and new is None
    return abs(old - new) <= _NOMINAL_TOLERANCE_MM


def is_same_construction(old: WallsConstruction, new: WallsConstruction) -> bool:
    """Старая и новая конструкция — вероятно, одна и та же стена после пересчёта.

    Тот же вид и номинальная толщина (обе не определены — тоже равны), центроид одной лежит внутри
    контура другой (отверстия не считаются), площади отличаются не более чем вдвое.
    """
    if old.kind != new.kind or not _same_nominal(
        old.thickness_nominal_mm, new.thickness_nominal_mm
    ):
        return False
    old_area = _polygon_area_mm2(old.polygon)
    new_area = _polygon_area_mm2(new.polygon)
    if old_area <= 0.0 or new_area <= 0.0:
        return False
    if not CARRY_AREA_RATIO_MIN <= new_area / old_area <= CARRY_AREA_RATIO_MAX:
        return False
    return _in_polygon(old.centroid, new.polygon) or _in_polygon(new.centroid, old.polygon)


def match_orphan_props(
    orphans: Mapping[str, WallsConstruction],
    props: PropsByKey,
    current: Sequence[WallsConstruction],
    occupied: Collection[str],
) -> dict[str, str]:
    """Осиротевший адрес -> адрес конструкции текущего файла; неоднозначное пропускается.

    `orphans` — старая геометрия осиротевших адресов, `props` — их параметры, `occupied` — адреса
    текущих конструкций, у которых уже есть своя запись (перезаписывать её нельзя). Перенос, только
    если кандидат ровно один; несколько сирот на одну конструкцию (слияние) переносятся, лишь когда
    их параметры и признак принятия совпадают.
    """
    targets: dict[str, list[str]] = defaultdict(list)
    for key, old in orphans.items():
        candidates = [c.id for c in current if is_same_construction(old, c)]
        if len(candidates) == 1 and candidates[0] not in occupied and key in props:
            targets[candidates[0]].append(key)
    moves: dict[str, str] = {}
    for target, keys in targets.items():
        first = props[keys[0]]
        if all(props[key] == first for key in keys):
            moves.update(dict.fromkeys(keys, target))
    return moves
