"""Совмещение плана с уровнем по маркам осей (ADR-0043 п. 5, этап С3): `consistency.align.v1`.

Система координат уровня - система координат эталонного плана АР секции: у этажей секции одна
сетка осей, поэтому план любого раздела и любого уровня секции переводится в неё одним
преобразованием `точка уровня = R(поворот) · точка листа + (dx, dy)`, где точка листа - мм DXF
вида CAD. Поворот - кратный 90°, сдвиг по каждому направлению - медиана разностей согласного
большинства общих марок (тесные промежуточные оси на выносках сдвинуты, главные совпадают; так же
совмещает этажи 3D здания). Невязка - отклонения согласных марок от сдвига. Масштаб берётся из
кадра вида CAD: калибровка человеком или размерные цепочки движка (поправка 2026-11-15 к п. 5);
масштаб не от калибровки делает итог «проверить».

Модуль чистый: оси уже переведены в мм вызывающим; БД, хранилище и CAD не импортируются.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

ALIGN_VERSION: Final = "consistency.align.v1"

# Марки с разностью в пределах допуска считаются одним сдвигом (как у этажей 3D здания).
AXIS_AGREE_MM: Final = 150.0
# Среднеквадратичная невязка согласных марок выше порога - итог «проверить».
RESIDUAL_CHECK_MM: Final = 50.0
ROTATIONS: Final = (0, 90, 180, 270)
AXES_LISTED_MAX: Final = 12


class AlignResult(StrEnum):
    REFERENCE = "reference"  # эталон секции: задаёт систему координат уровня
    ALIGNED = "aligned"
    CHECK = "check"  # совмещён, но есть причина проверить
    FAILED = "failed"  # оси есть, общего сдвига нет
    NOT_RUN = "not_run"  # нечего совмещать: нет CAD, осей, кадра или эталона


class AlignScaleSource(StrEnum):
    CALIBRATION = "calibration"  # калибровка листа человеком
    DIMENSION_CHAINS = "dimension_chains"  # подбор движка по размерным цепочкам (ADR-0045)


@dataclass(frozen=True, slots=True)
class SheetAxes:
    """Оси вида листа в мм DXF: подпись -> x вертикальной оси или y горизонтальной.

    `problem` - почему вид совмещать нечем (нет CAD, конструкций, кадра, осей одного направления).
    """

    key: str
    is_ar: bool
    vertical: dict[str, float]
    horizontal: dict[str, float]
    scale_source: AlignScaleSource | None
    problem: str | None = None

    @property
    def usable(self) -> bool:
        return self.problem is None and bool(self.vertical) and bool(self.horizontal)

    @property
    def axis_count(self) -> int:
        return len(self.vertical) + len(self.horizontal)


@dataclass(frozen=True, slots=True)
class Alignment:
    key: str
    result: AlignResult
    reference_key: str | None = None
    rotation_deg: int | None = None
    dx_mm: float | None = None
    dy_mm: float | None = None
    axes: tuple[str, ...] = ()  # согласные марки: сначала вертикальные, затем горизонтальные
    common_axes: int = 0
    agreed_axes: int = 0
    residual_rms_mm: float | None = None
    residual_max_mm: float | None = None
    reasons: tuple[str, ...] = ()


# --------------------------------------------------------------------------- оси


def _natural_key(text: str) -> list[tuple[int, int, str]]:
    return [
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in re.split(r"(\d+)", text)
        if part
    ]


def rotate_axes(
    vertical: dict[str, float], horizontal: dict[str, float], rotation: int
) -> tuple[dict[str, float], dict[str, float]]:
    """Оси после поворота листа на `rotation` градусов против часовой стрелки.

    Поворот на 90°: `(x, y) -> (-y, x)`, вертикаль `x = a` становится горизонталью `y = a`, а
    горизонталь `y = b` - вертикалью `x = -b`.
    """
    if rotation == 0:
        return dict(vertical), dict(horizontal)
    if rotation == 90:
        return {k: -v for k, v in horizontal.items()}, dict(vertical)
    if rotation == 180:
        return {k: -v for k, v in vertical.items()}, {k: -v for k, v in horizontal.items()}
    if rotation == 270:
        return dict(horizontal), {k: -v for k, v in vertical.items()}
    raise ValueError(f"поворот не кратен 90°: {rotation}")


def rotate_point(x: float, y: float, rotation: int) -> tuple[float, float]:
    if rotation == 0:
        return x, y
    if rotation == 90:
        return -y, x
    if rotation == 180:
        return -x, -y
    if rotation == 270:
        return y, -x
    raise ValueError(f"поворот не кратен 90°: {rotation}")


# --------------------------------------------------------------------------- одно направление


@dataclass(frozen=True, slots=True)
class _Direction:
    shift: float
    agreed: tuple[str, ...]
    common: tuple[str, ...]
    residuals: tuple[float, ...]


def _agreed(diffs: dict[str, float]) -> tuple[list[str], int]:
    """Наибольшая группа марок с одним сдвигом и размер следующей за ней группы."""
    labels = sorted(diffs, key=_natural_key)

    def around(center: str, pool: Sequence[str]) -> list[str]:
        return [m for m in pool if abs(diffs[m] - diffs[center]) <= AXIS_AGREE_MM]

    best: list[str] = []
    for label in labels:
        group = around(label, labels)
        if len(group) > len(best):
            best = group
    rest = [label for label in labels if label not in best]
    second = max((len(around(label, rest)) for label in rest), default=0)
    return best, second


def _direction(reference: dict[str, float], other: dict[str, float], name: str) -> _Direction | str:
    """Сдвиг по направлению по согласному большинству или причина отказа.

    Группа согласных марок не меньше чем вдвое больше следующей, а при двух и более общих марках
    в ней не меньше двух: две марки против двух с другим сдвигом - неоднозначность.
    """
    common = sorted(reference.keys() & other.keys(), key=_natural_key)
    if not common:
        return f"нет общих {name} осей с эталоном"
    diffs = {label: reference[label] - other[label] for label in common}
    agreed, second = _agreed(diffs)
    if (
        len(agreed) < max(2 * second, 1)
        or len(agreed) == second
        or (len(diffs) >= 2 and len(agreed) < 2)
    ):
        return f"{name} оси расходятся с эталоном: {', '.join(common[:AXES_LISTED_MAX])}"
    shift = statistics.median(diffs[label] for label in agreed)
    return _Direction(
        shift=shift,
        agreed=tuple(agreed),
        common=tuple(common),
        residuals=tuple(diffs[label] - shift for label in agreed),
    )


# --------------------------------------------------------------------------- лист к эталону


def _scale_reason(sheet: SheetAxes, whose: str) -> str | None:
    if sheet.scale_source is AlignScaleSource.CALIBRATION:
        return None
    if sheet.scale_source is AlignScaleSource.DIMENSION_CHAINS:
        return f"масштаб {whose} подобран по размерным цепочкам, а не калибровкой человеком"
    return f"источник масштаба {whose} не известен"


def match(reference: SheetAxes, other: SheetAxes) -> Alignment:
    """Совмещение вида с эталоном: лучший поворот (больше согласных марок, при равенстве - 0°)."""
    best: tuple[int, int, _Direction, _Direction] | None = None
    straight: list[str] = []
    for rotation in ROTATIONS:
        vertical, horizontal = rotate_axes(other.vertical, other.horizontal, rotation)
        along_x = _direction(reference.vertical, vertical, "вертикальных")
        along_y = _direction(reference.horizontal, horizontal, "горизонтальных")
        if isinstance(along_x, str) or isinstance(along_y, str):
            if rotation == 0:
                straight = [m for m in (along_x, along_y) if isinstance(m, str)]
            continue
        agreed = len(along_x.agreed) + len(along_y.agreed)
        if best is None or agreed > best[1]:
            best = (rotation, agreed, along_x, along_y)
    if best is None:
        return Alignment(
            key=other.key,
            result=AlignResult.FAILED,
            reference_key=reference.key,
            reasons=tuple(straight),
        )
    rotation, agreed, along_x, along_y = best
    residuals = [*along_x.residuals, *along_y.residuals]
    rms = math.sqrt(sum(value * value for value in residuals) / len(residuals))
    worst = max(abs(value) for value in residuals)
    reasons: list[str] = []
    if rotation != 0:
        reasons.append(f"план повёрнут относительно эталона на {rotation}°")
    if rms > RESIDUAL_CHECK_MM:
        reasons.append(f"невязка {rms:.0f} мм больше порога {RESIDUAL_CHECK_MM:.0f} мм")
    for direction, name in ((along_x, "вертикальных"), (along_y, "горизонтальных")):
        if len(direction.agreed) < 2:
            reasons.append(f"совпала одна из {name} осей: невязку по ней не проверить")
        apart = [label for label in direction.common if label not in direction.agreed]
        if apart:
            reasons.append(
                f"{name} оси расходятся с остальными: {', '.join(apart[:AXES_LISTED_MAX])}"
            )
    for sheet, whose in ((reference, "эталона"), (other, "листа")):
        reason = _scale_reason(sheet, whose)
        if reason is not None:
            reasons.append(reason)
    return Alignment(
        key=other.key,
        result=AlignResult.CHECK if reasons else AlignResult.ALIGNED,
        reference_key=reference.key,
        rotation_deg=rotation,
        dx_mm=along_x.shift,
        dy_mm=along_y.shift,
        axes=(*along_x.agreed, *along_y.agreed),
        common_axes=len(along_x.common) + len(along_y.common),
        agreed_axes=agreed,
        residual_rms_mm=rms,
        residual_max_mm=worst,
        reasons=tuple(reasons),
    )


# --------------------------------------------------------------------------- секция


NO_REFERENCE: Final = "в секции нет плана АР с осями в обоих направлениях: эталона нет"


def pick_reference(sheets: Sequence[SheetAxes], preferred: str | None = None) -> int | None:
    """Эталон секции: указанный (подтверждённый ранее), иначе план АР с наибольшим числом осей.

    При равенстве - с калибровкой человеком, затем по ключу: итог не зависит от порядка входа.
    """
    usable = [i for i, sheet in enumerate(sheets) if sheet.is_ar and sheet.usable]
    for index in usable:
        if sheets[index].key == preferred:
            return index
    if not usable:
        return None
    return min(
        usable,
        key=lambda i: (
            -sheets[i].axis_count,
            sheets[i].scale_source is not AlignScaleSource.CALIBRATION,
            sheets[i].key,
        ),
    )


def align_section(sheets: Sequence[SheetAxes], preferred: str | None = None) -> list[Alignment]:
    """Совмещение видов одной секции с её эталоном; порядок итога - как у входа."""
    ref_index = pick_reference(sheets, preferred)
    reference = None if ref_index is None else sheets[ref_index]
    result: list[Alignment] = []
    for index, sheet in enumerate(sheets):
        if reference is not None and index == ref_index:
            reason = _scale_reason(sheet, "эталона")
            result.append(
                Alignment(
                    key=sheet.key,
                    result=AlignResult.REFERENCE,
                    reference_key=sheet.key,
                    rotation_deg=0,
                    dx_mm=0.0,
                    dy_mm=0.0,
                    common_axes=sheet.axis_count,
                    agreed_axes=sheet.axis_count,
                    reasons=() if reason is None else (reason,),
                )
            )
        elif not sheet.usable:
            problem = sheet.problem or "на виде нет осей обоих направлений"
            result.append(Alignment(key=sheet.key, result=AlignResult.NOT_RUN, reasons=(problem,)))
        elif reference is None:
            result.append(
                Alignment(key=sheet.key, result=AlignResult.NOT_RUN, reasons=(NO_REFERENCE,))
            )
        else:
            result.append(match(reference, sheet))
    return result
