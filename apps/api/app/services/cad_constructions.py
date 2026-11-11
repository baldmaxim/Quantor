"""Расчёт величин конструкций по walls.json и данным человека (ADR-0038 п. 3).

Чистые функции без базы и хранилища: на входе разобранный `walls.json`, параметры конструкций и
переопределения высот листа, на выходе конструкции с величинами и итоги по группам. Модель нигде
не участвует; стоимости нет. Не определено — `None`, а не 0: «не определено» не превращается в
молчаливое умолчание.

Формулы (мм, результат в м, м2, м3):

- толщина `t` = переопределение человека, иначе номинал скрипта; номинала нет — `thickness_check`;
- высота `H` = переопределение человека, иначе (высота этажа - толщина плиты); высота этажа и
  толщина плиты — переопределение листа, иначе значение из walls.json; нет высоты —
  `height_missing`;
- материал: ввод человека (`props.material`), иначе подсказка из условных обозначений листа, если
  она однозначна (`matched`); props автоматически не заполняются; нет материала при подсказке
  `not_in_legend` или `conflict` — предупреждение `material_check` (на статус не влияет);
- длина = длина оси из walls.json (площадь в плане / измеренная толщина);
- объём = длина x `t` x `H` (по номиналу: штриховка бывает шире номинала) плюс по
  каждой двери конструкции ширина x `t` x max(0, `H` - высота двери): дверь стоит в разрыве стены
  на плане, и надпроёмная часть в площадь плана не попадает;
- площадь стены = длина x `H` плюс по каждой двери ширина x max(0, `H` - высота двери);
- каркасная перегородка ГКЛ (`frame_partition`) меряется площадью: длина и площадь стены как у
  кладки, объём не определён (`None`);
- разрыв без данных о проёме (`gap`) в объём и площадь не входит и даёт предупреждение
  `opening_no_data` у несущей конструкции.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
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
    CadHeightsRead,
    CadLevelValueRead,
    CadMaterial,
    CadOpeningRead,
    CadSheetLevelsRead,
    CadValueSource,
    WallsConstruction,
    WallsDocument,
    WallsHeights,
    WallsOpening,
)

KIND_ORDER: Final[tuple[CadConstructionKind, ...]] = (
    "masonry",
    "monolith_wall",
    "monolith_pylon",
    "monolith_column",
    "frame_partition",
)

_MM2_IN_M2: Final = 1e6
_MM3_IN_M3: Final = 1e9


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
    Отметка этажа: переопределение листа, затем walls.json.
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
    if overrides.floor_elevation_mm is not None:
        elevation, elevation_source = overrides.floor_elevation_mm, "manual"
    else:
        elevation = heights.floor_elevation_mm
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
        floor, slab, door, wall, wall_source, elevation, elevation_source, slab_ref
    )


def heights_read(heights: WallsHeights, levels: EffectiveLevels) -> CadHeightsRead:
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
        )


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def compute_construction(
    construction: WallsConstruction,
    host_openings: list[WallsOpening],
    props: CadConstructionProps,
    levels: EffectiveLevels,
    material: CadConstructionMaterialRead | None = None,
) -> Computed:
    """Величины одной конструкции; `host_openings` — проёмы, чья несущая стена — она.

    `material` — действующий материал (по умолчанию из `effective_material`).
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

    height: int | None
    height_source: CadValueSource | None
    if props.height_override_mm is not None:
        height, height_source = props.height_override_mm, "manual"
    else:
        height, height_source = levels.wall_height_mm, levels.wall_height_source

    doors = [o for o in host_openings if o.kind == "door"] if props.count_openings else []
    door_height = levels.door_height.value_mm
    warnings: list[CadConstructionWarning] = []
    if thickness is None:
        warnings.append("thickness_check")
    door_height_missing = bool(doors) and door_height is None
    if height is None or door_height_missing:
        warnings.append("height_missing")
    if any(o.kind == "gap" or o.status == "no_data" for o in host_openings):
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
            above_mm = [
                (o.width_mm, max(0.0, float(height) - float(door_height or 0))) for o in doors
            ]
            if construction.kind != "frame_partition":
                volume_m3 = (
                    base_mm3_per_h * height + math.fsum(w * thickness * h for w, h in above_mm)
                ) / _MM3_IN_M3
            wall_area_m2 = length_m * height / 1000 + math.fsum(w * h for w, h in above_mm) / (
                _MM2_IN_M2
            )
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
        ),
        warnings=warnings,
    )


@dataclass(frozen=True, slots=True)
class SheetResult:
    heights: CadHeightsRead
    constructions: list[CadConstructionRead]
    openings: list[CadOpeningRead]
    totals: list[CadConstructionGroupRead]
    summary: CadConstructionsSummaryRead


PropsByKey = Mapping[str, tuple[CadConstructionProps, bool]]


def compute_sheet(
    document: WallsDocument,
    props_by_key: PropsByKey,
    overrides: CadSheetLevelsRead,
    project_slab: ProjectSlab | None = None,
) -> SheetResult:
    """Конструкции листа с величинами и итоги по группам (вид x толщина x материал)."""
    levels = effective_levels(document.heights, overrides, project_slab)
    items_all = [*document.constructions, *document.frame_partitions]
    known = {c.id for c in items_all}
    by_host: dict[str, list[WallsOpening]] = defaultdict(list)
    for opening in document.openings:
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
        computed = compute_construction(item, by_host.get(item.id, []), props, levels, material)
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

    def order(key: tuple[CadConstructionKind, float, CadMaterial | None]) -> tuple[int, float, str]:
        return (KIND_ORDER.index(key[0]), key[1], key[2] or "")

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
        )
        for (kind, thickness, material), items in sorted(
            groups.items(), key=lambda kv: order(kv[0])
        )
    ]
    summary = CadConstructionsSummaryRead(
        total_count=len(items_all),
        thickness_check_count=check_count,
        height_missing_count=height_missing_count,
        unaccounted_gap_openings=sum(1 for o in document.openings if o.kind == "gap"),
        door_openings_without_host=sum(
            1
            for o in document.openings
            if o.kind == "door" and (o.host_id is None or o.host_id not in known)
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
        )
        for o in document.openings
    ]
    return SheetResult(
        heights=heights_read(document.heights, levels),
        constructions=constructions,
        openings=openings,
        totals=totals,
        summary=summary,
    )
