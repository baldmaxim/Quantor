import hashlib
import json
from pathlib import Path

import pytest

from building_model.approval import make_approval
from building_model.cli import main
from building_model.pipeline import TenderArgs, build_model, dumps_model
from building_model.reader import document_from_json
from tests.synth import make_sheet, wall


def _prepare(tmp_path: Path, page: int = 4, mm_per_pt: float | None = 35.0) -> tuple[Path, Path]:
    sheet = make_sheet(page=page, walls=[wall("W0", (0, 0), (4000, 0))])
    sheet["scale"] = {"mm_per_pt": mm_per_pt, "method": "axes", "confident": True}
    source = tmp_path / "set.json"
    source.write_text(json.dumps({"sheets": [sheet], "buildings": []}))
    model = tmp_path / "model.json"
    model.write_text(
        dumps_model(
            build_model(document_from_json(json.loads(source.read_text())), page, TenderArgs())
        )
    )
    return source, model


def test_approval_binds_model_bytes_and_scale(tmp_path: Path) -> None:
    source, model = _prepare(tmp_path)
    approval = make_approval(
        source, model, 4, "  Иван Тестов ", "проверено", now="2026-01-02T03:04:05Z"
    )
    assert approval.model_sha256 == hashlib.sha256(model.read_bytes()).hexdigest()
    assert (approval.page, approval.mm_per_pt, approval.by) == (4, 35.0, "Иван Тестов")
    assert (approval.at, approval.note) == ("2026-01-02T03:04:05Z", "проверено")


def test_empty_by_is_an_error(tmp_path: Path) -> None:
    source, model = _prepare(tmp_path)
    for blank in ("", "   "):
        with pytest.raises(ValueError, match="--by"):
            make_approval(source, model, 4, blank)


def test_page_mismatch_and_missing_scale_are_errors(tmp_path: Path) -> None:
    source, model = _prepare(tmp_path)
    with pytest.raises(ValueError, match="нет страницы"):
        make_approval(source, model, 9, "А")
    other = make_sheet(page=9)
    source.write_text(json.dumps({"sheets": [other], "buildings": []}))
    with pytest.raises(ValueError, match="другой страницы"):
        make_approval(source, model, 9, "А")
    source2, model2 = _prepare(tmp_path, mm_per_pt=None)
    with pytest.raises(ValueError, match="нет масштаба"):
        make_approval(source2, model2, 4, "А")


def test_approve_command_writes_file_and_empty_by_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, model = _prepare(tmp_path)
    out = tmp_path / "approval.json"
    args = [
        "approve",
        "--input",
        str(source),
        "--model",
        str(model),
        "--page",
        "4",
        "--out",
        str(out),
    ]
    assert main([*args, "--by", ""]) == 2
    assert "--by" in capsys.readouterr().err
    assert not out.exists()
    assert main([*args, "--by", "Иван Тестов", "--note", "ок"]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "quantor.model_approval.v1"
    assert list(data) == [
        "schema",
        "page",
        "model_sha256",
        "mm_per_pt",
        "by",
        "at",
        "note",
        "accepted_blockers",
    ]
    assert data["accepted_blockers"] == []
    assert data["at"].endswith("Z")


def test_pydantic_error_does_not_echo_file_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, _ = _prepare(tmp_path)
    bad = tmp_path / "bad_model.json"
    bad.write_text(json.dumps({"private_marker_name": "секретное имя помещения"}))
    out = tmp_path / "approval.json"
    code = main(
        ["approve", "--input", str(source), "--model", str(bad), "--page", "4", "--by", "А",
         "--out", str(out)]
    )  # fmt: skip
    err = capsys.readouterr().err
    assert code == 2
    assert "private_marker_name" not in err and "секретное" not in err
    assert not out.exists()
