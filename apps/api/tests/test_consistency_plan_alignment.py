"""Правило совмещения плана с уровнем `consistency.align.v1` и проверка «план ↔ уровень» (С3)."""

from __future__ import annotations

import pytest

from app.services.consistency.align_checks import AlignmentView, run_align_checks
from app.services.consistency.frame_checks import CheckCode, CheckStatus, RefKind
from app.services.consistency.plan_alignment import (
    NO_REFERENCE,
    RESIDUAL_CHECK_MM,
    AlignResult,
    AlignScaleSource,
    SheetAxes,
    align_section,
    match,
    pick_reference,
    rotate_axes,
    rotate_point,
)

CAL = AlignScaleSource.CALIBRATION
V = {"1": 0.0, "2": 6000.0, "3": 12000.0, "4": 18000.0}
H = {"А": 0.0, "Б": 6000.0, "В": 12000.0}


def _sheet(
    key: str,
    vertical: dict[str, float],
    horizontal: dict[str, float],
    *,
    is_ar: bool = False,
    scale: AlignScaleSource | None = CAL,
    problem: str | None = None,
) -> SheetAxes:
    return SheetAxes(key, is_ar, vertical, horizontal, scale, problem)


def _moved(axes: dict[str, float], shift: float) -> dict[str, float]:
    return {label: value - shift for label, value in axes.items()}


REF = _sheet("ar", V, H, is_ar=True)


def test_shift_is_found_by_axis_labels() -> None:
    other = _sheet("ios", _moved(V, 100.0), _moved(H, -250.0))
    result = match(REF, other)
    assert result.result is AlignResult.ALIGNED and result.reasons == ()
    assert (result.rotation_deg, result.dx_mm, result.dy_mm) == (0, 100.0, -250.0)
    assert result.axes == ("1", "2", "3", "4", "А", "Б", "В")
    assert (result.common_axes, result.agreed_axes) == (7, 7)
    assert result.residual_rms_mm == 0.0 and result.residual_max_mm == 0.0


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_rotated_plan_is_found_and_flagged(rotation: int) -> None:
    # Лист повёрнут на угол, обратный найденному: поворот возвращает его к эталону.
    back = (360 - rotation) % 360
    vertical, horizontal = rotate_axes(V, H, back)
    result = match(REF, _sheet("ios", vertical, horizontal))
    assert result.result is AlignResult.CHECK
    assert result.rotation_deg == rotation
    assert result.dx_mm == pytest.approx(0.0) and result.dy_mm == pytest.approx(0.0)
    assert f"повёрнут относительно эталона на {rotation}°" in result.reasons[0]


def test_rotate_point_matches_rotate_axes() -> None:
    # Пересечение осей 1/А (x = 5, y = 7) после поворота лежит на повёрнутых осях; при 90° и 270°
    # вертикаль и горизонталь меняются местами.
    for rotation in (0, 180):
        vertical, horizontal = rotate_axes({"1": 5.0}, {"А": 7.0}, rotation)
        assert (vertical["1"], horizontal["А"]) == rotate_point(5.0, 7.0, rotation)
    for rotation in (90, 270):
        vertical, horizontal = rotate_axes({"1": 5.0}, {"А": 7.0}, rotation)
        assert (vertical["А"], horizontal["1"]) == rotate_point(5.0, 7.0, rotation)
    with pytest.raises(ValueError, match="кратен 90"):
        rotate_axes(V, H, 45)


def test_outlier_axis_does_not_move_the_shift_but_is_reported() -> None:
    vertical = _moved(V, 100.0)
    vertical["3"] += 2500.0  # выноска промежуточной оси
    result = match(REF, _sheet("ios", vertical, _moved(H, 0.0)))
    assert result.result is AlignResult.CHECK and result.dx_mm == 100.0
    assert "3" not in result.axes and result.agreed_axes == 6 and result.common_axes == 7
    assert any("вертикальных оси расходятся с остальными: 3" in r for r in result.reasons)


def test_residual_above_threshold_needs_check() -> None:
    noisy = {
        label: value + (i % 2) * 2 * (RESIDUAL_CHECK_MM + 20)
        for i, (label, value) in enumerate(V.items())
    }
    result = match(REF, _sheet("ios", noisy, H))
    assert result.result is AlignResult.CHECK
    assert result.residual_rms_mm is not None and result.residual_rms_mm > RESIDUAL_CHECK_MM
    assert any("невязка" in reason for reason in result.reasons)


def test_single_common_axis_and_chain_scale_need_check() -> None:
    other = _sheet("ios", {"2": 6000.0}, {"Б": 6000.0}, scale=AlignScaleSource.DIMENSION_CHAINS)
    result = match(REF, other)
    assert result.result is AlignResult.CHECK
    assert sum("совпала одна из" in reason for reason in result.reasons) == 2
    assert "масштаб листа подобран по размерным цепочкам" in result.reasons[-1]


def test_no_common_axes_fails_with_reason() -> None:
    result = match(REF, _sheet("ios", {"7": 0.0}, {"Ж": 0.0}))
    assert result.result is AlignResult.FAILED and result.dx_mm is None
    assert result.reasons == (
        "нет общих вертикальных осей с эталоном",
        "нет общих горизонтальных осей с эталоном",
    )


def test_ambiguous_shift_fails() -> None:
    vertical = {"1": 0.0, "2": 6000.0, "3": 12000.0 - 3000.0, "4": 18000.0 - 3000.0}
    result = match(REF, _sheet("ios", vertical, H))
    assert result.result is AlignResult.FAILED
    assert "вертикальных оси расходятся с эталоном" in result.reasons[0]


def test_reference_is_the_ar_plan_with_most_axes_or_the_preferred_one() -> None:
    small = _sheet("ar-small", {"1": 0.0}, {"А": 0.0}, is_ar=True)
    chains = _sheet("ar-chains", V, H, is_ar=True, scale=AlignScaleSource.DIMENSION_CHAINS)
    ios = _sheet("ios", V, H)
    sheets = [ios, small, chains, REF]
    assert pick_reference(sheets) == 3  # больше осей, калибровка человеком
    assert pick_reference(sheets, preferred="ar-small") == 1
    assert pick_reference([ios]) is None


def test_section_alignment_marks_reference_unusable_and_missing_reference() -> None:
    broken = _sheet("broken", {}, {}, problem="оси на листе не распознаны")
    other = _sheet("ios", _moved(V, 10.0), H)
    results = align_section([other, broken, REF])
    assert [r.result for r in results] == [
        AlignResult.ALIGNED,
        AlignResult.NOT_RUN,
        AlignResult.REFERENCE,
    ]
    assert results[0].reference_key == "ar" and results[0].dx_mm == 10.0
    assert results[1].reasons == ("оси на листе не распознаны",)
    assert results[2].reasons == () and results[2].reference_key == "ar"
    orphan = align_section([other])
    assert orphan[0].result is AlignResult.NOT_RUN and orphan[0].reasons == (NO_REFERENCE,)


# --------------------------------------------------------------------------- проверка


def _view(
    key: str,
    result: AlignResult,
    status: str,
    *,
    section: str | None = "1",
    residual: float | None = 0.0,
    reason: str | None = None,
) -> AlignmentView:
    return AlignmentView(
        id=key,
        building="1",
        section=section,
        label=f"АР · лист {key}",
        file_name="АР.pdf",
        page_index=0,
        result=result,
        status=status,
        residual_rms_mm=residual,
        reason=reason,
    )


def test_align_check_without_alignments_is_not_run() -> None:
    [only] = run_align_checks([])
    assert only.code is CheckCode.PLANS_ALIGNED and only.status is CheckStatus.NOT_RUN
    assert "запустите совмещение" in only.message


def test_align_check_per_section() -> None:
    checks = run_align_checks(
        [
            _view("a", AlignResult.REFERENCE, "confirmed"),
            _view("b", AlignResult.CHECK, "confirmed", residual=12.4),
            _view("c", AlignResult.ALIGNED, "candidate", section="2"),
            _view("d", AlignResult.NOT_RUN, "candidate", section="3", reason="нет CAD"),
            _view("e", AlignResult.ALIGNED, "rejected", section="3"),
        ]
    )
    by_section = {check.section: check for check in checks}
    assert by_section["1"].status is CheckStatus.MATCH
    assert by_section["1"].message == "корпус 1, секция 1: совмещено планов - 2, невязка до 12 мм."
    assert by_section["2"].status is CheckStatus.NOT_RUN
    assert "ждут подтверждения - 1" in by_section["2"].message
    mismatch = by_section["3"]
    assert mismatch.status is CheckStatus.MISMATCH
    assert "лист d: не совмещался (нет CAD)" in mismatch.message
    assert "лист e: совмещение отклонено" in mismatch.message
    assert [ref.kind for ref in mismatch.refs] == [RefKind.ALIGNMENT, RefKind.ALIGNMENT]
