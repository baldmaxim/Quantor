"""Вид результата CAD: типизированная диагностика из JSON-артефактов попытки.

Сервер сам читает `scale.json`, `cad_checks.json`, `checks.json` и `preview.json` текущей
попытки и отдаёт только перечисленные поля. Сырой отчёт движка в интерфейс не попадает:
ни HTML, ни скрипты, ни пути. Все числа — то, что записал движок; сервер их не пересчитывает,
кроме вывода причин HOLD из тех же полей.
"""

from __future__ import annotations

import json
import math
from typing import Any, Final

from app.contracts.cad import (
    CadChecksRead,
    CadFrameRead,
    CadScaleControlRead,
    CadScaleRead,
)
from app.services import cad as cad_service
from app.storage.base import ObjectStorage

# Статус масштаба в scale.json: `passed|needs_review|failed` (движок после ADR-0036) и прежний
# `dimension_checks_passed` — артефакты уже выполненных заданий читаются как раньше.
SCALE_PASSED: Final = "dimension_checks_passed"
SCALE_PASSED_STATUSES: Final = frozenset({"passed", SCALE_PASSED})
OPERATOR_SOURCE: Final = "operator_calibration"


def _tolerances(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key)[:48]: number for key, item in value.items() if (number := _num(item)) is not None
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class ArtifactTooLargeError(Exception):
    pass


async def read_json(storage: ObjectStorage, key: str) -> Any:
    """JSON-артефакт целиком в память — только в пределах MAX_JSON_ARTIFACT_BYTES."""
    stat = await storage.stat(key)
    if stat.size > cad_service.MAX_JSON_ARTIFACT_BYTES:
        raise ArtifactTooLargeError(key)
    chunks: list[bytes] = []
    size = 0
    async for chunk in storage.iter_stream(key):
        size += len(chunk)
        if size > cad_service.MAX_JSON_ARTIFACT_BYTES:
            raise ArtifactTooLargeError(key)
        chunks.append(chunk)
    return json.loads(b"".join(chunks))


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    return value if type(value) is int else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _point(value: Any) -> tuple[float, float] | None:
    if isinstance(value, list) and len(value) == 2:
        x, y = _num(value[0]), _num(value[1])
        if x is not None and y is not None:
            return (x, y)
    return None


def hold_reasons(raw: dict[str, Any]) -> list[str]:
    """Почему масштаб не подтверждён. Только по полям проверки движка, без догадок."""
    if raw.get("status") in SCALE_PASSED_STATUSES:
        return []
    reasons: list[str] = []
    reason = raw.get("reason")
    if isinstance(reason, str) and reason.strip():
        reasons.append(reason.strip()[:400])
    controls = _as_list(raw.get("controls"))
    fit, held = _int(raw.get("fit_controls")) or 0, _int(raw.get("heldout_controls")) or 0
    if not controls:
        reasons.append(
            "Не найдено размерных цепочек с числовыми подписями, связанных с засечками: "
            "подобрать масштаб не по чему."
        )
    elif fit == 0:
        reasons.append("Нет контролей подбора масштаба (fit).")
    if controls and held == 0:
        reasons.append(
            "Нет независимой проверки (holdout): масштаб без проверки на отдельных цепочках "
            "не подтверждается."
        )
    outside = sum(
        1 for row in controls if isinstance(row, dict) and row.get("within_tolerance") is False
    )
    if outside:
        reasons.append(f"Контролей вне допуска: {outside}.")
    conflicts = _len(raw.get("anchored_conflicts"))
    if conflicts:
        reasons.append(f"Конфликтов привязки подписей к цепочкам: {conflicts}.")
    if raw.get("printed_scale_consistent") is False:
        reasons.append("Напечатанный масштаб не согласуется с подобранным по размерам.")
    if raw.get("fit_and_holdout_chains_disjoint") is False:
        reasons.append("Цепочки подбора и проверки пересекаются: проверка не независима.")
    if raw.get("independent_axes") is False:
        reasons.append("Контроли только по одной оси.")
    labels = raw.get("printed_scale_labels")
    if isinstance(labels, list) and labels and not controls:
        reasons.append(
            "Надпись масштаба на листе есть, но по ней масштаб не принимается: нужно "
            "подтверждение размерными цепочками (автоопределение масштаба по надписи запрещено)."
        )
    unassociated = _len(raw.get("unassociated_numeric_labels"))
    if unassociated:
        reasons.append(f"Числовых подписей без размерной цепочки: {unassociated}.")
    if not reasons:
        reasons.append(f"Движок вернул статус проверки «{raw.get('status')}» без подробностей.")
    return reasons


def scale_from(raw: Any) -> CadScaleRead | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("status"), str):
        return None
    controls: list[CadScaleControlRead] = []
    for row in _as_list(raw.get("controls")):
        if not isinstance(row, dict):
            continue
        ends = _as_list(row.get("endpoints_pt"))
        points = [p for p in (_point(end) for end in ends) if p is not None]
        controls.append(
            CadScaleControlRead(
                chain_id=_int(row.get("chain_id")),
                role=str(row.get("role", ""))[:16],
                label_mm=_num(row.get("label_mm")),
                length_pt=_num(row.get("length_pt")),
                fitted_measured_mm=_num(row.get("fitted_measured_mm")),
                residual_mm=_num(row.get("residual_mm")),
                tolerance_mm=_num(row.get("tolerance_mm")),
                within_tolerance=_bool(row.get("within_tolerance")),
                axis_angle_deg=_num(row.get("axis_angle_deg")),
                endpoints_pt=points[:2],
            )
        )
    labels = raw.get("printed_scale_labels")
    crop = raw.get("source_context_crop_pdf_display_pt")
    crop_values = [_num(v) for v in crop] if isinstance(crop, list) and len(crop) == 4 else None
    passed = raw["status"] in SCALE_PASSED_STATUSES
    source = str(raw["source"])[:48] if isinstance(raw.get("source"), str) else None
    operator_factor = _num(raw.get("operator_mm_per_pt"))
    reason = raw.get("reason")
    return CadScaleRead(
        status=raw["status"][:64],
        passed=passed,
        source=source,
        operator_mm_per_pt=operator_factor,
        dimension_mm_per_pt=_num(raw.get("dimension_mm_per_pt")),
        deviation=_num(raw.get("deviation")),
        tolerances=_tolerances(raw.get("tolerances")),
        reason=reason.strip()[:400] if isinstance(reason, str) and reason.strip() else None,
        method=str(raw["method"])[:96] if isinstance(raw.get("method"), str) else None,
        # Масштаб оператора — тот, по которому построен DXF; подбор по цепочкам — лишь проверка.
        mm_per_pdf_point=operator_factor
        if source == OPERATOR_SOURCE and operator_factor is not None
        else _num(raw.get("mm_per_pdf_point_fitted")),
        scale_denominator=_num(raw.get("scale_denominator_fitted")),
        printed_scale_labels=[v for v in (_num(x) for x in labels) if v is not None]
        if isinstance(labels, list)
        else [],
        printed_scale_consistent=_bool(raw.get("printed_scale_consistent")),
        fit_controls=_int(raw.get("fit_controls")) or 0,
        heldout_controls=_int(raw.get("heldout_controls")) or 0,
        fit_chains=_int(raw.get("fit_chains")),
        heldout_chains=_int(raw.get("heldout_chains")),
        fit_and_holdout_chains_disjoint=_bool(raw.get("fit_and_holdout_chains_disjoint")),
        independent_axes=_bool(raw.get("independent_axes")),
        anchored_conflicts=_len(raw.get("anchored_conflicts")),
        unassociated_numeric_labels=_len(raw.get("unassociated_numeric_labels")),
        release_allowed=raw.get("release_allowed") is True,
        controls=controls,
        hold_reasons=hold_reasons(raw),
        context_crop_pt=[v for v in crop_values if v is not None]
        if crop_values and all(v is not None for v in crop_values)
        else None,
    )


def frame_from(scale: CadScaleRead | None, cad_checks: Any) -> CadFrameRead:
    """Кадр DXF -> PDF. Без пригодного масштаба и начала координат — не подтверждён.

    Пригоден масштаб, прошедший проверку (`passed`), и масштаб оператора со статусом
    `needs_review`: DXF построен по калибровке человека, расхождение показывается отдельно.
    """
    origin = (
        _point(cad_checks.get("origin_pdf_display_pt")) if isinstance(cad_checks, dict) else None
    )
    units = cad_checks.get("units") if isinstance(cad_checks, dict) else None
    factor = scale.mm_per_pdf_point if scale else None
    reason: str | None = None
    if cad_checks is None:
        reason = "DXF в этой попытке нет: сравнивать с PDF нечего."
    elif scale is None or not (
        scale.passed or (scale.status == "needs_review" and scale.source == OPERATOR_SOURCE)
    ):
        reason = "Масштаб не подтверждён размерной проверкой: кадр координат не установлен."
    elif units != "mm":
        reason = "Единицы DXF не указаны как мм."
    elif origin is None:
        reason = "Движок не указал начало координат DXF на странице PDF."
    elif factor is None or factor <= 0:
        reason = "Нет подобранного коэффициента мм на точку PDF."
    return CadFrameRead(
        confirmed=reason is None,
        reason=reason,
        units=units if isinstance(units, str) else None,
        origin_pt=origin,
        mm_per_pdf_point=factor,
    )


def checks_from(cad_checks: Any, checks: Any) -> CadChecksRead | None:
    if not isinstance(cad_checks, dict) and not isinstance(checks, dict):
        return None
    cad = cad_checks if isinstance(cad_checks, dict) else {}
    view = checks if isinstance(checks, dict) else {}
    layers_raw = _as_dict(cad.get("layers"))
    layers = {str(name)[:48]: count for name, count in layers_raw.items() if type(count) is int}
    fills = _as_dict(view.get("fills"))
    doors = _as_dict(view.get("doors"))
    rooms = _as_dict(view.get("rooms"))
    return CadChecksRead(
        audit_errors=_int(cad.get("audit_errors")),
        layers=layers,
        door_block_inserts=_int(cad.get("door_block_inserts")),
        gate_block_inserts=_int(cad.get("gate_block_inserts")),
        source_fill_count=_int(fills.get("source_fill_count")),
        recognized_monolith_fill_count=_int(fills.get("recognized_monolith_fill_count")),
        door_block_count=_int(doors.get("door_block_count")),
        rooms_schedule_rows=_int(rooms.get("schedule_rows")),
        rooms_recognized_rows=_int(rooms.get("recognized_rows")),
        region_approved=_bool(view.get("region_approved")),
        all_source_fills_valid=_bool(view.get("all_source_fills_valid")),
        # Выпуск количеств в QA-контуре закрыт; true из отчёта всё равно показывается как есть.
        quantity_release_allowed=cad.get("quantity_release_allowed") is True
        or view.get("quantity_release_allowed") is True,
    )
