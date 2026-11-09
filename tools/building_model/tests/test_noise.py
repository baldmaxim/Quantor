"""Блокер шумного листа `openings_noise`, его принятие человеком и отказ адаптера."""

import json
from pathlib import Path

import pytest

from building_model.approval import ApprovalOut, make_approval
from building_model.canonical import BuildingModel
from building_model.cli import main
from building_model.markup import MarkupResult, render_index
from building_model.params import Params
from building_model.pipeline import TenderArgs, build_model, dumps_model
from building_model.reader import document_from_json
from building_model.revit import RevitRefusalError, build_package, refusal_reasons
from tests.revit_fixture import model_sha
from tests.synth import JsonObj, build, gap_item, make_sheet, wall
from tests.test_markup import _row


def _noisy_sheet(far: int, page: int = 0) -> JsonObj:
    """Одна стена и `far` пустых проёмов далеко от неё: у всех нет хозяина."""
    openings = [
        gap_item(f"H{i}", (9000 + 1000 * i, 9000), (9800 + 1000 * i, 9000)) for i in range(far)
    ]
    return make_sheet(page=page, walls=[wall("W0", (0, 0), (4000, 0))], openings=openings)


def _noise_items(model: BuildingModel) -> list[dict[str, float | int | str | None]]:
    return [i.detail for i in model.review.items if i.code == "openings_noise"]


def test_noise_blocker_at_count_threshold() -> None:
    assert _noise_items(build(_noisy_sheet(99))) == []
    model = build(_noisy_sheet(100))
    assert _noise_items(model) == [{"unhosted": 100, "openings_total": 100}]
    item = next(i for i in model.review.items if i.code == "openings_noise")
    assert (item.severity, item.element) == ("blocker", None)


def test_noise_blocker_share_threshold() -> None:
    # 3 из 6 проёмов без хозяина: доля ровно 0,5 — блокер; при 0,6 — нет.
    params = Params(noise_unhosted_min=3, noise_unhosted_share=0.5)
    sheet = make_sheet(
        walls=[wall("W0", (0, 0), (6000, 0))],
        windows=[gap_item(f"O{i}", (500 + 1000 * i, 0), (1300 + 1000 * i, 0)) for i in range(3)],
        openings=[
            gap_item(f"H{i}", (9000 + 1000 * i, 9000), (9800 + 1000 * i, 9000)) for i in range(3)
        ],
    )
    assert _noise_items(build(sheet, params)) == [{"unhosted": 3, "openings_total": 6}]
    assert _noise_items(build(sheet, Params(noise_unhosted_min=3, noise_unhosted_share=0.6))) == []


def test_noise_blocker_needs_both_conditions() -> None:
    # Доля 100 %, но число ниже порога; число выше порога, но доля ниже.
    assert _noise_items(build(_noisy_sheet(5))) == []
    sheet = _noisy_sheet(3)
    low_share = Params(noise_unhosted_min=2, noise_unhosted_share=1.1)
    assert _noise_items(build(sheet, low_share)) == []


def _files(tmp_path: Path, far: int) -> tuple[Path, Path]:
    source = tmp_path / "set.json"
    source.write_text(json.dumps({"sheets": [_noisy_sheet(far, page=4)], "buildings": []}))
    model = tmp_path / "model.json"
    model.write_text(
        dumps_model(
            build_model(document_from_json(json.loads(source.read_text())), 4, TenderArgs())
        )
    )
    return source, model


def test_approval_refuses_noisy_sheet_without_flag(tmp_path: Path) -> None:
    source, model = _files(tmp_path, 100)
    with pytest.raises(ValueError, match="openings_noise"):
        make_approval(source, model, 4, "А")
    approval = make_approval(source, model, 4, "А", accept_noise=True)
    assert approval.accepted_blockers == ["openings_noise"]


def test_flag_on_quiet_sheet_records_nothing(tmp_path: Path) -> None:
    source, model = _files(tmp_path, 3)
    assert make_approval(source, model, 4, "А", accept_noise=True).accepted_blockers == []
    assert make_approval(source, model, 4, "А").accepted_blockers == []


def test_approval_model_accepts_only_openings_noise() -> None:
    base = {"page": 0, "model_sha256": "x", "mm_per_pt": 1.0, "by": "a", "at": "t"}
    with pytest.raises(ValueError, match="no_axes_origin"):
        ApprovalOut.model_validate({**base, "accepted_blockers": ["no_axes_origin"]})
    ok = ApprovalOut.model_validate({**base, "accepted_blockers": ["openings_noise"]})
    assert ok.accepted_blockers == ["openings_noise"]


def test_cli_approve_accept_noise(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source, model = _files(tmp_path, 100)
    out = tmp_path / "approval.json"
    args = ["approve", "--input", str(source), "--model", str(model), "--page", "4"]
    args += ["--by", "Иван", "--out", str(out)]
    assert main(args) == 2
    assert "--accept-noise" in capsys.readouterr().err
    assert not out.exists()
    assert main([*args, "--accept-noise"]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["accepted_blockers"] == ["openings_noise"]


def _noisy_model_and_approval(accepted: list[str]) -> tuple[BuildingModel, ApprovalOut, str]:
    model = build(_noisy_sheet(100))
    sha = model_sha(model)
    approval = ApprovalOut(
        page=0, model_sha256=sha, mm_per_pt=35.0, by="А", at="t", accepted_blockers=accepted
    )
    return model, approval, sha


def test_adapter_refuses_noisy_sheet_unless_accepted() -> None:
    model, approval, sha = _noisy_model_and_approval([])
    with pytest.raises(RevitRefusalError, match="openings_noise"):
        build_package(model, approval, sha)
    model, accepted, sha = _noisy_model_and_approval(["openings_noise"])
    assert build_package(model, accepted, sha).manifest.approval == accepted


def test_unapproved_test_still_refuses_noisy_sheet() -> None:
    model, _, sha = _noisy_model_and_approval([])
    with pytest.raises(RevitRefusalError, match="openings_noise"):
        build_package(model, None, sha)


def test_accepted_noise_does_not_lift_other_blockers() -> None:
    model, approval, sha = _noisy_model_and_approval(["openings_noise"])
    other = model.review.items[0].model_copy(
        update={"code": "no_axes_origin", "severity": "blocker"}
    )
    review = model.review.model_copy(update={"items": [*model.review.items, other]})
    changed = model.model_copy(update={"review": review})
    reasons = refusal_reasons(changed, approval, sha)
    assert (
        len(reasons) == 1 and "no_axes_origin" in reasons[0] and "openings_noise" not in reasons[0]
    )
    # Чужой код в акте (в обход проверки модели) тоже ничего не снимает.
    forged = approval.model_copy(update={"accepted_blockers": ["no_axes_origin"]})
    assert "no_axes_origin" in " ".join(refusal_reasons(changed, forged, sha))


def test_markup_row_for_noisy_sheet() -> None:
    quiet = render_index(MarkupResult([_row()], {}, 1, 0, 1))
    assert "шумный лист" not in quiet and "--accept-noise" not in quiet
    noisy = render_index(
        MarkupResult([_row(noisy=True, approve_command="cmd --accept-noise")], {}, 1, 0, 1)
    )
    assert "шумный лист: сначала проверьте" in noisy
    assert "cmd --accept-noise" in noisy
