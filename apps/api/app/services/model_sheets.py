"""Чертёж наложением на модель здания: привязка вида листа к сетке осей версии модели.

Оси вида - те же, по которым «Здание» совмещает этажи: блок `axes` в `walls.json` (подпись,
направление на листе, положение в pt страницы) и кадр вида (масштаб мм/pt). Оси модели -
часть `grids.json` пакета QMP (мм системы здания). Связь подобием без отражения листа:

    модель_мм = R(θ) · diag(s, −s) · лист_pt + t

(ось Y листа вниз, ось Y модели на север). Поворот θ берётся из направлений осей модели с теми
же подписями (корпус может стоять под любым углом), при каждом θ масштаб s и сдвиг t -
наименьшими квадратами по расстояниям до осей модели. Привязка принята, если совпали оси двух
направлений (не меньше двух каждого), остаток мал и масштаб согласен с кадром вида.

Лист рисуется в браузере (pdf.js); здесь только матрица pt → мм модели для его углов.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.model_sheets import ModelSheetOverlayList, ModelSheetOverlayRead
from app.core.logging import get_logger
from app.models import BuildingModelVersion, ModelStorey
from app.services import cad_building3d as b3d
from app.storage.base import ObjectNotFoundError, ObjectStorage
from app.storage.keys import model_part_key

log = get_logger(__name__)

GRIDS_PATH: Final = "grids.json"
MAX_GRIDS_BYTES: Final = 8 * 1024 * 1024
# Оси листа и модели параллельны после поворота с этой точностью.
PARALLEL_DEG: Final = 1.0
MIN_PER_DIRECTION: Final = 2
MAX_RMS_MM: Final = 60.0
MAX_RESIDUAL_MM: Final = 150.0
# Масштаб подгонки против масштаба кадра вида (размерная проверка листа).
MAX_SCALE_DEVIATION: Final = 0.01
# Подпись, отстоящая от подгонки дальше этого, отбрасывается и подгонка повторяется (одна марка
# у двух корпусов, неверно прочитанная подпись).
OUTLIER_MM: Final = 400.0
LAT2CYR: Final = str.maketrans("ABCEHKMOPTXYaceopxy", "АВСЕНКМОРТХУасеорху")


def normalize_label(text: str) -> str:
    """Латинские двойники кириллицы - кириллица, верхний регистр, без пробелов."""
    return "".join(text.split()).translate(LAT2CYR).upper()


@dataclass(frozen=True, slots=True)
class SheetAxis:
    """Ось вида листа: подпись, направление на листе и положение (pt страницы, Y вниз)."""

    label: str
    orient: str  # vertical (x = pos) | horizontal (y = pos)
    pos_pt: float


@dataclass(frozen=True, slots=True)
class ModelAxis:
    """Ось сетки модели: подпись и отрезок в мм системы здания."""

    tag: str
    p0: tuple[float, float]
    p1: tuple[float, float]

    @property
    def angle(self) -> float:
        return math.degrees(math.atan2(self.p1[1] - self.p0[1], self.p1[0] - self.p0[0]))

    @property
    def normal(self) -> tuple[float, float]:
        dx, dy = self.p1[0] - self.p0[0], self.p1[1] - self.p0[1]
        length = math.hypot(dx, dy) or 1.0
        return (-dy / length, dx / length)


@dataclass(frozen=True, slots=True)
class SheetFit:
    """Подобие лист (pt) → модель (мм) и его качество."""

    rotation_deg: float
    scale: float  # мм модели на pt листа
    offset: tuple[float, float]
    rms_mm: float
    max_mm: float
    used: tuple[str, ...]
    n_vertical: int
    n_horizontal: int
    # подписи, общие с моделью, но стоящие на листе не там (отброшены при подгонке)
    rejected: tuple[str, ...] = ()

    @property
    def matrix(self) -> tuple[float, float, float, float, float, float]:
        """(a, b, c, d, e, f): x_мм = a·x_pt + b·y_pt + c, y_мм = d·x_pt + e·y_pt + f."""
        c, s = math.cos(math.radians(self.rotation_deg)), math.sin(math.radians(self.rotation_deg))
        k = self.scale
        return (k * c, k * s, self.offset[0], k * s, -k * c, self.offset[1])

    def apply(self, x_pt: float, y_pt: float) -> tuple[float, float]:
        a, b, c, d, e, f = self.matrix
        return (a * x_pt + b * y_pt + c, d * x_pt + e * y_pt + f)


def _angle_gap(a: float, b: float) -> float:
    """Разница направлений по модулю 180°."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def _solve3(m: list[list[float]], v: list[float]) -> tuple[float, float, float] | None:
    """Система 3×3 методом Гаусса с выбором ведущего; вырожденная - None."""
    a = [[*row, v[i]] for i, row in enumerate(m)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(3):
            if r != col:
                factor = a[r][col] / a[col][col]
                for k in range(col, 4):
                    a[r][k] -= factor * a[col][k]
    return (a[0][3] / a[0][0], a[1][3] / a[1][1], a[2][3] / a[2][2])


def _image(axis: SheetAxis, theta: float) -> float:
    """Направление оси листа в модели при повороте θ: вертикаль листа → θ − 90°, горизонталь → θ."""
    return theta - 90.0 if axis.orient == "vertical" else theta


def _rows(
    pairs: Sequence[tuple[SheetAxis, ModelAxis]], theta: float
) -> list[tuple[list[float], float]]:
    """Уравнения N·(R·D·q + t) = N·P для пар, параллельных при повороте θ."""
    c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    rows = []
    for axis, model in pairs:
        # образ направления оси листа: вертикаль (0, 1) → R·(0, −1), горизонталь (1, 0) → R·(1, 0)
        image = theta - 90.0 if axis.orient == "vertical" else theta
        if _angle_gap(image, model.angle) > PARALLEL_DEG:
            continue
        nx, ny = model.normal
        if axis.orient == "vertical":  # точка (pos, 0) → s·pos·(c, s) + t
            k = axis.pos_pt * (nx * c + ny * s)
        else:  # точка (0, pos) → s·pos·(s, −c) + t
            k = axis.pos_pt * (nx * s - ny * c)
        rows.append(([k, nx, ny], nx * model.p0[0] + ny * model.p0[1]))
    return rows


def _least_squares(rows: Sequence[tuple[list[float], float]]) -> tuple[float, float, float] | None:
    m = [[sum(r[0][i] * r[0][j] for r in rows) for j in range(3)] for i in range(3)]
    v = [sum(r[0][i] * r[1] for r in rows) for i in range(3)]
    return _solve3(m, v)


def _residuals(
    rows: Sequence[tuple[list[float], float]], x: tuple[float, float, float]
) -> list[float]:
    return [abs(r[0][0] * x[0] + r[0][1] * x[1] + r[0][2] * x[2] - r[1]) for r in rows]


def _pairs(
    sheet: Sequence[SheetAxis], model: Sequence[ModelAxis]
) -> list[tuple[SheetAxis, ModelAxis]]:
    by_tag: dict[str, list[ModelAxis]] = {}
    for axis in model:
        by_tag.setdefault(normalize_label(axis.tag), []).append(axis)
    return [(a, m) for a in sheet for m in by_tag.get(normalize_label(a.label), [])]


def _candidate_angles(pairs: Sequence[tuple[SheetAxis, ModelAxis]]) -> list[float]:
    raw = []
    for axis, model in pairs:
        base = model.angle + (90.0 if axis.orient == "vertical" else 0.0)
        raw += [base % 360.0, (base + 180.0) % 360.0]
    out: list[float] = []
    for angle in sorted(raw):
        if not out or abs(angle - out[-1]) > 0.2:
            out.append(angle)
    return out


def fit_sheet(
    sheet: Sequence[SheetAxis], model: Sequence[ModelAxis], frame_scale: float | None = None
) -> tuple[SheetFit | None, str | None]:
    """Подобие лист → модель по подписям осей. Нет привязки - (None, причина)."""
    pairs = _pairs(sheet, model)
    if not pairs:
        return None, "на листе нет осей с подписями из сетки модели"
    best: (
        tuple[int, float, float, tuple[float, float, float], list[tuple[SheetAxis, ModelAxis]]]
        | None
    ) = None
    for theta in _candidate_angles(pairs):
        kept = [p for p in pairs if _angle_gap(_image(p[0], theta), p[1].angle) <= PARALLEL_DEG]
        while len(kept) >= 3:
            rows = _rows(kept, theta)
            x = _least_squares(rows)
            if x is None or x[0] <= 0:
                break
            res = _residuals(rows, x)
            worst = max(res)
            median = sorted(res)[len(res) // 2]
            if worst <= max(MAX_RESIDUAL_MM, 3 * median) and worst <= OUTLIER_MM:
                rms = math.sqrt(sum(r * r for r in res) / len(res))
                if best is None or (len(rows), -rms) > (best[0], -best[1]):
                    best = (len(rows), rms, theta, x, kept)
                break
            drop = kept[res.index(worst)]
            rest = [p for p in kept if p is not drop]
            n_v = sum(1 for a, _ in rest if a.orient == "vertical")
            if n_v < MIN_PER_DIRECTION or len(rest) - n_v < MIN_PER_DIRECTION:
                break
            kept = rest
    if best is None:
        return None, "подписи осей листа не складываются в одно положение на сетке модели"
    _, rms, theta, x, used = best
    rows = _rows(used, theta)
    res = _residuals(rows, x)
    n_v = len({normalize_label(a.label) for a, _ in used if a.orient == "vertical"})
    n_h = len({normalize_label(a.label) for a, _ in used if a.orient == "horizontal"})
    used_labels = {normalize_label(a.label) for a, _ in used}
    rejected = tuple(
        sorted({a.label for a, _ in pairs if normalize_label(a.label) not in used_labels})
    )
    fit = SheetFit(
        rotation_deg=round(theta % 360.0, 4),
        scale=x[0],
        offset=(x[1], x[2]),
        rms_mm=round(rms, 1),
        max_mm=round(max(res), 1),
        used=tuple(sorted({a.label for a, _ in used})),
        n_vertical=n_v,
        n_horizontal=n_h,
        rejected=rejected,
    )
    if n_v < MIN_PER_DIRECTION or n_h < MIN_PER_DIRECTION:
        return None, (
            f"совпало осей: {n_v} одного направления и {n_h} другого; нужно не меньше "
            f"{MIN_PER_DIRECTION} каждого"
        )
    if fit.rms_mm > MAX_RMS_MM or fit.max_mm > MAX_RESIDUAL_MM:
        return (
            None,
            f"оси листа расходятся с сеткой модели: СКО {fit.rms_mm:.0f} мм, "
            f"максимум {fit.max_mm:.0f} мм",
        )
    if frame_scale is not None and frame_scale > 0:
        deviation = abs(fit.scale / frame_scale - 1.0)
        if deviation > MAX_SCALE_DEVIATION:
            return None, f"масштаб по осям расходится с масштабом листа на {deviation * 100:.1f} %"
    return fit, None


def sheet_axes(raw_walls: Any) -> list[SheetAxis]:
    """Оси вида из блока `axes` файла walls.json (pt страницы)."""
    block = raw_walls.get("axes") if isinstance(raw_walls, dict) else None
    items = block.get("items") if isinstance(block, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        label, orient, pos = item.get("label"), item.get("orient"), item.get("pos_pt")
        if (
            isinstance(label, str)
            and label.strip()
            and orient in ("vertical", "horizontal")
            and isinstance(pos, int | float)
            and not isinstance(pos, bool)
            and math.isfinite(pos)
        ):
            out.append(SheetAxis(label.strip(), str(orient), float(pos)))
    return out


def model_axes(raw_grids: Any) -> list[ModelAxis]:
    """Оси сетки модели из grids.json."""
    items = raw_grids.get("axes") if isinstance(raw_grids, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        try:
            p0 = (float(item["p0"][0]), float(item["p0"][1]))
            p1 = (float(item["p1"][0]), float(item["p1"][1]))
            tag = str(item["tag"])
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        if tag.strip() and math.dist(p0, p1) > 1.0:
            out.append(ModelAxis(tag.strip(), p0, p1))
    return out


def _overlaps(fit: SheetFit, model: Sequence[ModelAxis], bbox: Sequence[float] | None) -> bool:
    """Оси, по которым привязан лист, лежат в габарите этажа модели (с запасом 5 м)."""
    if not bbox or len(bbox) != 4:
        return True
    tags = {normalize_label(t) for t in fit.used}
    pts = [p for m in model if normalize_label(m.tag) in tags for p in (m.p0, m.p1)]
    if not pts:
        return False
    margin = 5000.0
    x0, y0 = min(p[0] for p in pts), min(p[1] for p in pts)
    x1, y1 = max(p[0] for p in pts), max(p[1] for p in pts)
    return not (
        x1 < bbox[0] - margin
        or x0 > bbox[2] + margin
        or y1 < bbox[1] - margin
        or y0 > bbox[3] + margin
    )


async def _read_json(storage: ObjectStorage, key: str, limit: int) -> Any:
    out = bytearray()
    async for chunk in storage.iter_stream(key):
        out += chunk
        if len(out) > limit:
            raise ValueError("файл больше допустимого")
    return json.loads(bytes(out).decode("utf-8"))


async def load_model_axes(
    storage: ObjectStorage, version: BuildingModelVersion
) -> list[ModelAxis] | None:
    """Сетка осей версии; части нет - None."""
    try:
        raw = await _read_json(
            storage, model_part_key(version.project_id, version.id, GRIDS_PATH), MAX_GRIDS_BYTES
        )
    except ObjectNotFoundError:
        return None
    return model_axes(raw)


_DIGITS: Final = re.compile(r"\d+")
_STOREY_FLOOR: Final = re.compile(r"^\s*(-?\d+)\s*этаж", re.IGNORECASE)
_TITLE_FLOORS: Final = re.compile(r"План\w*\s+((?:-?\d+\s*(?:[,–-]|и)?\s*)+)\s*этаж", re.IGNORECASE)
_RANGE: Final = re.compile(r"^(-?\d+)\s*[–-]\s*(-?\d+)$")
# Этаж без номера (техэтаж, кровля, фундамент): лист по отметке паспорта не дальше этого.
ELEVATION_MATCH_MM: Final = 1500.0
# Сколько листов этажа читать и подгонять: остальные - хуже по совпадению.
MAX_CANDIDATES: Final = 8
CACHE_SECONDS: Final = 600.0
CACHE_LIMIT: Final = 512
_cache: dict[tuple[Any, ...], tuple[float, ModelSheetOverlayList]] = {}


def building_number(name: str | None) -> str | None:
    """Номер корпуса из подписи здания («Корпус 5», «5», «Корп. 5»); без номера - None."""
    if not name:
        return None
    found = _DIGITS.search(name)
    return found.group(0) if found else None


def storey_floor(name: str) -> int | None:
    """Номер этажа из имени этажа модели («17 этаж», «-2 этаж»); техэтаж, кровля - None."""
    found = _STOREY_FLOOR.match(name)
    return int(found.group(1)) if found else None


def title_floors(title: str | None) -> set[int]:
    """Этажи из названия листа: «План 5, 9, 13, 16 этажей», «План 5-12 этажей», «План -2 этажа»."""
    found = _TITLE_FLOORS.search(title or "")
    if found is None:
        return set()
    out: set[int] = set()
    for part in re.split(r",|\bи\b", found.group(1)):
        item = part.strip()
        span = _RANGE.match(item)
        if span is not None:
            a, b = int(span.group(1)), int(span.group(2))
            if 0 < b - a <= 60:
                out.update(range(a, b + 1))
        elif re.fullmatch(r"-?\d+", item):
            out.add(int(item))
    return out


@dataclass(frozen=True, slots=True)
class SheetMatch:
    """Лист-кандидат этажа: `rank` 0 - номер этажа в названии листа, 1 - в диапазоне этажей
    паспорта, 2 - по отметке паспорта (этаж без номера или лист без этажей)."""

    sheet: b3d.SheetRef
    rank: int
    distance_mm: float


def match_sheets(
    sheets: Iterable[b3d.SheetRef],
    *,
    building_name: str | None,
    storey_name: str,
    elevation_mm: float,
) -> list[SheetMatch]:
    """Листы плана того же здания, на которых есть этот этаж (по номеру, иначе по отметке)."""
    wanted_building = building_number(building_name)
    floor = storey_floor(storey_name)
    out: list[SheetMatch] = []
    for sheet in sheets:
        if sheet.walls_key is None:
            continue
        sheet_building = building_number(sheet.passport_building)
        if wanted_building is not None and sheet_building not in (None, wanted_building):
            continue
        if wanted_building is None and sheet_building is not None:
            continue  # стилобат, подземная часть: листы без номера корпуса
        distance = (
            abs(sheet.passport_elevation_mm - elevation_mm)
            if sheet.passport_elevation_mm is not None
            else math.inf
        )
        explicit = title_floors(sheet.stamp_title)
        if floor is not None and floor in explicit:
            rank = 0
        elif (
            floor is not None
            and not explicit
            and sheet.passport_floor_from is not None
            and sheet.passport_floor_to is not None
            and sheet.passport_floor_from <= floor <= sheet.passport_floor_to
        ):
            rank = 1
        elif distance <= ELEVATION_MATCH_MM and not (floor is not None and explicit):
            rank = 2
        else:
            continue
        out.append(SheetMatch(sheet, rank, distance))
    out.sort(key=lambda m: (m.rank, m.distance_mm, m.sheet.page_index, m.sheet.view))
    return out[:MAX_CANDIDATES]


def _ranges(values: Iterable[int]) -> str:
    """4, 5, 6, 9 -> «4-6, 9»."""
    items = sorted(set(values))
    out: list[str] = []
    i = 0
    while i < len(items):
        j = i
        while j + 1 < len(items) and items[j + 1] == items[j] + 1:
            j += 1
        out.append(str(items[i]) if i == j else f"{items[i]}-{items[j]}")
        i = j + 1
    return ", ".join(out)


def building_floors(sheets: Iterable[b3d.SheetRef], building_name: str | None) -> str:
    """Этажи, на которые у здания есть посчитанные листы плана (по названию листа и паспорту)."""
    wanted = building_number(building_name)
    floors: set[int] = set()
    for sheet in sheets:
        if sheet.walls_key is None:
            continue
        number = building_number(sheet.passport_building)
        if (wanted is None) != (number is None) or (wanted is not None and number != wanted):
            continue
        explicit = title_floors(sheet.stamp_title)
        if explicit:
            floors |= explicit
        elif sheet.passport_floor_from is not None and sheet.passport_floor_to is not None:
            floors |= set(range(sheet.passport_floor_from, sheet.passport_floor_to + 1))
    return _ranges(floors)


def _item(
    match: SheetMatch, fit: SheetFit | None, reason: str | None, frame_scale: float | None
) -> ModelSheetOverlayRead:
    sheet = match.sheet
    number = building_number(sheet.passport_building)
    return ModelSheetOverlayRead(
        revision_id=sheet.revision_id,
        document_id=sheet.document_id,
        job_id=sheet.job_id,
        page_index=sheet.page_index,
        view=sheet.view,
        label=sheet.stamp_title or sheet.label,
        group_label=f"Корп. {number}" if number else "Корпус не указан",
        base_z_mm=sheet.passport_elevation_mm,
        status="registered" if fit is not None else "unregistered",
        reason=reason,
        matrix=list(fit.matrix) if fit is not None else None,
        rotation_deg=fit.rotation_deg if fit is not None else None,
        scale_mm_per_pt=fit.scale if fit is not None else None,
        frame_scale_mm_per_pt=frame_scale,
        rms_mm=fit.rms_mm if fit is not None else None,
        max_mm=fit.max_mm if fit is not None else None,
        axes_used=list(fit.used) if fit is not None else [],
        axes_rejected=list(fit.rejected) if fit is not None else [],
    )


def _cached(key: tuple[Any, ...]) -> ModelSheetOverlayList | None:
    hit = _cache.get(key)
    if hit is None or time.monotonic() - hit[0] > CACHE_SECONDS:
        return None
    return hit[1]


def _remember(key: tuple[Any, ...], value: ModelSheetOverlayList) -> None:
    if len(_cache) >= CACHE_LIMIT:
        for old in sorted(_cache, key=lambda k: _cache[k][0])[: CACHE_LIMIT // 4]:
            _cache.pop(old, None)
    _cache[key] = (time.monotonic(), value)


async def storey_sheets(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    version: BuildingModelVersion,
    storey: ModelStorey,
) -> ModelSheetOverlayList:
    """Листы планов этажа модели (то же здание, тот же этаж) и их привязка к сетке осей версии.

    Листы - из базы (паспорт листа: корпус, этажи, отметка), без сборки «Здания»; читаются
    и подгоняются только кандидаты этажа. Итог помнится в процессе 10 минут: ключ - версия,
    этаж и файлы кандидатов (новый расчёт листа - новый ключ).
    """
    empty = ModelSheetOverlayList(
        storey_key=storey.storey_key, elevation_mm=storey.elevation_mm, items=[]
    )
    axes = await load_model_axes(storage, version)
    if not axes:
        return empty.model_copy(
            update={"message": "В версии модели нет сетки осей: чертёж привязать не к чему."}
        )
    sheets, _warnings, _slab = await b3d.collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    matches = match_sheets(
        sheets,
        building_name=getattr(storey, "building_name", None),
        storey_name=storey.name,
        elevation_mm=storey.elevation_mm,
    )
    if not matches:
        have = building_floors(sheets, getattr(storey, "building_name", None))
        tail = f" У здания посчитаны листы этажей: {have}." if have else ""
        return empty.model_copy(
            update={"message": f"Листов плана этого этажа среди посчитанных листов CAD нет.{tail}"}
        )
    key = (
        version.id,
        storey.storey_key,
        tuple((m.sheet.walls_key, m.sheet.scale_key, m.sheet.checks_key) for m in matches),
    )
    cached = _cached(key)
    if cached is not None:
        return cached
    gate = asyncio.Semaphore(b3d.READ_CONCURRENCY)

    async def register(match: SheetMatch) -> tuple[SheetMatch, ModelSheetOverlayRead] | None:
        raw, problem = await b3d._read_walls(storage, match.sheet, gate)
        if raw is None:
            why = problem.message if problem else "конструкции вида не читаются"
            return match, _item(match, None, why, None)
        frame, _cacheable = await b3d._read_frame(storage, match.sheet, gate)
        frame_scale = frame.mm_per_pdf_point if frame.confirmed else None
        fit, reason = fit_sheet(sheet_axes(raw), axes, frame_scale)
        if fit is not None and not _overlaps(fit, axes, storey.bbox_mm):
            return None  # оси листа - другого здания
        if fit is None and not _pairs(sheet_axes(raw), axes):
            return None  # оси листа к этой модели не относятся
        return match, _item(match, fit, reason, frame_scale)

    gathered = await asyncio.gather(*(register(m) for m in matches))
    results = [r for r in gathered if r is not None]
    registered = [r for r in results if r[1].status == "registered"]
    best_rank = min((m.rank for m, _ in (registered or results)), default=0)
    # лучшие по совпадению этажа; не привязанные - только того же уровня совпадения
    items = sorted((i for m, i in registered if m.rank == best_rank), key=lambda i: i.rms_mm or 0.0)
    items += [i for m, i in results if i.status != "registered" and m.rank == best_rank]
    message = None if items else "Листы этажа есть, но их оси не относятся к сетке этой модели."
    out = ModelSheetOverlayList(
        storey_key=storey.storey_key, elevation_mm=storey.elevation_mm, items=items, message=message
    )
    _remember(key, out)
    log.info("model_sheets", storey=storey.storey_key, candidates=len(matches), **summarize(items))
    return out


def summarize(items: Iterable[ModelSheetOverlayRead]) -> dict[str, int]:
    """Сколько листов привязано и сколько нет (для журнала)."""
    out = {"registered": 0, "unregistered": 0}
    for item in items:
        out[item.status] += 1
    return out
