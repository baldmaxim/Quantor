"""Детерминированная оценка прогресса кругов ИИ-обводки CAD и перевод находок плиты в зоны.

Чистый сервисный модуль: без сетевых вызовов, без тяжёлых ML/PDF-зависимостей и без циклов импорта.
Метрики и оценка строятся только из фактов `walls.json` и отчёта ИИ; физические величины не
вычисляются.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.contracts.cad_ai_review import AiRender, AiReviewReport, AiReviewResult
from app.contracts.cad_zones import CadZoneCreate

ROUND_DIFF_SCHEMA: Final = "quantor.cad_ai_round_diff.v1"
_MAX_FAILED_HINTS: Final = 20
_MAX_HINT_CAP: Final = 20
_MAX_SLAB_ZONES: Final = 10
_SCORE_REGRESSION_DELTA: Final = 5.0


@dataclass(frozen=True, slots=True)
class WallsQualityScore:
    slab_has_zones: bool
    warnings_count: int
    constructions_count: int
    openings_count: int
    doors_count: int
    applied_hints: int
    no_candidate_hints: int
    score: float


@dataclass(frozen=True, slots=True)
class RoundProgress:
    status: Literal["improved", "stagnated", "regressed"]
    prev_score: float | None
    curr_score: float
    reasons: tuple[str, ...]


def _warnings_count(walls: Mapping[str, Any]) -> int:
    checks = walls.get("checks")
    if isinstance(checks, Mapping) and isinstance(checks.get("warnings"), list):
        return len(checks["warnings"])
    raw_warnings = walls.get("warnings")
    if isinstance(raw_warnings, list):
        return len(raw_warnings)
    return 0


def _score_to_dict(snapshot: WallsQualityScore) -> dict[str, Any]:
    return {
        "slab_has_zones": snapshot.slab_has_zones,
        "warnings_count": snapshot.warnings_count,
        "constructions_count": snapshot.constructions_count,
        "openings_count": snapshot.openings_count,
        "doors_count": snapshot.doors_count,
        "applied_hints": snapshot.applied_hints,
        "no_candidate_hints": snapshot.no_candidate_hints,
        "score": snapshot.score,
    }


def _merged_hints_applied(
    walls: Mapping[str, Any],
    convert_checks: Mapping[str, Any] | None = None,
) -> list[Mapping[str, Any]]:
    """Объединяет `hints_applied` из `walls.json` и `checks.json` без дублей по `id`."""
    merged: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    for source in (walls, convert_checks):
        if source is None:
            continue
        raw = source.get("hints_applied")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            raw_id = item.get("id")
            hint_id = raw_id if isinstance(raw_id, str) and raw_id else None
            if hint_id is not None:
                if hint_id in seen_ids:
                    continue
                seen_ids.add(hint_id)
            merged.append(item)
    return merged


def score_walls_snapshot(
    walls: Mapping[str, Any],
    convert_checks: Mapping[str, Any] | None = None,
) -> WallsQualityScore:
    """Детерминированная сводка качества снимка `walls.json` (с учётом `checks.json` конвертера)."""
    slab = walls.get("slab")
    slab_has_zones = isinstance(slab, Mapping) and slab.get("basis") == "zones"

    warnings_count = _warnings_count(walls)

    raw_constructions = walls.get("constructions")
    constructions_count = len(raw_constructions) if isinstance(raw_constructions, list) else 0

    raw_openings = walls.get("openings")
    openings_list = raw_openings if isinstance(raw_openings, list) else []
    openings_count = len(openings_list)
    doors_count = sum(
        1 for item in openings_list if isinstance(item, Mapping) and item.get("kind") == "door"
    )

    hints_list = _merged_hints_applied(walls, convert_checks)
    applied_hints = sum(1 for item in hints_list if item.get("status") == "applied")
    no_candidate_hints = sum(1 for item in hints_list if item.get("status") == "no_candidate")

    base = (
        (25.0 if slab_has_zones else 0.0)
        + (5.0 if doors_count > 0 else 0.0)
        + min(applied_hints, _MAX_HINT_CAP) * 2.0
        - warnings_count * 3.0
        - min(no_candidate_hints, _MAX_HINT_CAP) * 0.5
    )
    return WallsQualityScore(
        slab_has_zones=slab_has_zones,
        warnings_count=warnings_count,
        constructions_count=constructions_count,
        openings_count=openings_count,
        doors_count=doors_count,
        applied_hints=applied_hints,
        no_candidate_hints=no_candidate_hints,
        score=round(base, 2),
    )


def check_round_progress(
    prev_walls: Mapping[str, Any] | None,
    curr_walls: Mapping[str, Any],
    convert_checks: Mapping[str, Any] | None = None,
    *,
    prev_convert_checks: Mapping[str, Any] | None = None,
) -> RoundProgress:
    """Сравнивает текущий снимок `walls.json` с предыдущим кругом."""
    curr = score_walls_snapshot(curr_walls, convert_checks=convert_checks)
    if prev_walls is None:
        return RoundProgress("improved", None, curr.score, ("initial_round",))
    prev = score_walls_snapshot(prev_walls, convert_checks=prev_convert_checks)
    if prev.slab_has_zones and not curr.slab_has_zones:
        return RoundProgress("regressed", prev.score, curr.score, ("slab_lost_zones",))
    if curr.applied_hints == 0 and curr.no_candidate_hints > 0 and curr.score <= prev.score:
        return RoundProgress("stagnated", prev.score, curr.score, ("all_hints_no_candidate",))
    if curr.score < prev.score - _SCORE_REGRESSION_DELTA:
        return RoundProgress("regressed", prev.score, curr.score, ("quality_score_dropped",))
    return RoundProgress("improved", prev.score, curr.score, ("ok",))


def build_prev_round_diff(
    current_walls: Mapping[str, Any],
    prev_walls: Mapping[str, Any] | None,
    prev_review: AiReviewResult | None,
    convert_checks: Mapping[str, Any] | None = None,
    *,
    prev_convert_checks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Строит компактный JSON-отчёт изменений между кругами для пакета ИИ-проверки."""
    hints_items = _merged_hints_applied(current_walls, convert_checks)
    applied_count = sum(1 for item in hints_items if item.get("status") == "applied")
    no_candidate_count = sum(1 for item in hints_items if item.get("status") == "no_candidate")
    failed: list[dict[str, str]] = []
    for item in hints_items:
        status = str(item.get("status") or "")
        if status == "applied":
            continue
        failed.append(
            {
                "id": str(item.get("id") or ""),
                "type": str(item.get("type") or ""),
                "status": status,
                "reason": str(item.get("reason") or "")[:200],
            }
        )
        if len(failed) >= _MAX_FAILED_HINTS:
            break

    progress = check_round_progress(
        prev_walls,
        current_walls,
        convert_checks=convert_checks,
        prev_convert_checks=prev_convert_checks,
    )
    curr_s = score_walls_snapshot(current_walls, convert_checks=convert_checks)
    prev_s = (
        score_walls_snapshot(prev_walls, convert_checks=prev_convert_checks)
        if prev_walls is not None
        else None
    )

    prev_summary: dict[str, int] | None = None
    if prev_review is not None:
        prev_summary = {
            "findings": len(prev_review.report.findings),
            "slab_findings": len(prev_review.report.slab_findings),
            "props": len(prev_review.report.props),
        }

    return {
        "schema": ROUND_DIFF_SCHEMA,
        "prev_iteration": prev_review.iteration if prev_review is not None else None,
        "prev_verdict": prev_review.report.verdict if prev_review is not None else None,
        "prev_summary": prev_summary,
        "hints_summary": {
            "total": len(hints_items),
            "applied": applied_count,
            "no_candidate": no_candidate_count,
            "failed": failed,
        },
        "metrics": {
            "current": _score_to_dict(curr_s),
            "previous": _score_to_dict(prev_s) if prev_s is not None else None,
        },
        "progress": {
            "status": progress.status,
            "prev_score": progress.prev_score,
            "curr_score": progress.curr_score,
            "reasons": list(progress.reasons),
        },
    }


def slab_findings_to_zone_creates(
    report: AiReviewReport,
    render: AiRender,
    *,
    page_width_pt: float,
    page_height_pt: float,
    revision_id: uuid.UUID,
    page_index: int,
) -> list[CadZoneCreate]:
    """Переводит находки `slab_missing_area` в прямоугольные зоны МОП (нормализованные)."""
    if (
        not math.isfinite(page_width_pt)
        or not math.isfinite(page_height_pt)
        or page_width_pt <= 0
        or page_height_pt <= 0
    ):
        return []
    if (
        len(render.clip) != 4
        or not all(math.isfinite(val) for val in render.clip)
        or not math.isfinite(render.zoom)
        or render.zoom <= 0
    ):
        return []

    cx0, cy0 = render.clip[0], render.clip[1]
    zoom = render.zoom
    zones: list[CadZoneCreate] = []
    for finding in report.slab_findings:
        if finding.kind != "slab_missing_area":
            continue
        bbox = finding.bbox_px
        if len(bbox) != 4 or not all(math.isfinite(val) for val in bbox):
            continue
        bx0, by0, bx1, by1 = bbox
        if bx1 <= bx0 or by1 <= by0:
            continue

        x0_pt = cx0 + bx0 / zoom
        y0_pt = cy0 + by0 / zoom
        x1_pt = cx0 + bx1 / zoom
        y1_pt = cy0 + by1 / zoom

        x0 = min(max(x0_pt / page_width_pt, 0.0), 1.0)
        y0 = min(max(y0_pt / page_height_pt, 0.0), 1.0)
        x1 = min(max(x1_pt / page_width_pt, 0.0), 1.0)
        y1 = min(max(y1_pt / page_height_pt, 0.0), 1.0)
        if x0 >= x1 or y0 >= y1:
            continue

        zones.append(
            CadZoneCreate(
                revision_id=revision_id,
                page_index=page_index,
                kind="room_mop",
                room_type="mop_other",
                name=f"ИИ-зона плиты: {finding.observation[:60]}",
                room_mark="ИИ-ПЛ",
                points=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            )
        )
        if len(zones) >= _MAX_SLAB_ZONES:
            break
    return zones
