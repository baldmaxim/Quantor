"""3D DXF этажа для AutoCAD по модели 3D-вида (ADR-0036 п. 6, ADR-0039).

Вход - JSON модели этажа, как её отдаёт API (`CadFloor3dRead`): высоты с источниками, плита,
отверстия плиты с решением человека, стены, перемычки, полотна дверей; мм системы DXF плана.
Выход - DXF R2018, единицы мм (`$INSUNITS = 4`): X и Y - как в DXF плана (без центрирования,
чтобы 3D ложился на план), Z - абсолютные отметки из модели.

Каждая призма (плита, стена, перемычка, полотно двери) - замкнутая сущность MESH: низ и верх -
триангуляция полигона с дырами, боковые грани - по каждому кольцу. Плита вырезана по отверстиям
в состоянии `enabled` и `candidate`; `disabled` - плита сплошная. Контуры включённых и
кандидатных отверстий дополнительно лежат полилиниями на отметке верха плиты. Площадей и объёмов
в файле нет.

Сущности пишутся в порядке ключей модели, дата и GUID заголовка фиксированы: одна и та же модель
даёт один и тот же файл.
"""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ezdxf._options import options
from ezdxf.document import Drawing
from ezdxf.filemanagement import new
from ezdxf.layouts.layout import Modelspace
from ezdxf.math import Vec2
from ezdxf.math.triangulation import mapbox_earcut_2d
from ezdxf.render.mesh import MeshVertexMerger

from cad_walls.errors import WallsError

GENERATOR_VERSION: Final = "cad_floor3d_dxf.v2"
DXF_VERSION: Final = "R2018"
DXF_UNITS_MM: Final = 4
PROP_PREFIX: Final = "QUANTOR_"
MAX_MODEL_BYTES: Final = 32 * 1024 * 1024
MAX_PROP_LENGTH: Final = 1000

LAYER_SLAB: Final = "Q3D_ПЛИТА"
LAYER_MASONRY: Final = "Q3D_КЛАДКА"
LAYER_MONOLITH: Final = "Q3D_МОНОЛИТ"
LAYER_LINTELS: Final = "Q3D_ПЕРЕМЫЧКИ"
LAYER_DOORS: Final = "Q3D_ДВЕРИ"
LAYER_HOLES: Final = "Q3D_ОТВЕРСТИЯ"
LAYER_HOLES_CANDIDATE: Final = "Q3D_ОТВЕРСТИЯ_КАНДИДАТЫ"
# Цвета ACI заданы явно: слои различимы в любой теме AutoCAD.
LAYER_COLORS: Final = {
    LAYER_SLAB: 8,
    LAYER_MASONRY: 30,
    LAYER_MONOLITH: 5,
    LAYER_LINTELS: 6,
    LAYER_DOORS: 3,
    LAYER_HOLES: 1,
    LAYER_HOLES_CANDIDATE: 2,
}
_FAMILY_LAYERS: Final = {"masonry": LAYER_MASONRY, "monolith": LAYER_MONOLITH}

_EPS_MM: Final = 1e-6
# Допуск попадания вершины кольца на ребро триангуляции (мм): много меньше точности чертежа.
_ON_EDGE_MM: Final = 1e-4
_TRIANGULATION_TOLERANCE: Final = 1e-3

Point = tuple[float, float]
Ring = list[Point]
JsonObject = dict[str, object]


# --------------------------------------------------------------------------- разбор модели


@dataclass(frozen=True, slots=True)
class Prism:
    """Призма: слой, ключ порядка, контур с дырами и отметки низа и верха (мм)."""

    layer: str
    key: str
    shell: Ring
    holes: list[Ring]
    z_bottom: float
    z_top: float


@dataclass(frozen=True, slots=True)
class HoleOutline:
    key: str
    layer: str
    ring: Ring


@dataclass(slots=True)
class FloorModel:
    """Разобранная модель: призмы, контуры отверстий, свойства заголовка и пропуски."""

    prisms: list[Prism] = field(default_factory=list)
    outlines: list[HoleOutline] = field(default_factory=list)
    outline_elevation: float = 0.0
    properties: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _bad(message: str) -> WallsError:
    return WallsError("bad_model", message)


def _obj(value: object, what: str) -> JsonObject:
    if not isinstance(value, dict):
        raise _bad(f"{what}: ожидался объект")
    return {str(k): v for k, v in value.items()}


def _list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise _bad(f"{what}: ожидался список")
    return list(value)


def _str(value: object, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise _bad(f"{what}: ожидалась непустая строка")
    return value


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _bad(f"{what}: ожидалось число")
    return float(value)


def _opt_number(value: object, what: str) -> float | None:
    return None if value is None else _number(value, what)


def _ring(value: object, what: str) -> Ring:
    """Кольцо без повторов: замыкающая точка и подряд идущие дубликаты убираются."""
    points: Ring = []
    for item in _list(value, what):
        pair = _list(item, what)
        if len(pair) < 2:
            raise _bad(f"{what}: точка без двух координат")
        point = (_number(pair[0], what), _number(pair[1], what))
        if not points or math.dist(points[-1], point) > _EPS_MM:
            points.append(point)
    if len(points) > 1 and math.dist(points[0], points[-1]) <= _EPS_MM:
        points.pop()
    return points


def _signed_area2(ring: Sequence[Point]) -> float:
    """Удвоенная площадь со знаком; нужна только для ориентации колец и проверки триангуляции."""
    total = 0.0
    for i, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(i + 1) % len(ring)]
        total += x0 * y1 - x1 * y0
    return total


def _inside(ring: Sequence[Point], point: Point) -> bool:
    """Точка внутри кольца (чётность пересечений луча)."""
    x, y = point
    result = False
    for i, (x0, y0) in enumerate(ring):
        x1, y1 = ring[(i + 1) % len(ring)]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            result = not result
    return result


def _oriented(ring: Ring, *, counter_clockwise: bool) -> Ring:
    return ring if (_signed_area2(ring) > 0) == counter_clockwise else ring[::-1]


def _usable(ring: Ring) -> bool:
    return len(ring) >= 3 and abs(_signed_area2(ring)) > _EPS_MM


def _text(value: object) -> str:
    """Значение свойства заголовка: одна строка до `MAX_PROP_LENGTH` знаков."""
    text = " ".join(str(value).split())
    return text if len(text) <= MAX_PROP_LENGTH else text[: MAX_PROP_LENGTH - 1] + "…"


def _mm(value: object) -> str:
    return "не определено" if value is None else f"{_number(value, 'высота'):g}"


def _source(value: object) -> str:
    return "не определён" if value is None else _text(value)


def _header_properties(
    raw: JsonObject, model_sha256: str, *, elevation_known: bool
) -> list[tuple[str, str]]:
    """Свойства `QUANTOR_*`: генератор, хеш модели, высоты с источниками, предупреждения."""
    heights = _obj(raw.get("heights"), "heights")
    floor_height = _obj(heights.get("floor_height"), "heights.floor_height")
    slab = _obj(heights.get("slab_thickness"), "heights.slab_thickness")
    door = _obj(heights.get("door_height"), "heights.door_height")
    elevation = (
        _mm(heights.get("floor_elevation_mm"))
        if elevation_known
        else "не определена (построено от нуля)"
    )
    warnings = [
        f"{_text(_obj(w, 'warning').get('code'))}: {_text(_obj(w, 'warning').get('message'))}"
        for w in _list(raw.get("warnings", []), "warnings")
    ]
    rows = [
        ("GENERATOR", GENERATOR_VERSION),
        ("MODEL_GENERATOR", _text(raw.get("generator", ""))),
        ("MODEL_SHA256", model_sha256),
        ("FLOOR_ELEVATION_MM", elevation),
        ("FLOOR_ELEVATION_SOURCE", _source(heights.get("floor_elevation_source"))),
        ("FLOOR_HEIGHT_MM", _mm(floor_height.get("value_mm"))),
        ("FLOOR_HEIGHT_SOURCE", _source(floor_height.get("source"))),
        ("SLAB_THICKNESS_MM", _mm(slab.get("value_mm"))),
        ("SLAB_THICKNESS_SOURCE", _source(slab.get("source"))),
        ("SLAB_THICKNESS_SHEET", _source(heights.get("slab_thickness_sheet_ref"))),
        ("DOOR_HEIGHT_MM", _mm(door.get("value_mm"))),
        ("DOOR_HEIGHT_SOURCE", _source(door.get("source"))),
        ("WARNINGS", "; ".join(warnings) if warnings else "нет"),
    ]
    return [(PROP_PREFIX + tag, value) for tag, value in rows]


def parse_model(raw_bytes: bytes) -> FloorModel:
    """Разбирает и проверяет JSON модели; негодная модель - `WallsError` (код выхода 2)."""
    if len(raw_bytes) > MAX_MODEL_BYTES:
        raise _bad("модель больше допустимого размера")
    try:
        loaded: object = json.loads(raw_bytes)
    except ValueError as error:
        raise _bad("модель не читается как JSON") from error
    raw = _obj(loaded, "модель")
    if raw.get("units") != "mm":
        raise _bad("единицы модели должны быть мм")
    base = _number(raw.get("base_z_mm"), "base_z_mm")
    model = FloorModel(outline_elevation=base)
    model.properties = _header_properties(
        raw,
        hashlib.sha256(raw_bytes).hexdigest(),
        elevation_known=raw.get("elevation_known") is True,
    )

    slab_ring: Ring | None = None
    slab_z: tuple[float, float] = (0.0, 0.0)
    slab_raw = raw.get("slab")
    if slab_raw is not None:
        slab = _obj(slab_raw, "slab")
        z_top = _number(slab.get("z_top_mm"), "slab.z_top_mm")
        model.outline_elevation = z_top
        z_bottom = _opt_number(slab.get("z_bottom_mm"), "slab.z_bottom_mm")
        shell = _ring(slab.get("shell"), "slab.shell")
        if z_bottom is None:
            model.skipped.append("плита: толщина не определена")
        elif not _usable(shell) or z_bottom >= z_top:
            model.skipped.append("плита: вырожденный контур или отметки")
        else:
            slab_ring, slab_z = shell, (z_bottom, z_top)

    holes: list[tuple[str, str, Ring]] = []
    for item in _list(raw.get("slab_holes", []), "slab_holes"):
        hole = _obj(item, "slab_holes[]")
        key = _str(hole.get("key"), "slab_holes[].key")
        state = _str(hole.get("state"), f"slab_holes[{key}].state")
        if state not in ("candidate", "enabled", "disabled"):
            raise _bad(f"отверстие {key}: неизвестное состояние {state}")
        if state == "disabled":
            continue
        ring = _ring(hole.get("shell"), f"slab_holes[{key}].shell")
        if not _usable(ring):
            model.skipped.append(f"отверстие {key}: вырожденный контур")
            continue
        holes.append((key, state, ring))
    holes.sort(key=lambda row: row[0])

    cut: list[Ring] = []
    for key, state, ring in holes:
        layer = LAYER_HOLES if state == "enabled" else LAYER_HOLES_CANDIDATE
        model.outlines.append(HoleOutline(key, layer, ring))
        if slab_ring is not None:
            if all(_inside(slab_ring, p) for p in ring):
                cut.append(ring)
            else:
                model.skipped.append(f"отверстие {key}: вне контура плиты, вырез не сделан")
    if slab_ring is not None:
        model.prisms.append(Prism(LAYER_SLAB, "", slab_ring, cut, slab_z[0], slab_z[1]))

    walls: list[Prism] = []
    for item in _list(raw.get("walls", []), "walls"):
        wall = _obj(item, "walls[]")
        key = _str(wall.get("construction_key"), "walls[].construction_key")
        family = _str(wall.get("family"), f"walls[{key}].family")
        if family not in _FAMILY_LAYERS:
            raise _bad(f"стена {key}: неизвестное семейство {family}")
        z_top_wall = _opt_number(wall.get("z_top_mm"), f"walls[{key}].z_top_mm")
        if z_top_wall is None:
            model.skipped.append(f"стена {key}: высота не определена")
            continue
        z_bottom_wall = _number(wall.get("z_bottom_mm"), f"walls[{key}].z_bottom_mm")
        shell = _ring(wall.get("shell"), f"walls[{key}].shell")
        wall_holes = [
            _ring(h, f"walls[{key}].holes")
            for h in _list(wall.get("holes", []), f"walls[{key}].holes")
        ]
        if not _usable(shell) or z_bottom_wall >= z_top_wall:
            model.skipped.append(f"стена {key}: вырожденный контур или отметки")
            continue
        walls.append(
            Prism(
                _FAMILY_LAYERS[family],
                key,
                shell,
                [h for h in wall_holes if _usable(h)],
                z_bottom_wall,
                z_top_wall,
            )
        )
    walls.sort(key=lambda prism: prism.key)
    model.prisms.extend(walls)

    lintels: list[Prism] = []
    for item in _list(raw.get("lintels", []), "lintels"):
        lintel = _obj(item, "lintels[]")
        key = _str(lintel.get("opening_id"), "lintels[].opening_id")
        shell = _ring(lintel.get("shell"), f"lintels[{key}].shell")
        z0 = _number(lintel.get("z_bottom_mm"), f"lintels[{key}].z_bottom_mm")
        z1 = _number(lintel.get("z_top_mm"), f"lintels[{key}].z_top_mm")
        if not _usable(shell) or z0 >= z1:
            model.skipped.append(f"перемычка {key}: вырожденный контур или отметки")
            continue
        # материал (модель с cad_walls v1.6): монолит - на слой монолита, иначе - слой перемычек
        layer = LAYER_MONOLITH if lintel.get("material") == "monolith" else LAYER_LINTELS
        lintels.append(Prism(layer, key, shell, [], z0, z1))
    lintels.sort(key=lambda prism: prism.key)
    model.prisms.extend(lintels)

    # полотна дверей (модель API с cad_walls v1.4); в старой модели ключа нет
    doors: list[Prism] = []
    for item in _list(raw.get("doors", []), "doors"):
        door = _obj(item, "doors[]")
        key = _str(door.get("opening_id"), "doors[].opening_id")
        shell = _ring(door.get("shell"), f"doors[{key}].shell")
        z0 = _number(door.get("z_bottom_mm"), f"doors[{key}].z_bottom_mm")
        z1 = _number(door.get("z_top_mm"), f"doors[{key}].z_top_mm")
        if not _usable(shell) or z0 >= z1:
            model.skipped.append(f"дверь {key}: вырожденный контур или отметки")
            continue
        doors.append(Prism(LAYER_DOORS, key, shell, [], z0, z1))
    doors.sort(key=lambda prism: prism.key)
    model.prisms.extend(doors)
    return model


# --------------------------------------------------------------------------- геометрия


def _cap_triangles(shell: Ring, holes: list[Ring]) -> list[tuple[Vec2, Vec2, Vec2]]:
    """Триангуляция многоугольника с дырами; тройки вершин без ориентации."""
    triangles = mapbox_earcut_2d(shell, holes)
    return [(t[0], t[1], t[2]) for t in triangles]


def _triangle_area2(a: Vec2, b: Vec2, c: Vec2) -> float:
    return float((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y))


class _VertexIndex:
    """Вершины колец, отсортированные по X: поиск вершин, лежащих на ребре триангуляции.

    Ear clipping может провести ребро треугольника вдоль нескольких вершин колец (например, через
    два соосных отверстия). Без этих вершин на ребре верх и низ плиты не стыкуются с боковыми
    гранями по вершинам (Т-стык) и сетка не замкнута топологически.
    """

    def __init__(self, rings: Sequence[Sequence[Point]]) -> None:
        unique = sorted({p for ring in rings for p in ring})
        self._points = unique
        self._xs = [p[0] for p in unique]

    def on_edge(self, a: Vec2, b: Vec2) -> list[Point]:
        """Вершины строго внутри отрезка ab, по порядку от a к b."""
        lo = bisect_left(self._xs, min(a.x, b.x) - _ON_EDGE_MM)
        hi = bisect_right(self._xs, max(a.x, b.x) + _ON_EDGE_MM)
        dx, dy = b.x - a.x, b.y - a.y
        length2 = dx * dx + dy * dy
        if length2 == 0.0:
            return []
        found: list[tuple[float, Point]] = []
        for point in self._points[lo:hi]:
            t = ((point[0] - a.x) * dx + (point[1] - a.y) * dy) / length2
            if t <= 0.0 or t >= 1.0:
                continue
            if math.hypot(point[0] - (a.x + t * dx), point[1] - (a.y + t * dy)) > _ON_EDGE_MM:
                continue
            if math.dist(point, (a.x, a.y)) <= _ON_EDGE_MM or math.dist(point, (b.x, b.y)) <= (
                _ON_EDGE_MM
            ):
                continue
            found.append((t, point))
        found.sort()
        return [point for _t, point in found]


def _cap_face(corners: Sequence[Vec2], index: _VertexIndex) -> list[Point]:
    """Контур грани крышки: углы треугольника плюс вершины колец, лежащие на его рёбрах."""
    face: list[Point] = []
    for i, corner in enumerate(corners):
        face.append((corner.x, corner.y))
        face.extend(index.on_edge(corner, corners[(i + 1) % len(corners)]))
    return face


def build_mesh(prism: Prism) -> tuple[MeshVertexMerger, bool]:
    """Замкнутая сетка призмы; второй результат - сошлась ли триангуляция с контуром.

    Внешнее кольцо ориентируется против часовой стрелки, дыры - по часовой: боковые грани
    смотрят наружу от тела (в дыру - тоже наружу от тела), верх - вверх, низ - вниз.
    """
    shell = _oriented(prism.shell, counter_clockwise=True)
    holes = [_oriented(h, counter_clockwise=False) for h in prism.holes]
    mesh = MeshVertexMerger()
    z0, z1 = prism.z_bottom, prism.z_top
    triangles = _cap_triangles(shell, holes)
    index = _VertexIndex([shell, *holes])
    covered = 0.0
    for a, b, c in triangles:
        area2 = _triangle_area2(a, b, c)
        if area2 == 0.0:
            continue
        covered += abs(area2)
        corners = (a, b, c) if area2 > 0 else (a, c, b)
        face = _cap_face(corners, index)
        mesh.add_face([(x, y, z1) for x, y in face])
        mesh.add_face([(x, y, z0) for x, y in reversed(face)])
    for ring in (shell, *holes):
        for i, (x0, y0) in enumerate(ring):
            x1, y1 = ring[(i + 1) % len(ring)]
            mesh.add_face([(x0, y0, z0), (x1, y1, z0), (x1, y1, z1), (x0, y0, z1)])
    expected = abs(_signed_area2(shell)) - sum(abs(_signed_area2(h)) for h in holes)
    matched = bool(triangles) and abs(covered - expected) <= _TRIANGULATION_TOLERANCE * max(
        expected, 1.0
    )
    return mesh, matched


# --------------------------------------------------------------------------- запись DXF


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Итог записи: сущности по слоям, предупреждения генератора."""

    meshes: dict[str, int]
    outlines: int
    skipped: list[str]
    triangulation_mismatch: list[str]


def _layers(doc: Drawing) -> None:
    for name, aci in LAYER_COLORS.items():
        doc.layers.new(name, dxfattribs={"color": aci})


def _add_outlines(msp: Modelspace, model: FloorModel) -> None:
    for outline in model.outlines:
        msp.add_lwpolyline(
            outline.ring,
            close=True,
            dxfattribs={"layer": outline.layer, "elevation": model.outline_elevation},
        )


def _write_properties(doc: Drawing, properties: Sequence[tuple[str, str]]) -> None:
    custom = doc.header.custom_vars
    for tag, value in properties:
        custom.append(tag, value)


def write_dxf(model: FloorModel, path: Path) -> WriteResult:
    """Пишет DXF R2018: слои, MESH призм, контуры отверстий, свойства `QUANTOR_*` в заголовке."""
    previous = options.write_fixed_meta_data_for_testing
    # Фиксированные дата и GUID заголовка: одна и та же модель - один и тот же файл.
    options.write_fixed_meta_data_for_testing = True
    try:
        doc = new(DXF_VERSION)
        doc.units = DXF_UNITS_MM
        _layers(doc)
        msp = doc.modelspace()
        counts: dict[str, int] = {}
        mismatch: list[str] = []
        for prism in model.prisms:
            mesh, matched = build_mesh(prism)
            if not matched:
                mismatch.append(f"{prism.layer}:{prism.key or 'плита'}")
            mesh.render_mesh(msp, dxfattribs={"layer": prism.layer})
            counts[prism.layer] = counts.get(prism.layer, 0) + 1
        _add_outlines(msp, model)
        _write_properties(doc, model.properties)
        # ezdxf берёт классы из множества строк (порядок зависит от хеш-seed): фиксируем порядок.
        for name in sorted(doc.entitydb.dxf_types_in_use()):
            doc.classes.add_class(name)
        doc.classes.add_required_classes(doc.dxfversion)
        doc.saveas(str(path))
    finally:
        options.write_fixed_meta_data_for_testing = previous
    return WriteResult(counts, len(model.outlines), list(model.skipped), mismatch)


def generate(model_path: Path, out: Path) -> dict[str, object]:
    """Читает модель, пишет DXF и возвращает сводку для stdout (JSON одной строкой)."""
    if not model_path.is_file():
        raise _bad("файл модели не найден")
    raw_bytes = model_path.read_bytes()
    model = parse_model(raw_bytes)
    out.parent.mkdir(parents=True, exist_ok=True)
    result = write_dxf(model, out)
    return {
        "generator": GENERATOR_VERSION,
        "model_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "dxf_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "meshes": result.meshes,
        "outlines": result.outlines,
        "skipped": result.skipped,
        "triangulation_mismatch": result.triangulation_mismatch,
    }
