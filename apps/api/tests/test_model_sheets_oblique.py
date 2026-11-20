"""Чертёж наложением: оси листа под углом к листу (корпус повёрнут на плане) идут в подгонку."""

from __future__ import annotations

import math

from app.services import model_sheets as ms


def _sheet_from_model(
    model: list[ms.ModelAxis], theta: float, scale: float, offset: tuple[float, float]
) -> list[ms.SheetAxis]:
    """Лист, каким он выглядел бы при известном подобии: ось под углом - точка и угол на листе."""
    c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    out = []
    for axis in model:
        mx, my = axis.p0
        # модель = R · diag(scale, −scale) · pt + t
        # →  pt = diag(1, −1) · R⁻¹ · (модель − t) / scale
        dx, dy = mx - offset[0], my - offset[1]
        rx, ry = (c * dx + s * dy) / scale, (-s * dx + c * dy) / scale
        point = (rx, -ry)
        ddx, ddy = axis.p1[0] - axis.p0[0], axis.p1[1] - axis.p0[1]
        ex, ey = c * ddx + s * ddy, -s * ddx + c * ddy
        angle = math.degrees(math.atan2(-ey, ex)) % 180.0
        out.append(ms.SheetAxis(axis.tag, "oblique", 0.0, angle, point))
    return out


def test_fit_sheet_with_oblique_axes_only() -> None:
    # корпус повёрнут на 7° к осям площадки: на листе ни одной вертикали и горизонтали
    model = [
        ms.ModelAxis("7/А", (123366.0, 51307.0), (56221.0, 59551.0)),
        ms.ModelAxis("7/Л", (130526.0, 109619.0), (63381.0, 117863.0)),
        ms.ModelAxis("7/1", (71613.0, 120834.0), (63337.0, 53425.0)),
        ms.ModelAxis("7/11", (126898.0, 114046.0), (118621.0, 46637.0)),
    ]
    sheet = _sheet_from_model(model, 0.0, 35.2744, (49017.0, 129334.0))
    fit, why = ms.fit_sheet(sheet, model, frame_scale=35.2744)
    assert why is None and fit is not None
    assert fit.rms_mm < 0.5 and abs(fit.scale - 35.2744) < 1e-3
    assert abs(((fit.rotation_deg + 180) % 360) - 180) < 0.01
    assert abs(fit.offset[0] - 49017.0) < 0.5 and abs(fit.offset[1] - 129334.0) < 0.5


def test_fit_sheet_oblique_one_direction_is_refused() -> None:
    model = [
        ms.ModelAxis("7/А", (123366.0, 51307.0), (56221.0, 59551.0)),
        ms.ModelAxis("7/Л", (130526.0, 109619.0), (63381.0, 117863.0)),
    ]
    sheet = _sheet_from_model(model, 0.0, 35.2744, (49017.0, 129334.0))
    fit, why = ms.fit_sheet(sheet, model, frame_scale=35.2744)
    assert fit is None and why is not None


def test_sheet_axes_reads_oblique_items() -> None:
    raw = {
        "axes": {
            "items": [
                {"label": "7н", "orient": "vertical", "pos_pt": 1438.2},
                {
                    "label": "7/А",
                    "orient": "oblique",
                    "angle_deg": 7.0,
                    "pos_pt": 1.0,
                    "point_pt": [258.9, 1985.0],
                },
                {"label": "битая", "orient": "oblique", "angle_deg": 7.0},
            ]
        }
    }
    axes = ms.sheet_axes(raw)
    assert [(a.label, a.orient) for a in axes] == [("7н", "vertical"), ("7/А", "oblique")]
    assert axes[1].angle_deg == 7.0 and axes[1].point_pt == (258.9, 1985.0)
