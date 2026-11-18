"""Координационный файл выпуска базы объекта: общая сетка осей и этажи здания.

ADR-0051, дополнение 2026-11-18. Источник — то, что уже лежит в выпуске: оси каждого вида
(`axes.json`, мм кадра вида, приняты движком) и размещение этажа в здании (`building.json`:
`p = R(rotation_deg) · p_вида + offset_mm`, отметка `base_z_mm`). Ничего не распознаём заново:
этажи группы уже совмещены «Зданием» по общим осям, здесь их оси переводятся в систему здания
и сводятся по подписи. Расхождение одной оси между этажами - качество совмещения, оно пишется
в файл и в сомнения.

Два файла в корне ZIP:
- `coordination.json` — `quantor.object_base.coordination.v1`: по группам (корпус/секция) оси
  линиями в мм системы здания и этажи с отметками;
- `coordination.ifc` — то же в IFC4 (мм): участок, здание на группу, этажи на отметках,
  `IfcGrid` на каждом этаже. Пишется текстом STEP без ifcopenshell: в образе API тяжёлых
  зависимостей нет (ADR-0035).
"""

from __future__ import annotations

import math
import statistics
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, cast

from app.contracts.tender_exchange import (
    ObjectBaseAxis,
    ObjectBaseCoordination,
    ObjectBaseCoordinationAxis,
    ObjectBaseCoordinationGroup,
    ObjectBaseCoordinationStorey,
)

# Две подписи одной оси на разных этажах после совмещения расходятся больше - сомнение: совмещение
# «Здания»
# допускает до ширины линии, 50 мм уже видно на плане 1:100.
SPREAD_DOUBT_MM = 50.0
# На сколько оси выходят за крайние пересечения в IFC: чтобы подписи не лежали на углу здания.
AXIS_OVERHANG_MM = 3000.0
# Ось без пересечений (в группе нет осей другого направления) рисуется отрезком такой длины.
LONE_AXIS_MM = 20000.0
IFC_GUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


@dataclass(frozen=True)
class CoordinationFloor:
    """Один вид выпуска: что о нём нужно координационному файлу."""

    view_key: str
    label: str
    group_key: str
    group_label: str
    base_z_mm: int
    floor_height_mm: int
    offset_mm: tuple[float, float]
    rotation_deg: float
    alignment: str
    axes: Sequence[ObjectBaseAxis]


@dataclass
class _Line:
    point: tuple[float, float]
    direction: tuple[float, float]
    view_key: str


@dataclass
class _GroupAcc:
    label: str
    floors: list[CoordinationFloor] = field(default_factory=list)


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return c * x - s * y, s * x + c * y


def _axis_line(axis: ObjectBaseAxis, floor: CoordinationFloor) -> _Line:
    """Ось вида линией в системе здания: вертикальная - x = pos, горизонтальная - y = pos (мм кадра
    вида).
    """
    if axis.orient == "vertical":
        point, direction = (float(axis.pos_mm), 0.0), (0.0, 1.0)
    else:
        point, direction = (0.0, float(axis.pos_mm)), (1.0, 0.0)
    px, py = _rotate(*point, floor.rotation_deg)
    dx, dy = _rotate(*direction, floor.rotation_deg)
    return _Line((px + floor.offset_mm[0], py + floor.offset_mm[1]), (dx, dy), floor.view_key)


def _merge(lines: Sequence[_Line], reference_view: str | None) -> tuple[_Line, float]:
    """Сводная линия оси и разброс (мм поперёк оси) между этажами.

    Направление берётся у эталонного этажа группы (по нему «Здание» совмещало остальные), положение
    поперёк - медиана по этажам: один плохо совмещённый лист не сдвигает сетку.
    """
    ref = next((line for line in lines if line.view_key == reference_view), lines[0])
    dx, dy = ref.direction
    nx, ny = -dy, dx
    offsets = [nx * line.point[0] + ny * line.point[1] for line in lines]
    middle = statistics.median(offsets)
    along = dx * ref.point[0] + dy * ref.point[1]
    point = (nx * middle + dx * along, ny * middle + dy * along)
    return _Line(point, (dx, dy), ref.view_key), max(offsets) - min(offsets)


def _direction_key(axis: ObjectBaseAxis) -> tuple[str, str]:
    return axis.orient, axis.label


def _label_order(label: str) -> tuple[int, int, str]:
    """Цифровые оси по числу, буквенные - по русскому алфавиту осей (без Ё, З, Й, О, Х, Ъ, Ы, Ь)."""
    if label.isdigit():
        return 0, int(label), label
    alphabet = "АБВГДЕЖИКЛМНПРСТУФЦЧШЭЮЯ"
    head = label[:1].upper()
    return 1, alphabet.index(head) if head in alphabet else len(alphabet), label


def build_coordination(floors: Iterable[CoordinationFloor]) -> ObjectBaseCoordination:
    """Сетка осей и этажи по группам здания из видов выпуска."""
    groups: dict[str, _GroupAcc] = {}
    for floor in floors:
        groups.setdefault(floor.group_key, _GroupAcc(label=floor.group_label)).floors.append(floor)
    doubts: list[str] = []
    out: list[ObjectBaseCoordinationGroup] = []
    for group_key, acc in groups.items():
        placed = [f for f in acc.floors if f.alignment != "none"]
        for f in acc.floors:
            if f.alignment == "none":
                doubts.append(
                    f"{acc.label}: вид «{f.label}» не совмещён с остальными этажами - "
                    "его оси в сетку не вошли"
                )
        reference = next((f.view_key for f in placed if f.alignment == "reference"), None)
        lines: dict[tuple[str, str], list[_Line]] = {}
        for f in placed:
            for axis in f.axes:
                lines.setdefault(_direction_key(axis), []).append(_axis_line(axis, f))
        floors_with_axes = sum(1 for f in placed if f.axes)
        axes_out: list[ObjectBaseCoordinationAxis] = []
        for (orient, label), group_lines in sorted(
            lines.items(), key=lambda kv: (kv[0][0] != "vertical", _label_order(kv[0][1]))
        ):
            merged, spread = _merge(group_lines, reference)
            if spread > SPREAD_DOUBT_MM:
                doubts.append(
                    f"{acc.label}: ось {label} расходится между этажами на {round(spread)} мм"
                )
            if floors_with_axes >= 4 and len(group_lines) * 2 < floors_with_axes:
                doubts.append(
                    f"{acc.label}: ось {label} найдена только на {len(group_lines)} из "
                    f"{floors_with_axes} этажей"
                )
            axes_out.append(
                ObjectBaseCoordinationAxis(
                    label=label,
                    orient=cast(Literal["vertical", "horizontal"], orient),
                    point_mm=[round(merged.point[0]), round(merged.point[1])],
                    direction=[round(merged.direction[0], 6), round(merged.direction[1], 6)],
                    views=len(group_lines),
                    spread_mm=round(spread),
                )
            )
        if not axes_out:
            doubts.append(f"{acc.label}: оси не найдены ни на одном этаже - сетки нет")
        storeys: dict[int, ObjectBaseCoordinationStorey] = {}
        for f in sorted(acc.floors, key=lambda f: f.base_z_mm):
            row = storeys.get(f.base_z_mm)
            if row is None:
                storeys[f.base_z_mm] = ObjectBaseCoordinationStorey(
                    label=f.label,
                    base_z_mm=f.base_z_mm,
                    floor_height_mm=f.floor_height_mm,
                    view_keys=[f.view_key],
                )
            else:
                row.view_keys.append(f.view_key)
        out.append(
            ObjectBaseCoordinationGroup(
                group_key=group_key,
                group_label=acc.label,
                axes=axes_out,
                storeys=list(storeys.values()),
            )
        )
    return ObjectBaseCoordination(
        schema_name="quantor.object_base.coordination.v1",
        units="mm",
        frame="building_mm",
        groups=out,
        doubts=doubts,
    )


# ------------------------------------------------------------------------------------------- IFC


def ifc_guid(value: uuid.UUID) -> str:
    """GlobalId IFC: 128 бит uuid в 22 знаках (основание 64, первый знак - старшие 2 бита)."""
    number = value.int
    chars = []
    for _ in range(22):
        number, rest = divmod(number, 64)
        chars.append(IFC_GUID_CHARS[rest])
    return "".join(reversed(chars))


def _step_text(value: str) -> str:
    """Строка STEP: апостроф и обратная косая удваиваются, не-ASCII - кодом \\X2\\…\\X0\\ (UTF-16).
    """
    out: list[str] = []
    wide: list[str] = []

    def flush() -> None:
        if wide:
            data = "".join(wide).encode("utf-16-be").hex().upper()
            out.append(f"\\X2\\{data}\\X0\\")
            wide.clear()

    for char in value:
        if 32 <= ord(char) < 127:
            flush()
            out.append("''" if char == "'" else "\\\\" if char == "\\" else char)
        else:
            wide.append(char)
    flush()
    return "'" + "".join(out) + "'"


def _real(value: float) -> str:
    text = f"{float(value):.3f}".rstrip("0")
    return text if not text.endswith(".") else text + "0"


class _Step:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, entity: str) -> str:
        self.lines.append(entity)
        return f"#{len(self.lines)}"

    def point2(self, x: float, y: float) -> str:
        return self.add(f"IFCCARTESIANPOINT(({_real(x)},{_real(y)}))")

    def placement(self, z: float, relative_to: str | None) -> str:
        origin = self.add(f"IFCCARTESIANPOINT((0.,0.,{_real(z)}))")
        axis = self.add(f"IFCAXIS2PLACEMENT3D({origin},$,$)")
        return self.add(f"IFCLOCALPLACEMENT({relative_to or '$'},{axis})")


def _segment(
    axis: ObjectBaseCoordinationAxis, others: Sequence[ObjectBaseCoordinationAxis]
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Отрезок оси в мм здания: от крайнего пересечения с осями другого направления до другого, с
    вылетом.
    """
    px, py = axis.point_mm
    dx, dy = axis.direction
    params: list[float] = []
    for other in others:
        ox, oy = other.point_mm
        ex, ey = other.direction
        det = dx * ey - dy * ex
        if abs(det) < 1e-6:
            continue
        params.append(((ox - px) * ey - (oy - py) * ex) / det)
    if params:
        lo, hi = min(params) - AXIS_OVERHANG_MM, max(params) + AXIS_OVERHANG_MM
    else:
        lo, hi = -LONE_AXIS_MM / 2, LONE_AXIS_MM / 2
    return (px + dx * lo, py + dy * lo), (px + dx * hi, py + dy * hi)


def _grid_axes(
    step: _Step,
    axes: Sequence[ObjectBaseCoordinationAxis],
    others: Sequence[ObjectBaseCoordinationAxis],
    curves: list[str],
) -> list[str]:
    """Оси одной семьи как IfcGridAxis; их линии добавляются в `curves` (вид «FootPrint» сетки)."""
    refs = []
    for axis in axes:
        (x1, y1), (x2, y2) = _segment(axis, others)
        curve = step.add(f"IFCPOLYLINE(({step.point2(x1, y1)},{step.point2(x2, y2)}))")
        curves.append(curve)
        refs.append(step.add(f"IFCGRIDAXIS({_step_text(axis.label)},{curve},.T.)"))
    return refs


def coordination_ifc(
    coordination: ObjectBaseCoordination,
    *,
    project_name: str,
    release_id: uuid.UUID,
    moment: datetime,
) -> bytes:
    """`coordination.ifc`: IFC4, мм. GlobalId выводятся из id выпуска - тот же выпуск даёт те же id.
    """
    step = _Step()
    counter = iter(range(1, 1_000_000))

    def guid() -> str:
        return "'" + ifc_guid(uuid.uuid5(release_id, f"coordination-{next(counter)}")) + "'"

    length = step.add("IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.)")
    angle = step.add("IFCSIUNIT(*,.PLANEANGLEUNIT.,$,.RADIAN.)")
    units = step.add(f"IFCUNITASSIGNMENT(({length},{angle}))")
    world_origin = step.add("IFCCARTESIANPOINT((0.,0.,0.))")
    world = step.add(f"IFCAXIS2PLACEMENT3D({world_origin},$,$)")
    context = step.add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,{world},$)")
    axis_context = step.add(
        f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Axis','Model',*,*,*,*,{context},$,.GRAPH_VIEW.,$)"
    )
    project = step.add(
        f"IFCPROJECT({guid()},$,{_step_text(project_name)},"
        f"{_step_text('Координационный файл: сетка осей и этажи')},$,$,$,({context}),{units})"
    )
    site_place = step.add(f"IFCLOCALPLACEMENT($,{world})")
    site = step.add(
        f"IFCSITE({guid()},$,{_step_text('Участок')},$,$,{site_place},$,$,.ELEMENT.,$,$,$,$,$)"
    )
    step.add(f"IFCRELAGGREGATES({guid()},$,$,$,{project},({site}))")
    buildings: list[str] = []
    for group in coordination.groups:
        building_place = step.placement(0.0, site_place)
        building = step.add(
            f"IFCBUILDING({guid()},$,{_step_text(group.group_label or 'Здание')},$,$,"
            f"{building_place},$,$,.ELEMENT.,$,$,$)"
        )
        buildings.append(building)
        vertical = [a for a in group.axes if a.orient == "vertical"]
        horizontal = [a for a in group.axes if a.orient == "horizontal"]
        storeys: list[str] = []
        for storey in group.storeys:
            storey_place = step.placement(storey.base_z_mm, building_place)
            storey_ref = step.add(
                f"IFCBUILDINGSTOREY({guid()},$,{_step_text(storey.label)},$,$,{storey_place},$,$,"
                f".ELEMENT.,{_real(storey.base_z_mm)})"
            )
            storeys.append(storey_ref)
            if not group.axes:
                continue
            # IfcGrid требует обе семьи осей: при одной - только этаж, без сетки.
            if not vertical or not horizontal:
                continue
            curves: list[str] = []
            u = _grid_axes(step, vertical, horizontal, curves)
            v = _grid_axes(step, horizontal, vertical, curves)
            curve_set = step.add(f"IFCGEOMETRICCURVESET(({','.join(curves)}))")
            shape = step.add(
                f"IFCSHAPEREPRESENTATION({axis_context},'FootPrint','GeometricCurveSet',({curve_set}))"
            )
            product_shape = step.add(f"IFCPRODUCTDEFINITIONSHAPE($,$,({shape}))")
            grid_place = step.placement(0.0, storey_place)
            u_list = f"({','.join(u)})"
            v_list = f"({','.join(v)})"
            grid = step.add(
                f"IFCGRID({guid()},$,{_step_text('Сетка осей')},$,$,{grid_place},{product_shape},"
                f"{u_list},{v_list},$,$)"
            )
            step.add(f"IFCRELCONTAINEDINSPATIALSTRUCTURE({guid()},$,$,$,({grid}),{storey_ref})")
        if storeys:
            step.add(f"IFCRELAGGREGATES({guid()},$,$,$,{building},({','.join(storeys)}))")
    if buildings:
        step.add(f"IFCRELAGGREGATES({guid()},$,$,$,{site},({','.join(buildings)}))")
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%S")
    header = (
        "ISO-10303-21;\nHEADER;\n"
        "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
        f"FILE_NAME('coordination.ifc','{stamp}',(''),(''),'Quantor','Quantor','');\n"
        "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n"
    )
    body = "".join(f"#{i}={line};\n" for i, line in enumerate(step.lines, start=1))
    return (header + body + "ENDSEC;\nEND-ISO-10303-21;\n").encode("ascii")
