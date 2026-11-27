"""Роль «координация»: оси с id, смещение по парам, ответ модели, задание, «Здание»."""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast, get_args
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cad_worker import ai_coordination, ai_coordination_cli
from app.cad_worker.ai_coordination import execute_ai_coordination
from app.contracts.cad_ai_coordination import (
    AiCoordinationReport,
    AiCoordinationResult,
    AiCoordinationSkipped,
    AiCoordinationView,
)
from app.contracts.cad_ai_review import AiLoopPilot, AiPromptRole, AiReviewStart
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.main import create_app
from app.models import AiPromptVersion, Job
from app.services import (
    ai_loop,
    cad_building3d_grid,
    cad_project_levels,
    cad_site_pins,
    jobs,
)
from app.services import cad_axis_coordination as coord
from app.services import cad_axis_coordination_jobs as coord_jobs
from app.services import cad_building3d as b3d
from app.services import cad_building3d_assembly as assembly
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_ai_loop import _context, _walls
from tests.test_cad_building3d import FRAME, axes_block, built, sheet
from tests.test_cad_building3d_assembly import _no_levels, _no_model, _no_pins
from tests.test_cad_floor3d import BASE, heights, raw_document, raw_extras

# Эталон: подписи верны. Целевой лист сдвинут на (-3000, -500) мм, ось «7» прочитана как «11».
REF_V = {"1": 1000.0, "4": 8000.0, "7": 20000.0, "11": 50000.0}
REF_H = {"А": 2000.0, "Б": 4000.0, "В": 9000.0}
SHIFT = (-3000.0, -500.0)
TARGET_V = {"4": 5000.0, "11": 17000.0, "12": 27000.0}
TARGET_H = {"А": 1500.0, "Б": 3500.0}


def _axes(vertical: dict[str, float], horizontal: dict[str, float]) -> list[b3d.CoordAxis]:
    return b3d.coordination_axes({"axes": axes_block(vertical, horizontal)}, FRAME)


def _by_label(axes: list[b3d.CoordAxis], label: str, orient: str) -> b3d.CoordAxis:
    return next(a for a in axes if a.label == label and a.orient == orient)


def _report(*pairs: tuple[str, str], confidence: str = "high") -> AiCoordinationReport:
    return AiCoordinationReport.model_validate(
        {
            "pairs": [
                {
                    "target_axis_id": t,
                    "reference_axis_id": r,
                    "confidence": confidence,
                    "evidence": "рядом шахта лифта",
                }
                for t, r in pairs
            ],
            "notes": "",
        }
    )


def _scenario_341() -> tuple[list[b3d.CoordAxis], list[b3d.CoordAxis], AiCoordinationReport]:
    target = _axes(TARGET_V, TARGET_H)
    reference = _axes(REF_V, REF_H)
    pairs = (
        (_by_label(target, "4", "vertical").id, _by_label(reference, "4", "vertical").id),
        # Подпись цели «11» на деле ось «7» эталона.
        (_by_label(target, "11", "vertical").id, _by_label(reference, "7", "vertical").id),
        (_by_label(target, "А", "horizontal").id, _by_label(reference, "А", "horizontal").id),
        (_by_label(target, "Б", "horizontal").id, _by_label(reference, "Б", "horizontal").id),
    )
    return target, reference, _report(*pairs)


# ------------------------------------------------------------------ оси с идентификаторами


def test_axes_get_stable_ids_left_to_right_and_bottom_up() -> None:
    axes = _axes({"Б": 9000.0, "1": 1000.0, "2": 5000.0}, {"А": 4000.0, "Б": 2000.0})
    assert [(a.id, a.label) for a in axes if a.orient == "vertical"] == [
        ("V1", "1"),
        ("V2", "2"),
        ("V3", "Б"),
    ]
    assert [(a.id, a.label) for a in axes if a.orient == "horizontal"] == [
        ("H1", "Б"),
        ("H2", "А"),
    ]
    assert [round(a.pos_mm) for a in axes if a.orient == "vertical"] == [1000, 5000, 9000]


def test_same_label_on_distant_axes_stays_two_axes_and_close_repeats_merge() -> None:
    block = {"axes": axes_block({"11": 5000.0}, {"А": 2000.0})}
    items = block["axes"]["items"]
    items.append({**items[0], "pos_pt": items[0]["pos_pt"] + 20.0 / 2.0})  # +20 мм: тот же ось
    items.append({**items[0], "pos_pt": items[0]["pos_pt"] + 15000.0 / 2.0})  # +15 м: другая ось
    axes = b3d.coordination_axes(block, FRAME)
    vertical = [a for a in axes if a.orient == "vertical"]
    assert [(a.id, a.label) for a in vertical] == [("V1", "11"), ("V2", "11")]
    assert vertical[0].pos_mm == pytest.approx(5010.0)
    # `axes_in_mm` такую подпись отбросил бы целиком - ровно поэтому координация строит оси сама.
    assert "11" not in b3d.axes_in_mm(block, FRAME).vertical


def test_no_axes_without_confirmed_frame() -> None:
    block = {"axes": axes_block(REF_V, REF_H)}
    unconfirmed = FRAME.model_copy(update={"confirmed": False})
    assert b3d.coordination_axes(block, unconfirmed) == []
    assert b3d.coordination_axes({"axes": None}, FRAME) == []
    assert b3d.coordination_axes(None, FRAME) == []


def test_axes_document_has_no_coordinates() -> None:
    document = coord.axes_document(_axes(REF_V, REF_H))
    assert set(document[0]) == {"id", "label", "orient"}
    assert "mm" not in json.dumps(document)


# ------------------------------------------------------------------ смещение


def test_offset_of_scenario_341_ignores_the_misread_label() -> None:
    target, reference, report = _scenario_341()
    kept, dropped = coord.sanitize_pairs(report, target, reference)
    assert dropped == [] and len(kept) == 4
    offset = coord.compute_offset(kept)
    assert offset.status == "ok" and offset.reason is None
    # p_эталона = p_вида + offset: цель сдвинута на (-3000, -500), вернуть - (+3000, +500).
    assert offset.offset_mm == (3000.0, 500.0)
    assert {p.residual_mm for p in offset.used} == {0.0}
    seven = next(p for p in offset.used if p.reference_label == "7")
    assert (seven.target_label, seven.shift_mm) == ("11", 3000.0)


def test_offset_drops_the_outlier_pair_with_a_reason() -> None:
    target, reference, _ = _scenario_341()
    ids = {
        "t4": _by_label(target, "4", "vertical").id,
        "t11": _by_label(target, "11", "vertical").id,
        "t12": _by_label(target, "12", "vertical").id,
        "r4": _by_label(reference, "4", "vertical").id,
        "r7": _by_label(reference, "7", "vertical").id,
        "r1": _by_label(reference, "1", "vertical").id,
        "tA": _by_label(target, "А", "horizontal").id,
        "tB": _by_label(target, "Б", "horizontal").id,
        "rA": _by_label(reference, "А", "horizontal").id,
        "rB": _by_label(reference, "Б", "horizontal").id,
    }
    report = _report(
        (ids["t4"], ids["r4"]),
        (ids["t11"], ids["r7"]),
        (ids["t12"], ids["r1"]),
        (ids["tA"], ids["rA"]),
        (ids["tB"], ids["rB"]),
    )
    kept, _ = coord.sanitize_pairs(report, target, reference)
    offset = coord.compute_offset(kept)
    assert offset.status == "ok" and offset.offset_mm == (3000.0, 500.0)
    assert [(d.target_axis_id, d.reference_axis_id) for d in offset.dropped] == [
        (ids["t12"], ids["r1"])
    ]
    assert "расходится" in offset.dropped[0].reason
    assert len(offset.used) == 4


def test_offset_is_rejected_without_two_agreed_pairs_per_direction() -> None:
    target, reference, _ = _scenario_341()
    one_vertical = _report(
        (_by_label(target, "4", "vertical").id, _by_label(reference, "4", "vertical").id),
        (_by_label(target, "А", "horizontal").id, _by_label(reference, "А", "horizontal").id),
        (_by_label(target, "Б", "horizontal").id, _by_label(reference, "Б", "horizontal").id),
    )
    kept, _ = coord.sanitize_pairs(one_vertical, target, reference)
    offset = coord.compute_offset(kept)
    assert offset.status == "rejected" and offset.offset_mm is None and offset.used == []
    assert "вертикальным" in (offset.reason or "")
    assert coord.compute_offset([]).status == "rejected"


def test_offset_needs_an_unambiguous_majority_per_direction() -> None:
    target, reference, _ = _scenario_341()
    t4, t11 = (_by_label(target, label, "vertical").id for label in ("4", "11"))
    r4, r7, r11 = (_by_label(reference, label, "vertical").id for label in ("4", "7", "11"))
    tied = _report(
        (t4, r4),
        (t11, r7),
        (_by_label(target, "12", "vertical").id, r11),
        (_by_label(target, "А", "horizontal").id, _by_label(reference, "А", "horizontal").id),
        (_by_label(target, "Б", "horizontal").id, _by_label(reference, "Б", "horizontal").id),
    )
    # Сдвиги по вертикали: 3000, 3000 и 23000: большинство однозначно (две против одной).
    kept, _ = coord.sanitize_pairs(tied, target, reference)
    assert coord.compute_offset(kept).status == "ok"
    split = _report(
        (t4, r4),
        (t11, r11),
        (_by_label(target, "А", "horizontal").id, _by_label(reference, "А", "horizontal").id),
        (_by_label(target, "Б", "horizontal").id, _by_label(reference, "Б", "horizontal").id),
    )
    kept, _ = coord.sanitize_pairs(split, target, reference)
    offset = coord.compute_offset(kept)
    assert offset.status == "rejected" and "вертикальным" in (offset.reason or "")


def test_sanitize_drops_foreign_ids_other_direction_and_repeated_axes() -> None:
    target, reference, _ = _scenario_341()
    t4 = _by_label(target, "4", "vertical").id
    r4 = _by_label(reference, "4", "vertical").id
    t_h = _by_label(target, "А", "horizontal").id
    report = _report(
        (t4, r4),
        ("V99", r4),
        (t4, _by_label(reference, "7", "vertical").id),
        (_by_label(target, "11", "vertical").id, r4),
        (t_h, r4),
    )
    kept, dropped = coord.sanitize_pairs(report, target, reference)
    assert [(a.id, b.id) for _, a, b in kept] == [(t4, r4)]
    assert [d.reason for d in dropped] == [
        "идентификатор оси вне пакета",
        "ось уже входит в другую пару",
        "ось уже входит в другую пару",
        "оси разных направлений",
    ]


def test_report_contract_is_strict_and_roles_include_coordination() -> None:
    schema = AiCoordinationReport.model_json_schema()
    assert set(schema["properties"]) == {"pairs", "notes"}
    assert set(schema["$defs"]["AiCoordinationPair"]["properties"]) == {
        "target_axis_id",
        "reference_axis_id",
        "confidence",
        "evidence",
    }
    with pytest.raises(ValidationError):
        AiCoordinationReport.model_validate(
            {
                "pairs": [
                    {
                        "target_axis_id": "V1",
                        "reference_axis_id": "V2",
                        "confidence": "high",
                        "evidence": "x",
                        "offset_mm": 3000,
                    }
                ],
                "notes": "",
            }
        )
    with pytest.raises(ValidationError):
        _report(("V1", "V2"), confidence="sure")
    assert get_args(AiPromptRole)[-1] == "coordination"
    with pytest.raises(ValidationError):
        AiReviewStart.model_validate({"role": "coordination"})


# ------------------------------------------------------------------ исполнитель


def _view_payload() -> dict[str, str | int]:
    return {
        "revision_id": str(uuid.uuid4()),
        "page_index": 8,
        "view": 1,
        "walls_job_id": str(uuid.uuid4()),
        "cad_job_id": str(uuid.uuid4()),
    }


def _response(*pairs: tuple[str, str]) -> dict[str, Any]:
    return {
        "sources": {"vor": {"filename": "vor.md", "sha256": "a" * 64}},
        "report": json.loads(_report(*pairs).model_dump_json()),
        "usage": {"cost_usd": 0.5, "duration_ms": 1000, "input_tokens": 10, "output_tokens": 5},
        "model": "claude-opus-5-5",
        "prompt_sha256": "b" * 64,
        "bundle_sha256": "c" * 64,
    }


def _views() -> tuple[AiCoordinationView, AiCoordinationView]:
    target, reference = (AiCoordinationView.model_validate(_view_payload()) for _ in range(2))
    return target, reference


async def _run_execute(
    monkeypatch: pytest.MonkeyPatch,
    response: dict[str, Any],
    exit_code: int = 0,
    *,
    pair: Any = None,
    reuse: Any = None,
) -> tuple[AsyncMock, AsyncMock, MagicMock]:
    """Исполнитель с подменёнными границами: промт, эталон «Здания», пакет и запуск CLI.

    Возвращает `succeed`, `fail` и подмену запуска CLI (`call_count` - вызывалась ли модель).
    """
    target, reference, _ = _scenario_341()
    target_view, reference_view = _views()
    job = Job(
        id=uuid.uuid4(),
        status=JobStatus.RUNNING,
        job_type=JobType.CAD_AI_REVIEW,
        worker_id="w",
        attempt=1,
        payload={"role": "coordination", "target": target_view.model_dump(mode="json")},
    )
    side = {"input_sha256": "e" * 64, "walls_sha256": "f" * 64}
    manifest = {
        "model": "claude-opus-5-5",
        "sources": {"vor": "/pilot/vor.md"},
        "prompt_version_id": str(uuid.uuid4()),
        "prompt_version": 1,
        "target": side,
        "reference": side,
    }
    prompt = AiPromptVersion(id=uuid.uuid4(), role="coordination", version=1, text="Промт\n")

    async def prepare(*args: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        return manifest, {"target": target, "reference": reference}

    cli = MagicMock()

    async def run(
        session: Any, job_: Job, owner: Any, attempt: Any, command: list[str], **kw: Any
    ) -> tuple[int, str]:
        cli()
        assert command[3] and command[1] == "-I"
        (Path(command[3]) / "coordination.json").write_text(json.dumps(response), encoding="utf-8")
        return exit_code, ""

    resolved = (
        pair
        if pair is not None
        else (
            target_view.model_copy(update={"axes_sha256": coord.axes_fingerprint(target)}),
            reference_view.model_copy(update={"axes_sha256": coord.axes_fingerprint(reference)}),
        )
    )
    monkeypatch.setattr(ai_coordination, "_prepare", prepare)
    monkeypatch.setattr(ai_coordination, "_run_while_owned", run)
    monkeypatch.setattr(ai_coordination, "_still_owned", AsyncMock(return_value=True))
    monkeypatch.setattr(ai_coordination, "_active_prompt", AsyncMock(return_value=prompt))
    monkeypatch.setattr(ai_coordination, "_resolve_pair", AsyncMock(return_value=resolved))
    monkeypatch.setattr(coord_jobs, "reusable_result", AsyncMock(return_value=reuse))
    monkeypatch.setattr(ai_loop, "pilot_for_project", lambda *_a, **_k: object())
    monkeypatch.setattr(jobs, "start", AsyncMock())
    succeed = AsyncMock(side_effect=lambda session, job, payload: job)
    monkeypatch.setattr(jobs, "succeed", succeed)
    fail = AsyncMock(side_effect=lambda session, job, **kw: job)
    monkeypatch.setattr(jobs, "fail", fail)
    settings = Settings(cad_review_ssh_config="/ssh/config", cad_engine_python="/engine/python")
    await execute_ai_coordination(AsyncMock(), job, AsyncMock(), settings)
    return succeed, fail, cli


def _good_pairs() -> tuple[tuple[str, str], ...]:
    _, _, report = _scenario_341()
    return tuple((p.target_axis_id, p.reference_axis_id) for p in report.pairs)


async def test_execute_computes_the_offset_in_code_and_stores_the_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = _good_pairs()
    succeed, fail, _cli = await _run_execute(monkeypatch, _response(("V99", "V1"), *good))
    fail.assert_not_awaited()
    stored = AiCoordinationResult.model_validate(
        succeed.call_args.kwargs["payload"]["ai_coordination"]
    )
    assert stored.status == "ok" and stored.offset_mm == (3000.0, 500.0)
    assert len(stored.pairs) == 4 and [d.reason for d in stored.dropped] == [
        "идентификатор оси вне пакета"
    ]
    assert stored.usage.cost_usd == 0.5 and stored.prompt_version == 1
    assert stored.prompt_sha256 == "b" * 64 and stored.target_walls_sha256 == "f" * 64
    # Отпечатки осей, которые видела модель: ключ применимости пар к перестроенным конструкциям.
    axes_t, axes_r, _ = _scenario_341()
    assert stored.target.axes_sha256 == coord.axes_fingerprint(axes_t)
    assert stored.reference.axes_sha256 == coord.axes_fingerprint(axes_r)


async def test_execute_keeps_a_rejected_candidate_as_a_succeeded_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    succeed, fail, _cli = await _run_execute(monkeypatch, _response(_good_pairs()[0]))
    fail.assert_not_awaited()
    stored = succeed.call_args.kwargs["payload"]["ai_coordination"]
    assert stored["status"] == "rejected" and stored["offset_mm"] is None and stored["reason"]
    assert stored["pairs"] == []


@pytest.mark.parametrize(
    "response",
    [
        {**_response(), "report": {"pairs": "x", "notes": ""}},
        # Числа от модели не принимаются: лишние поля отклоняют весь отчёт.
        {
            **_response(),
            "report": {
                "pairs": [
                    {
                        "target_axis_id": "V1",
                        "reference_axis_id": "V1",
                        "confidence": "high",
                        "evidence": "x",
                        "offset_mm": 1,
                    }
                ],
                "notes": "",
            },
        },
        {k: v for k, v in _response().items() if k != "report"},
    ],
)
async def test_execute_rejects_a_bad_response(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]
) -> None:
    succeed, fail, _cli = await _run_execute(monkeypatch, response)
    succeed.assert_not_awaited()
    assert fail.call_args.kwargs["error_code"] == "CAD_ENGINE_FAILED"


@pytest.mark.parametrize(
    ("code", "error"),
    [(124, "JOB_TIMEOUT"), (255, "CAD_ENGINE_UNAVAILABLE"), (3, "CAD_ENGINE_FAILED")],
)
async def test_execute_maps_exit_codes(
    monkeypatch: pytest.MonkeyPatch, code: int, error: str
) -> None:
    succeed, fail, _cli = await _run_execute(monkeypatch, _response(), exit_code=code)
    succeed.assert_not_awaited()
    assert fail.call_args.kwargs["error_code"] == error


async def test_execute_skips_without_calling_the_model_when_there_is_no_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_view, _ = _views()
    skipped = AiCoordinationSkipped(reason="вид - эталон группы", target=target_view)
    succeed, fail, cli = await _run_execute(monkeypatch, _response(), pair=skipped)
    fail.assert_not_awaited()
    cli.assert_not_called()
    stored = succeed.call_args.kwargs["payload"]["ai_coordination"]
    assert stored["status"] == "skipped" and stored["reason"] == "вид - эталон группы"


async def test_execute_copies_a_reusable_result_without_calling_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_view, reference_view = _views()
    previous_job = Job(id=uuid.uuid4(), job_type=JobType.CAD_AI_REVIEW)
    succeed, _, cli = await _run_execute(monkeypatch, _response(), reuse=None)
    assert cli.call_count == 1 and succeed.await_count == 1
    stored = AiCoordinationResult.model_validate(
        succeed.call_args.kwargs["payload"]["ai_coordination"]
    )
    previous = stored.model_copy(update={"reused_from": None})
    succeed, fail, cli = await _run_execute(
        monkeypatch,
        _response(),
        pair=(target_view, reference_view),
        reuse=(previous_job, previous),
    )
    fail.assert_not_awaited()
    cli.assert_not_called()
    copied = AiCoordinationResult.model_validate(
        succeed.call_args.kwargs["payload"]["ai_coordination"]
    )
    # Пары и смещение скопированы, вызова модели нет: затрат нет, источник - прежнее задание.
    assert copied.reused_from == previous_job.id
    assert copied.usage.cost_usd is None and copied.usage.duration_ms is None
    assert copied.offset_mm == previous.offset_mm and copied.pairs == previous.pairs
    assert copied.target == target_view and copied.reference == reference_view


def test_cli_package_and_remote_command() -> None:
    assert "draw_target.json" not in ai_coordination_cli.PACKAGE_FILES
    assert set(ai_coordination_cli.PACKAGE_FILES) == {
        "manifest.json",
        "axes_target.json",
        "axes_reference.json",
        "plan_target.png",
        "plan_reference.png",
        "prompt.txt",
        "schema.json",
    }
    assert ai_coordination_cli.remote_command(300) == ai_coordination_cli.remote_command(300)
    assert ai_coordination_cli.remote_command(300) != ai_coordination_cli.remote_command(301)


def test_cli_renders_both_plans_with_axis_tags(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    with pymupdf.open() as document:
        page = document.new_page(width=600, height=400)
        page.draw_rect(pymupdf.Rect(50, 50, 550, 350))
        document.save(tmp_path / "target.pdf")
    side = {"pdf_file": "target.pdf", "pdf_page": 1, "view_zone": None}
    (tmp_path / "manifest.json").write_text(
        json.dumps({"target": side, "reference": side}), encoding="utf-8"
    )
    draw = {
        "axes": [
            {"id": "V1", "orient": "vertical", "pos_pt": 100.0},
            {"id": "V2", "orient": "vertical", "pos_pt": 140.0},
            {"id": "H1", "orient": "horizontal", "pos_pt": 300.0},
        ]
    }
    for name in ("target", "reference"):
        (tmp_path / f"draw_{name}.json").write_text(json.dumps(draw), encoding="utf-8")
    ai_coordination_cli.render(tmp_path)
    for name in ("plan_target.png", "plan_reference.png"):
        assert (tmp_path / name).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------ совмещение «Здания»


def _hint(reference: b3d.BuiltFloor, result: coord.Offset) -> b3d.CoordinationHint:
    assert result.offset_mm is not None
    return b3d.CoordinationHint(
        reference_view=b3d.view_key_of(reference.floor),
        offset_mm=result.offset_mm,
        pairs=tuple(
            b3d.CoordinationPair(
                orient=p.orient,
                target_label=p.target_label,
                reference_label=p.reference_label,
                target_mm=p.target_mm,
                reference_mm=p.reference_mm,
                residual_mm=p.residual_mm,
            )
            for p in result.used
        ),
    )


def _with_axes(
    item: b3d.BuiltFloor, vertical: dict[str, float], horizontal: dict[str, float]
) -> b3d.BuiltFloor:
    """Этаж с осями: `axes` для совмещения по подписям и `coord_axes` для координации."""
    block = axes_block(vertical, horizontal)
    return dataclasses.replace(
        item,
        axes=b3d.axes_in_mm({"axes": block}, FRAME),
        coord_axes=tuple(b3d.coordination_axes({"axes": block}, FRAME)),
    )


def _floors(
    target_v: dict[str, float] = TARGET_V,
) -> tuple[b3d.BuiltFloor, b3d.BuiltFloor]:
    reference = _with_axes(built(axes=axes_block(REF_V, REF_H), order=0), REF_V, REF_H)
    target = _with_axes(
        built(axes=axes_block(target_v, TARGET_H), order=1, shift=SHIFT), target_v, TARGET_H
    )
    return target, reference


def _stored(
    target: b3d.BuiltFloor, reference: b3d.BuiltFloor, report: AiCoordinationReport
) -> coord_jobs.StoredCoordination:
    return coord_jobs.StoredCoordination(
        reference_view=b3d.view_key_of(reference.floor),
        target_axes_sha256=coord.axes_fingerprint(target.coord_axes),
        reference_axes_sha256=coord.axes_fingerprint(reference.coord_axes),
        pairs=tuple(report.pairs),
    )


def test_labels_alone_fail_but_coordination_aligns_the_floor() -> None:
    target, reference = _floors()
    by_labels = b3d._align_to(target, reference)
    assert by_labels.alignment == "none" and by_labels.alignment_source == "labels"

    axes_t, axes_r, report = _scenario_341()
    kept, _ = coord.sanitize_pairs(report, axes_t, axes_r)
    offset = coord.compute_offset(kept)
    coordinated = dataclasses.replace(target, coordination=(_hint(reference, offset),))
    aligned = b3d._align_to(coordinated, reference)
    assert aligned.alignment == "axes" and aligned.alignment_source == "ai_coordination"
    assert aligned.offset_mm == (3000.0, 500.0) and aligned.rotation_deg == 0.0
    assert aligned.alignment_note == (
        "оси сопоставлены ИИ (координация): 4 пар, смещение посчитано движком"
    )
    assert "11→7 (верт.)" in aligned.alignment_axes
    assert aligned.alignment_max_mm == 0.0 and aligned.alignment_axes_common == 4
    # Этаж встал на эталон: габариты совпали.
    assert aligned.bbox == reference.floor.bbox


CONFIDENT_V = {"4": 5000.0, "7": 17000.0}


def test_confident_label_alignment_is_not_overridden_by_coordination() -> None:
    """Две согласные подписи в каждом направлении: ИИ совмещение не перебивает."""
    target, reference = _floors(CONFIDENT_V)
    by_labels = b3d._align_to(target, reference)
    assert by_labels.alignment == "axes" and by_labels.alignment_source == "labels"
    axes_t, axes_r, report = _scenario_341()
    kept, _ = coord.sanitize_pairs(report, axes_t, axes_r)
    agree = _hint(reference, coord.compute_offset(kept))
    confirmed = b3d._align_to(dataclasses.replace(target, coordination=(agree,)), reference)
    assert confirmed.alignment_source == "labels"
    assert confirmed.offset_mm == by_labels.offset_mm
    assert confirmed.alignment_note == "подтверждено ИИ (координация)"
    # ИИ называет иное смещение: остаётся совмещение по подписям, расхождение - в примечании.
    other = dataclasses.replace(agree, offset_mm=(agree.offset_mm[0] + 5000.0, agree.offset_mm[1]))
    kept_by_labels = b3d._align_to(dataclasses.replace(target, coordination=(other,)), reference)
    assert kept_by_labels.alignment_source == "labels"
    assert kept_by_labels.offset_mm == by_labels.offset_mm
    assert "оставлено совмещение по подписям" in (kept_by_labels.alignment_note or "")


def test_label_alignment_confidence_rules() -> None:
    target, reference = _floors(CONFIDENT_V)
    aligned = b3d._align_to(target, reference)
    assert b3d._confident_by_labels(aligned, reference)
    # Одна подпись в направлении: уверенно только при перекрытии не меньше 0,85.
    single = aligned.model_copy(update={"alignment_axes": ["4 (верт.)", "А (гор.)"]})
    assert b3d._confident_by_labels(single, reference)
    away_box = [c + 100000.0 for c in (single.bbox or [0.0, 0.0, 1.0, 1.0])]
    assert not b3d._confident_by_labels(single.model_copy(update={"bbox": away_box}), reference)
    # Нет подписей в одном направлении и откат на центр - неуверенно.
    assert not b3d._confident_by_labels(
        aligned.model_copy(update={"alignment_axes": ["4 (верт.)"]}), reference
    )
    assert not b3d._confident_by_labels(aligned.model_copy(update={"alignment": "none"}), reference)


def test_coordination_of_another_reference_view_is_ignored() -> None:
    target, reference = _floors()
    axes_t, axes_r, report = _scenario_341()
    kept, _ = coord.sanitize_pairs(report, axes_t, axes_r)
    hint = _hint(reference, coord.compute_offset(kept))
    other = _with_axes(built(axes=axes_block(REF_V, REF_H), order=2), REF_V, REF_H)
    assert b3d._align_to(dataclasses.replace(target, coordination=(hint,)), other).alignment == (
        "none"
    )


def test_coordination_keeps_the_scale_and_overlap_checks() -> None:
    target, reference = _floors()
    axes_t, axes_r, report = _scenario_341()
    kept, _ = coord.sanitize_pairs(report, axes_t, axes_r)
    hint = _hint(reference, coord.compute_offset(kept))
    # Три вертикальные пары: расстояния между осями эталона на 1 % больше, чем у цели.
    stretched = dataclasses.replace(
        hint,
        pairs=tuple(
            b3d.CoordinationPair("vertical", f"t{i}", f"r{i}", i * 10000.0, i * 10100.0 + 3000.0, 0)
            for i in range(3)
        ),
    )
    scale = b3d._align_to(dataclasses.replace(target, coordination=(stretched,)), reference)
    assert scale.alignment == "none" and "масштаб листа" in (scale.alignment_message or "")
    # Смещение, уводящее этаж с эталона: не перекрывается.
    far = dataclasses.replace(hint, offset_mm=(900000.0, 0.0))
    away = b3d._align_to(dataclasses.replace(target, coordination=(far,)), reference)
    assert away.alignment == "none" and "не перекрывает эталон" in (away.alignment_message or "")


def test_walls_job_id_is_read_from_the_walls_key() -> None:
    walls_id = uuid.uuid4()
    key = f"revisions/{uuid.uuid4()}/cad/{walls_id}/attempt-2/views/p001_v01/walls.json"
    assert b3d.walls_job_id_of_key(key) == walls_id
    assert b3d.walls_job_id_of_key(None) is None and b3d.walls_job_id_of_key("k") is None


# ------------------------------------------------------------------ задание, автоход, эндпоинт


def _pilot_settings(project_id: uuid.UUID | None, *, flag: bool = False) -> Settings:
    assert project_id is not None
    pilot = AiLoopPilot(project_id=project_id, sources={"vor": "/pilot/vor.md"})
    return clean_settings(
        environment="test",
        cad_ai_loop=pilot.model_dump_json(),
        feature_flags="cad.export=true" if flag else "",
    )


async def _pair(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    *,
    prompt: bool = True,
) -> tuple[Job, Job, Job, Settings]:
    ctx = await _context(db_session, fake_storage, build_api, workspace_id)
    target = await _walls(db_session, ctx.convert)
    reference = await _walls(db_session, ctx.convert)
    if prompt:
        db_session.add(
            AiPromptVersion(role="coordination", version=1, text="Промт\n", status="active")
        )
    await db_session.commit()
    return ctx.convert, target, reference, _pilot_settings(ctx.project_id)


FPS = "a" * 64


async def test_enqueue_is_idempotent_by_target_and_prompt_and_keeps_payload_nested(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    _, target, reference, settings = await _pair(db_session, build_api, fake_storage, workspace_id)
    first = await coord_jobs.enqueue_coordination(db_session, target, settings)
    again = await coord_jobs.enqueue_coordination(db_session, target, settings)
    assert first.id == again.id and first.status is JobStatus.QUEUED
    payload = first.payload
    assert payload["role"] == "coordination" and payload["model"] == "claude-opus-5-5"
    assert payload["target"]["walls_job_id"] == str(target.id)
    # Эталон «Здания» ищет исполнитель: в задании его нет.
    assert "reference" not in payload
    # Ключи проверки вида на верхнем уровне не лежат: `reviews_of` и конвейер листа их ищут.
    assert not {"walls_job_id", "revision_id", "page_index", "view"} & set(payload)
    other = await coord_jobs.enqueue_coordination(db_session, reference, settings)
    assert other.id != first.id


async def test_failed_job_is_repeated_by_the_loop_up_to_the_limit_and_by_a_manual_start(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    """Упавшее задание не блокирует вид: автоход ставит новое, пока попыток не больше лимита."""
    _, target, _, settings = await _pair(db_session, build_api, fake_storage, workspace_id)
    failed: list[Job] = []
    for _ in range(coord_jobs.MAX_AUTO_RETRIES + 1):
        job = await coord_jobs.enqueue_coordination(
            db_session, target, settings, target_axes_sha256=FPS
        )
        assert job.status is JobStatus.QUEUED and job.id not in {j.id for j in failed}
        job.status = JobStatus.FAILED
        await db_session.commit()
        failed.append(job)
    # Лимит исчерпан: автоход возвращает упавшее задание и нового не ставит.
    blocked = await coord_jobs.enqueue_coordination(
        db_session, target, settings, target_axes_sha256=FPS
    )
    assert blocked.status is JobStatus.FAILED and blocked.id in {j.id for j in failed}
    # Ручной запуск ставит всегда.
    retry = await coord_jobs.enqueue_coordination(
        db_session, target, settings, retry_failed=True, target_axes_sha256=FPS
    )
    assert retry.status is JobStatus.QUEUED and retry.id not in {j.id for j in failed}
    # Упавшее задание не мешает и вызову без отпечатка осей.
    retry.status = JobStatus.FAILED
    await db_session.commit()
    plain = await coord_jobs.enqueue_coordination(db_session, target, settings)
    assert plain.status is JobStatus.QUEUED


async def test_two_simultaneous_enqueues_of_one_key_make_one_job(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Проигравшая гонку постановка получает задание победившей: дубля нет, сессия живая."""
    _, target, _, settings = await _pair(db_session, build_api, fake_storage, workspace_id)
    assert db_session.bind is not None
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    original = jobs.enqueue
    raced: list[uuid.UUID] = []

    async def racing(session: AsyncSession, **kwargs: Any) -> Job:
        # Другая транзакция успела поставить такое же задание между проверкой и вставкой.
        async with factory() as other:
            winner = await original(other, **kwargs)
            await other.commit()
        raced.append(winner.id)
        session.add(
            Job(
                project_id=kwargs["project_id"],
                workspace_id=kwargs["workspace_id"],
                job_type=kwargs["job_type"],
                status=JobStatus.QUEUED,
                idempotency_key=kwargs["idempotency_key"],
                payload=kwargs["payload"],
            )
        )
        await session.flush()  # уникальный ключ: IntegrityError
        raise AssertionError("вставка должна была упасть")

    monkeypatch.setattr(jobs, "enqueue", racing)
    job = await coord_jobs.enqueue_coordination(db_session, target, settings)
    monkeypatch.setattr(jobs, "enqueue", original)
    assert raced == [job.id]
    rows = await db_session.scalars(
        select(Job).where(Job.idempotency_key.startswith("cad-ai-coordination:"))
    )
    assert [row.id for row in rows] == [job.id]
    # Сессия после отката точки сохранения работает: повтор возвращает то же задание.
    assert (await coord_jobs.enqueue_coordination(db_session, target, settings)).id == job.id


async def test_enqueue_refuses_without_pilot_prompt_or_ready_walls(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    _, target, _, settings = await _pair(
        db_session, build_api, fake_storage, workspace_id, prompt=False
    )
    with pytest.raises(DomainError, match="промта"):
        await coord_jobs.enqueue_coordination(db_session, target, settings)
    with pytest.raises(DomainError, match="недоступна"):
        await coord_jobs.enqueue_coordination(db_session, target, clean_settings())
    target.status = JobStatus.FAILED
    with pytest.raises(DomainError, match="не готовы"):
        await coord_jobs.enqueue_coordination(db_session, target, settings)


async def _queued(db_session: AsyncSession) -> list[Job]:
    rows = await db_session.scalars(
        select(Job)
        .where(Job.job_type == JobType.CAD_AI_REVIEW)
        .execution_options(populate_existing=True)
    )
    return [job for job in rows if job.payload.get("role") == "coordination"]


async def test_hook_queues_a_light_job_without_collecting_the_whole_project(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    convert, target, _, settings = await _pair(db_session, build_api, fake_storage, workspace_id)
    axes = _axes(TARGET_V, TARGET_H)
    read_axes = AsyncMock(return_value=axes)
    monkeypatch.setattr(coord_jobs, "target_view_axes", read_axes)
    collect = AsyncMock(side_effect=AssertionError("хук не собирает листы проекта"))
    monkeypatch.setattr(b3d, "collect_sheets", collect)

    await ai_loop.after_walls(db_session, target, settings)  # без хранилища хода нет
    assert await _queued(db_session) == []
    await ai_loop.after_walls(db_session, target, clean_settings(), fake_storage)  # без пилота
    assert await _queued(db_session) == []
    await ai_loop.after_walls(db_session, target, settings, fake_storage)
    [row] = await _queued(db_session)
    assert row.payload["target"]["walls_job_id"] == str(target.id)
    assert row.payload["target"]["axes_sha256"] == coord.axes_fingerprint(axes)
    assert "reference" not in row.payload
    collect.assert_not_awaited()
    # Нет осей для координации (причина вместо списка): задания нет.
    read_axes.return_value = "на виде меньше двух осей в одном из направлений"
    other = await _walls(db_session, convert)
    await ai_loop.after_walls(db_session, other, settings, fake_storage)
    assert len(await _queued(db_session)) == 1
    collect.assert_not_awaited()


async def test_hook_error_does_not_fail_the_parent(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, target, _, settings = await _pair(db_session, build_api, fake_storage, workspace_id)
    monkeypatch.setattr(
        coord_jobs,
        "coordinate_for_walls",
        AsyncMock(side_effect=DomainError(ErrorCode.CAD_RESULT_NOT_READY, "сбой")),
    )
    await ai_loop.after_walls(db_session, target, settings, fake_storage)


def _ok_result(
    target: Job,
    reference: Job,
    *,
    status: str = "ok",
    fingerprints: bool = True,
    target_page: int = 2,
    reference_page: int = 1,
) -> dict[str, Any]:
    axes_t, axes_r, report = _scenario_341()

    def view(walls: Job, page: int, axes: list[b3d.CoordAxis]) -> dict[str, Any]:
        return {
            "revision_id": walls.payload["revision_id"],
            "page_index": page,
            "view": 1,
            "walls_job_id": str(walls.id),
            "cad_job_id": walls.payload["parent_job_id"],
            "axes_sha256": coord.axes_fingerprint(axes) if fingerprints else None,
        }

    kept, _ = coord.sanitize_pairs(report, axes_t, axes_r)
    offset = coord.compute_offset(kept)
    return {
        "target": view(target, target_page, axes_t),
        "reference": view(reference, reference_page, axes_r),
        "model": "claude-opus-5-5",
        "target_input_sha256": "1" * 64,
        "reference_input_sha256": "2" * 64,
        "target_walls_sha256": "3" * 64,
        "reference_walls_sha256": "4" * 64,
        "prompt_sha256": "b" * 64,
        "bundle_sha256": "c" * 64,
        "usage": {},
        "sources": {},
        "pairs": [p.model_dump(mode="json") for p in offset.used],
        "dropped": [],
        "offset_mm": list(offset.offset_mm or ()) or None,
        "status": status,
        "reason": None,
    }


async def test_load_hints_returns_only_ok_results_with_axes_fingerprints_by_target_view(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    convert, target, reference, _ = await _pair(db_session, build_api, fake_storage, workspace_id)
    assert convert.workspace_id is not None and convert.project_id is not None

    async def succeeded(key: str, result: dict[str, Any]) -> Job:
        job = await jobs.enqueue(
            db_session,
            job_type=JobType.CAD_AI_REVIEW,
            workspace_id=convert.workspace_id,
            project_id=convert.project_id,
            idempotency_key=key,
            payload={"role": "coordination", "ai_coordination": result},
        )
        job.status = JobStatus.SUCCEEDED
        return job

    await succeeded("c-ok", _ok_result(target, reference))
    await succeeded("c-rejected", _ok_result(target, reference, status="rejected"))
    await succeeded("c-old", _ok_result(target, reference, fingerprints=False, target_page=5))
    # Упавшее задание (в том числе с остатком итога) и идущее подсказкой не становятся и сборку
    # «Здания» не блокируют: берутся только успешные задания.
    broken = await succeeded("c-failed", _ok_result(target, reference, target_page=6))
    broken.status = JobStatus.FAILED
    running = await succeeded("c-running", _ok_result(target, reference, target_page=7))
    running.status = JobStatus.RUNNING
    await db_session.commit()
    hints = await coord_jobs.load_hints(
        db_session, workspace_id=convert.workspace_id, project_id=convert.project_id
    )
    revision_id = uuid.UUID(target.payload["revision_id"])
    # Отказ и результат без отпечатков осей (старый) подсказкой не становятся.
    assert set(hints) == {(revision_id, 2, 1)}
    [stored] = hints[(revision_id, 2, 1)]
    axes_t, axes_r, _ = _scenario_341()
    assert stored.reference_view == (revision_id, 1, 1)
    assert stored.target_axes_sha256 == coord.axes_fingerprint(axes_t)
    assert stored.reference_axes_sha256 == coord.axes_fingerprint(axes_r)
    assert len(stored.pairs) == 4


def test_fingerprint_follows_ids_labels_directions_and_millimetres() -> None:
    axes = _axes(REF_V, REF_H)
    assert coord.axes_fingerprint(axes) == coord.axes_fingerprint(_axes(REF_V, REF_H))
    # Доли миллиметра (повторный разбор тех же осей) отпечаток не меняют, миллиметры - меняют.
    nudged = {**REF_V, "4": REF_V["4"] + 0.3}
    assert coord.axes_fingerprint(_axes(nudged, REF_H)) == coord.axes_fingerprint(axes)
    moved = {**REF_V, "4": REF_V["4"] + 5.0}
    assert coord.axes_fingerprint(_axes(moved, REF_H)) != coord.axes_fingerprint(axes)
    renamed = {("Z" if label == "4" else label): value for label, value in REF_V.items()}
    assert coord.axes_fingerprint(_axes(renamed, REF_H)) != coord.axes_fingerprint(axes)


def test_rebuilt_target_with_the_same_axes_keeps_the_hint_and_recomputes_the_offset() -> None:
    target, reference = _floors()
    _, _, report = _scenario_341()
    stored = _stored(target, reference, report)
    key = b3d.view_key_of(target.floor)
    # Перестроенные конструкции: оси те же (до долей миллиметра), положение этажа пересчитано.
    rebuilt_v = {**TARGET_V, "4": TARGET_V["4"] + 0.3}
    rebuilt, _ = _floors(rebuilt_v)
    rebuilt = dataclasses.replace(rebuilt, floor=target.floor)
    applied = coord_jobs.apply_hints([rebuilt, reference], {key: (stored,)})
    [hint] = applied[0].coordination
    assert hint.reference_view == b3d.view_key_of(reference.floor)
    # Смещение пересчитано по ТЕКУЩИМ осям: медиана согласных сдвигов съехала на доли мм.
    assert hint.offset_mm != (3000.0, 500.0) and hint.offset_mm[0] == pytest.approx(3000.0, abs=0.5)
    aligned = b3d._align_to(applied[0], applied[1])
    assert aligned.alignment == "axes" and aligned.alignment_source == "ai_coordination"
    assert applied[1].coordination == ()


@pytest.mark.parametrize("changed", ["target", "reference"])
def test_changed_axes_do_not_apply_the_pairs_and_the_note_says_why(changed: str) -> None:
    target, reference = _floors()
    _, _, report = _scenario_341()
    stored = _stored(target, reference, report)
    key = b3d.view_key_of(target.floor)
    if changed == "target":
        moved, _ = _floors({**TARGET_V, "4": 5100.0})
        target = dataclasses.replace(moved, floor=target.floor)
    else:
        reference = _with_axes(reference, {**REF_V, "4": 8100.0}, REF_H)
    applied = coord_jobs.apply_hints([target, reference], {key: (stored,)})
    assert applied[0].coordination == ()
    aligned = b3d._align_to(applied[0], applied[1])
    assert aligned.alignment == "none" and aligned.alignment_source == "labels"
    assert aligned.alignment_note == coord_jobs.STALE_NOTE


def test_stored_pairs_that_no_longer_give_an_offset_fall_back_with_a_reason() -> None:
    target, reference = _floors()
    _, _, report = _scenario_341()
    # В сохранённых парах лишь одна вертикальная: на текущих осях смещения нет.
    thin = AiCoordinationReport(
        pairs=[p for p in report.pairs if p.target_axis_id != "V3"][:3], notes=""
    )
    stored = _stored(target, reference, thin)
    applied = coord_jobs.apply_hints(
        [target, reference], {b3d.view_key_of(target.floor): (stored,)}
    )
    assert applied[0].coordination == ()
    note = b3d._align_to(applied[0], applied[1]).alignment_note
    assert note is not None and "не дали смещения" in note


def test_manual_route_is_in_openapi() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    route = paths["/api/v1/projects/{project_id}/cad/building3d/axis-coordination"]
    assert set(route) == {"post"}


async def test_manual_start_queues_the_view_and_reports_a_reason_otherwise(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    convert, target, reference, _ = await _pair(db_session, build_api, fake_storage, workspace_id)
    assert convert.project_id is not None
    settings = _pilot_settings(convert.project_id, flag=True)
    body = {"revision_id": convert.payload["revision_id"], "page_index": 0, "view": 1}
    url = f"/api/v1/projects/{convert.project_id}/cad/building3d/axis-coordination"
    async with build_api(make_context(), settings=settings) as api:
        response = await api.post(url, json=body)
        assert response.status_code == 202, response.text
        data = response.json()
        assert data["status"] == "queued"
        # Эталон в ответе не называется: его ищет исполнитель задания.
        assert data["target_walls_job_id"] in {str(target.id), str(reference.id)}
        assert "reference_walls_job_id" not in data
        assert (await api.post(url, json={**body, "mode": "x"})).status_code == 422
        # Вид без готовых конструкций: причина вместо задания.
        refused = await api.post(url, json={**body, "page_index": 7})
        assert refused.status_code >= 400 and "Конструкции вида" in refused.text
    async with build_api(make_context(), settings=_pilot_settings(uuid.uuid4(), flag=True)) as api:
        assert (await api.post(url, json=body)).status_code >= 400


# ------------------------------------------------------------------ сборка «Здания»


def _walls_file(
    elevation: int, floor: int, *, shift: tuple[float, float], axes: dict[str, Any]
) -> bytes:
    title = {"corps": "9", "section": "3", "floors": [floor], "text": None, "kind": "floor"}
    raw = raw_document()
    raw["generator"] = "cad_walls.v1.15"
    raw["heights"] = heights(title=title, floor_elevation_mm=elevation, floor_height_mm=3000)
    extras = raw_extras()
    dx, dy = shift
    extras["slab"]["shell"] = [[x + dx, y + dy] for x, y in extras["slab"]["shell"]]
    for construction in raw["constructions"]:
        shell = construction["polygon"]["shell"]
        construction["polygon"] = {"shell": [[x + dx, y + dy] for x, y in shell], "holes": []}
    return json.dumps({**extras, **raw, "axes": axes}).encode()


async def test_building_uses_the_stored_coordination_for_the_target_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b3d.floor_cache.clear()
    storage = FakeObjectStorage()
    walls_ids = (uuid.uuid4(), uuid.uuid4())
    revision_id = uuid.uuid4()
    files = (
        (BASE, 1, (0.0, 0.0), axes_block(REF_V, REF_H)),
        (BASE + 3300, 2, SHIFT, axes_block(TARGET_V, TARGET_H)),
    )
    refs: list[b3d.SheetRef] = []
    for index, (walls_id, (elevation, floor, shift, axes)) in enumerate(
        zip(walls_ids, files, strict=True)
    ):
        key = f"revisions/{revision_id}/cad/{walls_id}/attempt-1/views/p001_v01/walls.json"
        await storage.put_bytes(
            key,
            _walls_file(elevation, floor, shift=shift, axes=axes),
            content_type="application/json",
        )
        refs.append(
            dataclasses.replace(
                sheet(order=(0.0, 0.0, index, 1)), walls_key=key, label=f"АР · лист {index + 1}"
            )
        )

    async def collect(
        *_args: object, **_kwargs: object
    ) -> tuple[list[b3d.SheetRef], list[Any], None]:
        return list(refs), [], None

    axes_t, axes_r, report = _scenario_341()
    # Результат хранится по ВИДАМ (ревизия, страница, вид) и отпечаткам осей, не по заданиям
    # конструкций: перестроенные конструкции (иной walls-job) подсказку не теряют.
    stored = coord_jobs.StoredCoordination(
        reference_view=(refs[0].revision_id, 0, 1),
        target_axes_sha256=coord.axes_fingerprint(axes_t),
        reference_axes_sha256=coord.axes_fingerprint(axes_r),
        pairs=tuple(report.pairs),
    )
    hints = {(refs[1].revision_id, 1, 1): (stored,)}
    monkeypatch.setattr(b3d, "collect_sheets", collect)
    monkeypatch.setattr(b3d, "_read_frame", AsyncMock(return_value=(FRAME, True)))
    monkeypatch.setattr(assembly, "collect_missing_plans", AsyncMock(return_value=[]))
    monkeypatch.setattr(cad_site_pins, "active_site_pins", _no_pins)
    monkeypatch.setattr(cad_project_levels, "load_project_levels", _no_levels)
    monkeypatch.setattr(cad_building3d_grid, "load_model_reference", _no_model)
    loader = AsyncMock(return_value=hints)
    monkeypatch.setattr(coord_jobs, "load_hints", loader)

    async def build() -> list[Any]:
        body = await assembly.build_building3d(
            cast(AsyncSession, object()),
            storage,
            workspace_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )
        return list(body.floors)

    reference, target = await build()
    # Один запрос заданий на всю сборку, а не на этаж.
    assert loader.await_count == 1
    assert reference.alignment == "reference" and reference.alignment_source == "labels"
    assert target.alignment == "axes" and target.alignment_source == "ai_coordination"
    assert target.offset_mm == (3000.0, 500.0)
    assert target.alignment_note and "4 пар" in target.alignment_note
    # Без заданий - прежний путь по подписям: «4» и «11» расходятся с эталоном.
    loader.return_value = {}
    _, plain = await build()
    assert plain.alignment == "none" and plain.alignment_source == "labels"
    assert plain.alignment_note is None
    # Оси вида изменились после координации: пары не применяются, причина - в примечании.
    loader.return_value = {
        (refs[1].revision_id, 1, 1): (dataclasses.replace(stored, target_axes_sha256="0" * 64),)
    }
    _, stale = await build()
    assert stale.alignment == "none" and stale.alignment_note == coord_jobs.STALE_NOTE
    b3d.floor_cache.clear()


async def test_manual_start_repeats_a_rejected_result_but_the_loop_does_not(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    _, target, _, settings = await _pair(db_session, build_api, fake_storage, workspace_id)
    first = await coord_jobs.enqueue_coordination(
        db_session, target, settings, target_axes_sha256=FPS
    )
    first.status = JobStatus.SUCCEEDED
    first.payload = {**first.payload, "ai_coordination": {"status": "rejected"}}
    await db_session.commit()
    again = await coord_jobs.enqueue_coordination(
        db_session, target, settings, target_axes_sha256=FPS
    )
    assert again.id == first.id
    repeat = await coord_jobs.enqueue_coordination(
        db_session, target, settings, retry_failed=True, target_axes_sha256=FPS
    )
    assert repeat.id != first.id and repeat.status is JobStatus.QUEUED


async def test_loop_does_not_repeat_a_view_whose_axes_did_not_change(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
) -> None:
    convert, target, _, settings = await _pair(db_session, build_api, fake_storage, workspace_id)
    first = await coord_jobs.enqueue_coordination(
        db_session, target, settings, target_axes_sha256=FPS
    )
    # Перестроенные конструкции цели (новый walls-job), оси те же: идущее задание остаётся одним.
    rebuilt = await _walls(db_session, convert)
    await db_session.commit()
    running = await coord_jobs.enqueue_coordination(
        db_session, rebuilt, settings, target_axes_sha256=FPS
    )
    assert running.id == first.id
    # То же после завершения: итог ok и итог rejected новой координации не порождают.
    first.status = JobStatus.SUCCEEDED
    first.payload = {**first.payload, "ai_coordination": {"status": "rejected"}}
    await db_session.commit()
    done = await coord_jobs.enqueue_coordination(
        db_session, rebuilt, settings, target_axes_sha256=FPS
    )
    assert done.id == first.id
    # Завершённое без вызова модели (эталона не было) координации не мешает: эталон мог появиться.
    first.payload = {**first.payload, "ai_coordination": {"status": "skipped"}}
    await db_session.commit()
    after_skipped = await coord_jobs.enqueue_coordination(
        db_session, rebuilt, settings, target_axes_sha256=FPS
    )
    assert after_skipped.id != first.id and after_skipped.status is JobStatus.QUEUED
    # Оси цели изменились (другие конструкции вида) - новое задание.
    rebuilt_again = await _walls(db_session, convert)
    await db_session.commit()
    moved = await coord_jobs.enqueue_coordination(
        db_session, rebuilt_again, settings, target_axes_sha256="c" * 64
    )
    assert moved.id not in {first.id, after_skipped.id}
    # Ручной запуск ставит всегда (после rejected), даже при тех же осях.
    after_skipped.status = JobStatus.SUCCEEDED
    after_skipped.payload = {**after_skipped.payload, "ai_coordination": {"status": "rejected"}}
    await db_session.commit()
    manual = await coord_jobs.enqueue_coordination(
        db_session, rebuilt, settings, retry_failed=True, target_axes_sha256=FPS
    )
    assert manual.status is JobStatus.QUEUED and manual.id not in {first.id, after_skipped.id}


async def test_hook_asks_the_model_again_only_when_axes_changed(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    convert, target, _, settings = await _pair(db_session, build_api, fake_storage, workspace_id)
    rebuilt = await _walls(db_session, convert)
    await db_session.commit()
    read_axes = AsyncMock(return_value=_axes(TARGET_V, TARGET_H))
    monkeypatch.setattr(coord_jobs, "target_view_axes", read_axes)
    await ai_loop.after_walls(db_session, target, settings, fake_storage)
    assert len(await _queued(db_session)) == 1
    # Правщик перестроил конструкции, оси те же: нового вызова модели нет.
    await ai_loop.after_walls(db_session, rebuilt, settings, fake_storage)
    assert len(await _queued(db_session)) == 1
    # Оси изменились: новая координация.
    read_axes.return_value = _axes({**TARGET_V, "4": TARGET_V["4"] + 500.0}, TARGET_H)
    await ai_loop.after_walls(db_session, rebuilt, settings, fake_storage)
    assert len(await _queued(db_session)) == 2
