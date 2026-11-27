"""Координация осей: оси вида с устойчивыми идентификаторами и смещение по парам осей.

Чистые функции без ввода-вывода и без ИИ. Модель роли `coordination` сопоставляет оси по рисунку и
называет пары идентификаторов; смещение этажа считает этот модуль. Кадр и знак - как у совмещения
«Здания» (`cad_building3d._align_to`): оси в мм кадра вида (`axes_in_mm`), сдвиг `d = ось эталона -
ось цели`, `p_эталона = p_вида + offset` (поворот 0 градусов).
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from app.contracts.cad_ai_coordination import (
    AiCoordinationDropped,
    AiCoordinationPair,
    AiCoordinationReport,
    AiCoordinationUsedPair,
    CoordinationStatus,
)
from app.services.cad_building3d import AXIS_TOLERANCE_MM, CoordAxis

VERTICAL: Final = "vertical"
HORIZONTAL: Final = "horizontal"
# Согласных пар по каждому направлению (x по вертикальным осям, y по горизонтальным).
MIN_AGREED_PAIRS: Final = 2


def axes_fingerprint(axes: Sequence[CoordAxis]) -> str:
    """Отпечаток осей вида: хеш упорядоченного списка (id, подпись, направление, мм до 1 мм).

    Пары идентификаторов из координации применимы только к тем осям, для которых они названы:
    совпал отпечаток - идентификаторы указывают на те же оси (перестроенные конструкции с теми же
    осями дают тот же отпечаток).
    """
    rows = [[a.id, a.label, a.orient, round(a.pos_mm)] for a in axes]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Offset:
    """Итог расчёта: `ok` со сдвигом и использованными парами либо `rejected` с причиной."""

    status: CoordinationStatus
    reason: str | None
    offset_mm: tuple[float, float] | None
    used: list[AiCoordinationUsedPair]
    dropped: list[AiCoordinationDropped]


def sanitize_pairs(
    report: AiCoordinationReport,
    target: Sequence[CoordAxis],
    reference: Sequence[CoordAxis],
) -> tuple[list[tuple[AiCoordinationPair, CoordAxis, CoordAxis]], list[AiCoordinationDropped]]:
    """Пары ответа с осями пакета; чужие идентификаторы, повторы и разные направления - в
    `dropped`. Повтор: ось, уже вошедшая в пару, во вторую не берётся (первая пара остаётся)."""
    target_by_id = {axis.id: axis for axis in target}
    reference_by_id = {axis.id: axis for axis in reference}
    kept: list[tuple[AiCoordinationPair, CoordAxis, CoordAxis]] = []
    dropped: list[AiCoordinationDropped] = []
    used_target: set[str] = set()
    used_reference: set[str] = set()

    def drop(pair: AiCoordinationPair, reason: str) -> None:
        dropped.append(
            AiCoordinationDropped(
                target_axis_id=pair.target_axis_id,
                reference_axis_id=pair.reference_axis_id,
                reason=reason,
            )
        )

    for pair in report.pairs:
        first = target_by_id.get(pair.target_axis_id)
        second = reference_by_id.get(pair.reference_axis_id)
        if first is None or second is None:
            drop(pair, "идентификатор оси вне пакета")
        elif first.orient != second.orient:
            drop(pair, "оси разных направлений")
        elif pair.target_axis_id in used_target or pair.reference_axis_id in used_reference:
            drop(pair, "ось уже входит в другую пару")
        else:
            used_target.add(pair.target_axis_id)
            used_reference.add(pair.reference_axis_id)
            kept.append((pair, first, second))
    return kept, dropped


def _best_group(shifts: Sequence[float]) -> tuple[list[int], int]:
    """Индексы согласного большинства сдвигов и размер лучшей из остальных групп.

    Группа - сдвиги в пределах допуска от сдвига-опоры; берётся наибольшая (при равенстве - по
    порядку), затем состав уточняется по медиане группы.
    """

    def around(center: float, pool: Sequence[int]) -> list[int]:
        return [i for i in pool if abs(shifts[i] - center) <= AXIS_TOLERANCE_MM]

    everyone = list(range(len(shifts)))
    best: list[int] = []
    for i in everyone:
        group = around(shifts[i], everyone)
        if len(group) > len(best):
            best = group
    median = statistics.median(shifts[i] for i in best)
    agreed = around(median, everyone)
    rest = [i for i in everyone if i not in agreed]
    second = max((len(around(shifts[i], rest)) for i in rest), default=0)
    return agreed, second


def compute_offset(pairs: Sequence[tuple[AiCoordinationPair, CoordAxis, CoordAxis]]) -> Offset:
    """Смещение по парам осей; отказ, если по какому-то направлению нет двух согласных пар.

    Сдвиг пары - `ось эталона - ось цели`. По направлению берётся согласное большинство (в
    пределах `AXIS_TOLERANCE_MM` от медианы), смещение - медиана согласных. Несогласные пары идут в
    `dropped`. Две группы с общим сдвигом одного размера - неоднозначность, отказ.
    """
    used: list[AiCoordinationUsedPair] = []
    dropped: list[AiCoordinationDropped] = []
    offsets: dict[str, float] = {}
    problems: list[str] = []
    for orient, name in ((VERTICAL, "вертикальным"), (HORIZONTAL, "горизонтальным")):
        rows = [row for row in pairs if row[1].orient == orient]
        shifts = [ref.pos_mm - own.pos_mm for _, own, ref in rows]
        if len(rows) < MIN_AGREED_PAIRS:
            problems.append(f"по {name} осям пар меньше {MIN_AGREED_PAIRS}: {len(rows)}")
            dropped.extend(_unused(rows, "направление отклонено: пар слишком мало"))
            continue
        agreed, second = _best_group(shifts)
        if len(agreed) < MIN_AGREED_PAIRS or len(agreed) <= second:
            problems.append(
                f"по {name} осям нет согласных пар (нужно не меньше {MIN_AGREED_PAIRS}, "
                "большинство однозначно)"
            )
            dropped.extend(_unused(rows, "направление отклонено: пары расходятся"))
            continue
        shift = statistics.median(shifts[i] for i in agreed)
        offsets[orient] = shift
        for index, (pair, own, ref) in enumerate(rows):
            if index in agreed:
                used.append(
                    AiCoordinationUsedPair(
                        target_axis_id=own.id,
                        reference_axis_id=ref.id,
                        target_label=own.label,
                        reference_label=ref.label,
                        orient=own.orient,
                        confidence=pair.confidence,
                        evidence=pair.evidence,
                        target_mm=round(own.pos_mm, 1),
                        reference_mm=round(ref.pos_mm, 1),
                        shift_mm=round(shifts[index], 1),
                        residual_mm=round(shifts[index] - shift, 1),
                    )
                )
            else:
                dropped.append(
                    AiCoordinationDropped(
                        target_axis_id=own.id,
                        reference_axis_id=ref.id,
                        reason=(
                            f"сдвиг {shifts[index]:.0f} мм расходится с общим {shift:.0f} мм "
                            f"больше допуска {AXIS_TOLERANCE_MM:.0f} мм"
                        ),
                    )
                )
    if problems:
        return Offset("rejected", "; ".join(problems), None, [], dropped)
    return Offset(
        "ok",
        None,
        (round(offsets[VERTICAL], 1), round(offsets[HORIZONTAL], 1)),
        used,
        dropped,
    )


def _unused(
    rows: Sequence[tuple[AiCoordinationPair, CoordAxis, CoordAxis]], reason: str
) -> list[AiCoordinationDropped]:
    return [
        AiCoordinationDropped(target_axis_id=own.id, reference_axis_id=ref.id, reason=reason)
        for _, own, ref in rows
    ]


def axes_document(axes: Sequence[CoordAxis]) -> list[Mapping[str, str]]:
    """Оси для пакета модели: идентификатор, подпись и направление - без координат."""
    return [{"id": axis.id, "label": axis.label, "orient": axis.orient} for axis in axes]
