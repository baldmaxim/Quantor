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
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.model_sheets import ModelSheetOverlayList, ModelSheetOverlayRead
from app.core.logging import get_logger
from app.models import BuildingModelVersion, ModelStorey
from app.services import cad_building3d as b3d
from app.services import cad_building3d_assembly
from app.storage.base import ObjectNotFoundError, ObjectStorage
from app.storage.keys import model_part_key

log = get_logger(__name__)

GRIDS_PATH: Final = "grids.json"
MAX_GRIDS_BYTES: Final = 8 * 1024 * 1024
# Отметка листа (верх плиты по паспорту) и отметка этажа модели расходятся на пирог пола и
# округление: дальше этого - другой этаж.
LEVEL_TOLERANCE_MM: Final = 600.0
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
        kept = list(pairs)
        for _ in range(3):
            rows = _rows(kept, theta)
            if len(rows) < 3:
                break
            x = _least_squares(rows)
            if x is None or x[0] <= 0:
                break
            res = _residuals(rows, x)
            used = [
                p
                for p in kept
                if _angle_gap((theta - 90.0 if p[0].orient == "vertical" else theta), p[1].angle)
                <= PARALLEL_DEG
            ]
            worst = max(res)
            if worst <= OUTLIER_MM:
                rms = math.sqrt(sum(r * r for r in res) / len(res))
                if best is None or (len(rows), -rms) > (best[0], -best[1]):
                    best = (len(rows), rms, theta, x, used)
                break
            drop = used[res.index(worst)]
            kept = [p for p in kept if p is not drop]
    if best is None:
        return None, "подписи осей листа не складываются в одно положение на сетке модели"
    _, rms, theta, x, used = best
    rows = _rows(used, theta)
    res = _residuals(rows, x)
    n_v = len({normalize_label(a.label) for a, _ in used if a.orient == "vertical"})
    n_h = len({normalize_label(a.label) for a, _ in used if a.orient == "horizontal"})
    fit = SheetFit(
        rotation_deg=round(theta % 360.0, 4),
        scale=x[0],
        offset=(x[1], x[2]),
        rms_mm=round(rms, 1),
        max_mm=round(max(res), 1),
        used=tuple(sorted({a.label for a, _ in used})),
        n_vertical=n_v,
        n_horizontal=n_h,
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


@dataclass(slots=True)
class _Candidate:
    floor: Any
    sheet: b3d.SheetRef
    labels: list[str] = field(default_factory=list)


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


def _item(
    floor: Any, fit: SheetFit | None, reason: str | None, frame_scale: float | None
) -> ModelSheetOverlayRead:
    return ModelSheetOverlayRead(
        revision_id=floor.revision_id,
        document_id=floor.document_id,
        job_id=floor.job_id,
        page_index=floor.page_index,
        view=floor.view,
        label=floor.label,
        group_label=floor.group_label,
        base_z_mm=floor.base_z_mm,
        status="registered" if fit is not None else "unregistered",
        reason=reason,
        matrix=list(fit.matrix) if fit is not None else None,
        rotation_deg=fit.rotation_deg if fit is not None else None,
        scale_mm_per_pt=fit.scale if fit is not None else None,
        frame_scale_mm_per_pt=frame_scale,
        rms_mm=fit.rms_mm if fit is not None else None,
        max_mm=fit.max_mm if fit is not None else None,
        axes_used=list(fit.used) if fit is not None else [],
    )


async def storey_sheets(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    version: BuildingModelVersion,
    storey: ModelStorey,
) -> ModelSheetOverlayList:
    """Листы планов на отметке этажа модели и их привязка к сетке осей версии."""
    axes = await load_model_axes(storage, version)
    if not axes:
        return ModelSheetOverlayList(
            storey_key=storey.storey_key,
            elevation_mm=storey.elevation_mm,
            items=[],
            message="В версии модели нет сетки осей: чертёж привязать не к чему.",
        )
    building = await cad_building3d_assembly.build_building3d(
        session, storage, workspace_id=workspace_id, project_id=project_id, include_walls=False
    )
    sheets, _warnings, _slab = await b3d.collect_sheets(
        session, workspace_id=workspace_id, project_id=project_id
    )
    by_address = {(s.job_id, s.page_index, s.view): s for s in sheets}
    seen: set[tuple[uuid.UUID, int, int]] = set()
    candidates: list[_Candidate] = []
    unknown = 0
    for floor in building.floors:
        address = (floor.job_id, floor.page_index, floor.view)
        if address in seen or address not in by_address:
            continue
        if not floor.elevation_known:
            unknown += 1
            continue
        if abs(floor.base_z_mm - storey.elevation_mm) > LEVEL_TOLERANCE_MM:
            continue
        seen.add(address)
        candidates.append(_Candidate(floor, by_address[address]))
    gate = asyncio.Semaphore(b3d.READ_CONCURRENCY)

    async def register(candidate: _Candidate) -> ModelSheetOverlayRead | None:
        raw, problem = await b3d._read_walls(storage, candidate.sheet, gate)
        if raw is None:
            return _item(
                candidate.floor,
                None,
                problem.message if problem else "конструкции вида не читаются",
                None,
            )
        frame, _cacheable = await b3d._read_frame(storage, candidate.sheet, gate)
        frame_scale = frame.mm_per_pdf_point if frame.confirmed else None
        fit, reason = fit_sheet(sheet_axes(raw), axes, frame_scale)
        if fit is not None and not _overlaps(fit, axes, storey.bbox_mm):
            return None  # лист другого корпуса на той же отметке
        if fit is None and not _pairs(sheet_axes(raw), axes):
            return None  # оси листа к этой модели не относятся
        return _item(candidate.floor, fit, reason, frame_scale)

    results = await asyncio.gather(*(register(c) for c in candidates))
    items = [r for r in results if r is not None]
    items.sort(key=lambda r: (r.status != "registered", r.rms_mm or 0.0, r.label))
    message = None
    if not items:
        message = "На отметке этажа нет листов плана с осями этой модели."
        if unknown:
            message += f" У {unknown} листов отметка не определена."
    return ModelSheetOverlayList(
        storey_key=storey.storey_key, elevation_mm=storey.elevation_mm, items=items, message=message
    )


def summarize(items: Iterable[ModelSheetOverlayRead]) -> dict[str, int]:
    """Сколько листов привязано и сколько нет (для журнала)."""
    out = {"registered": 0, "unregistered": 0}
    for item in items:
        out[item.status] += 1
    return out
