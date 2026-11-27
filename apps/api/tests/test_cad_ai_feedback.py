"""Юнит-тесты детерминированной оценки кругов ИИ-обводки и перевода находок плиты в зоны."""

from __future__ import annotations

import uuid
from typing import Any

from app.contracts.cad_ai_review import (
    AiRender,
    AiReviewReport,
    AiReviewResult,
    AiSlabFinding,
    AiSourceCopy,
    AiUsage,
)
from app.services.cad_ai_feedback import (
    ROUND_DIFF_SCHEMA,
    build_prev_round_diff,
    check_round_progress,
    score_walls_snapshot,
    slab_findings_to_zone_creates,
)


def _sample_review(iteration: int = 1) -> AiReviewResult:
    return AiReviewResult(
        walls_job_id=uuid.uuid4(),
        walls_attempt=1,
        cad_job_id=uuid.uuid4(),
        revision_id=uuid.uuid4(),
        page_index=0,
        view=1,
        role="corrector",
        iteration=iteration,
        model="claude-opus-5-5",
        input_sha256="a" * 64,
        walls_sha256="b" * 64,
        dxf_sha256="c" * 64,
        prompt_sha256="d" * 64,
        bundle_sha256="e" * 64,
        sources={"rules": AiSourceCopy(filename="rules.md", sha256="f" * 64)},
        usage=AiUsage(),
        render=AiRender(clip=[0.0, 0.0, 1000.0, 500.0], zoom=2.0),
        remark_keys=["ai-1"],
        report=AiReviewReport(
            verdict="needs_correction",
            findings=[],
            props=[],
            vor_check=[],
            limitations=[],
            slab_findings=[
                AiSlabFinding(
                    kind="slab_missing_area",
                    priority="major",
                    bbox_px=[100.0, 100.0, 300.0, 200.0],
                    observation="Пропущен участок плиты в коридоре",
                    evidence="Видно на плане",
                    suggested_fix="Добавить зону",
                )
            ],
        ),
    )


def test_score_walls_snapshot_with_and_without_zones() -> None:
    walls_with_zones: dict[str, Any] = {
        "slab": {"basis": "zones"},
        "checks": {"warnings": ["w1", "w2"]},
        "constructions": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
        "openings": [{"kind": "door"}, {"kind": "window"}, {"kind": "door"}],
        "hints_applied": [
            {"id": "h1", "status": "applied"},
            {"id": "h2", "status": "applied"},
            {"id": "h3", "status": "no_candidate"},
        ],
    }
    scored = score_walls_snapshot(walls_with_zones)
    assert scored.slab_has_zones is True
    assert scored.warnings_count == 2
    assert scored.constructions_count == 3
    assert scored.openings_count == 3
    assert scored.doors_count == 2
    assert scored.applied_hints == 2
    assert scored.no_candidate_hints == 1
    # 25 (zones) + 5 (doors) + 2*2 (applied) - 2*3 (warnings) - 1*0.5 (no_candidate) = 27.5
    assert scored.score == 27.5

    walls_without_zones: dict[str, Any] = {
        "slab": {"basis": "hull"},
        "warnings": ["w1"],
        "constructions": [],
        "openings": [{"kind": "window"}],
        "hints_applied": [],
    }
    scored_no_zones = score_walls_snapshot(walls_without_zones)
    assert scored_no_zones.slab_has_zones is False
    assert scored_no_zones.warnings_count == 1
    assert scored_no_zones.doors_count == 0
    # 0 + 0 + 0 - 3 - 0 = -3.0
    assert scored_no_zones.score == -3.0


def test_score_walls_snapshot_caps_hints_at_20() -> None:
    walls: dict[str, Any] = {
        "hints_applied": [
            *[{"id": f"a{i}", "status": "applied"} for i in range(25)],
            *[{"id": f"n{i}", "status": "no_candidate"} for i in range(25)],
        ]
    }
    scored = score_walls_snapshot(walls)
    assert scored.applied_hints == 25
    assert scored.no_candidate_hints == 25
    # min(25, 20)*2 - min(25, 20)*0.5 = 40 - 10 = 30.0
    assert scored.score == 30.0


def test_check_round_progress_transitions() -> None:
    curr_initial: dict[str, Any] = {"slab": {"basis": "zones"}, "openings": [{"kind": "door"}]}
    initial = check_round_progress(None, curr_initial)
    assert initial.status == "improved"
    assert initial.prev_score is None
    assert initial.curr_score == 30.0
    assert initial.reasons == ("initial_round",)

    improved = check_round_progress(
        {"slab": {"basis": "hull"}},
        {"slab": {"basis": "zones"}, "hints_applied": [{"status": "applied"}]},
    )
    assert improved.status == "improved"
    assert improved.prev_score == 0.0
    assert improved.curr_score == 27.0
    assert improved.reasons == ("ok",)

    stagnated = check_round_progress(
        {"slab": {"basis": "zones"}, "openings": [{"kind": "door"}]},
        {
            "slab": {"basis": "zones"},
            "openings": [{"kind": "door"}],
            "hints_applied": [{"status": "no_candidate"}, {"status": "no_candidate"}],
        },
    )
    assert stagnated.status == "stagnated"
    assert stagnated.reasons == ("all_hints_no_candidate",)

    lost_zones = check_round_progress(
        {"slab": {"basis": "zones"}},
        {"slab": {"basis": "hull"}, "hints_applied": [{"status": "applied"}] * 15},
    )
    assert lost_zones.status == "regressed"
    assert lost_zones.reasons == ("slab_lost_zones",)

    dropped_score = check_round_progress(
        {"slab": {"basis": "zones"}, "checks": {"warnings": []}},
        {"slab": {"basis": "zones"}, "checks": {"warnings": ["w1", "w2"]}},
    )
    assert dropped_score.status == "regressed"
    assert dropped_score.reasons == ("quality_score_dropped",)


def test_build_prev_round_diff_fields_and_limits() -> None:
    prev_walls: dict[str, Any] = {"slab": {"basis": "zones"}}
    long_reason = "x" * 250
    curr_walls: dict[str, Any] = {
        "slab": {"basis": "zones"},
        "hints_applied": [
            {"id": "ok-1", "type": "missing_wall", "status": "applied", "reason": "ok"},
            *[
                {
                    "id": f"fail-{i}",
                    "type": "false_wall",
                    "status": "no_candidate",
                    "reason": long_reason,
                }
                for i in range(25)
            ],
        ],
    }
    prev_review = _sample_review(iteration=2)
    diff = build_prev_round_diff(curr_walls, prev_walls, prev_review)

    assert diff["schema"] == ROUND_DIFF_SCHEMA
    assert diff["prev_iteration"] == 2
    assert diff["prev_verdict"] == "needs_correction"
    assert diff["prev_summary"] == {"findings": 0, "slab_findings": 1, "props": 0}

    hints_summary = diff["hints_summary"]
    assert hints_summary["total"] == 26
    assert hints_summary["applied"] == 1
    assert hints_summary["no_candidate"] == 25
    assert len(hints_summary["failed"]) == 20
    assert hints_summary["failed"][0]["id"] == "fail-0"
    assert len(hints_summary["failed"][0]["reason"]) == 200

    assert diff["metrics"]["previous"]["score"] == 25.0
    assert diff["metrics"]["current"]["applied_hints"] == 1
    assert diff["progress"]["status"] == "regressed"
    assert diff["progress"]["reasons"] == ["quality_score_dropped"]


def test_slab_findings_to_zone_creates_normalization_filtering_and_limit() -> None:
    revision_id = uuid.uuid4()
    render = AiRender(clip=[100.0, 50.0, 900.0, 450.0], zoom=2.0)

    # Valid finding:
    # x0_pt = 100 + 200/2 = 200 -> 200/1000 = 0.2
    # y0_pt = 50 + 100/2 = 100 -> 100/500 = 0.2
    # x1_pt = 100 + 600/2 = 400 -> 400/1000 = 0.4
    # y1_pt = 50 + 300/2 = 200 -> 200/500 = 0.4
    valid = AiSlabFinding(
        kind="slab_missing_area",
        priority="major",
        bbox_px=[200.0, 100.0, 600.0, 300.0],
        observation="А" * 80,
        evidence="План",
        suggested_fix="Добавить зону",
    )
    # Non-missing_area finding (must be skipped)
    other_kind = AiSlabFinding(
        kind="slab_missing_hole",
        priority="major",
        bbox_px=[200.0, 100.0, 600.0, 300.0],
        observation="Проём шахты",
        evidence="План",
        suggested_fix="Вырезать отверстие",
    )
    # Completely outside page (> page_width_pt) -> clamps to x0=1.0, x1=1.0 -> degenerate (skipped)
    outside = AiSlabFinding(
        kind="slab_missing_area",
        priority="minor",
        bbox_px=[2000.0, 100.0, 2200.0, 200.0],
        observation="Вне листа",
        evidence="План",
        suggested_fix="Игнорировать",
    )

    report = AiReviewReport(
        verdict="needs_correction",
        findings=[],
        props=[],
        vor_check=[],
        limitations=[],
        slab_findings=[valid, other_kind, outside],
    )
    zones = slab_findings_to_zone_creates(
        report,
        render,
        page_width_pt=1000.0,
        page_height_pt=500.0,
        revision_id=revision_id,
        page_index=3,
    )
    assert len(zones) == 1
    zone = zones[0]
    assert zone.revision_id == revision_id
    assert zone.page_index == 3
    assert zone.kind == "room_mop"
    assert zone.room_type == "mop_other"
    assert zone.room_mark == "ИИ-ПЛ"
    assert zone.name == f"ИИ-зона плиты: {'А' * 60}"
    assert zone.points == [(0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)]

    # Limit 10 zones
    many_report = AiReviewReport(
        verdict="needs_correction",
        findings=[],
        props=[],
        vor_check=[],
        limitations=[],
        slab_findings=[valid for _ in range(15)],
    )
    many_zones = slab_findings_to_zone_creates(
        many_report,
        render,
        page_width_pt=1000.0,
        page_height_pt=500.0,
        revision_id=revision_id,
        page_index=0,
    )
    assert len(many_zones) == 10


def test_convert_checks_hints_merged_and_stagnated_when_only_checks_no_candidate() -> None:
    prev_walls: dict[str, Any] = {"slab": {"basis": "zones"}, "openings": [{"kind": "door"}]}
    # walls.json не содержит hints_applied, а checks.json конвертера содержит no_candidate
    curr_walls: dict[str, Any] = {"slab": {"basis": "zones"}, "openings": [{"kind": "door"}]}
    convert_checks: dict[str, Any] = {
        "hints_applied": [
            {
                "id": "h-mw-1",
                "type": "missing_wall",
                "status": "no_candidate",
                "reason": "нет кандидатов в области",
            },
            {
                "id": "h-md-2",
                "type": "missing_door",
                "status": "no_candidate",
                "reason": "дуга не найдена",
            },
        ]
    }
    progress = check_round_progress(prev_walls, curr_walls, convert_checks=convert_checks)
    assert progress.status == "stagnated"
    assert progress.reasons == ("all_hints_no_candidate",)

    diff = build_prev_round_diff(
        curr_walls, prev_walls, _sample_review(1), convert_checks=convert_checks
    )
    assert diff["hints_summary"]["total"] == 2
    assert diff["hints_summary"]["applied"] == 0
    assert diff["hints_summary"]["no_candidate"] == 2
    assert len(diff["hints_summary"]["failed"]) == 2
    assert diff["progress"]["status"] == "stagnated"

    # Проверка приоритета walls.json при совпадении id
    walls_with_override: dict[str, Any] = {
        "hints_applied": [
            {"id": "h-mw-1", "type": "missing_wall", "status": "applied", "reason": "ok"}
        ]
    }
    scored = score_walls_snapshot(walls_with_override, convert_checks=convert_checks)
    assert scored.applied_hints == 1
    assert scored.no_candidate_hints == 1
