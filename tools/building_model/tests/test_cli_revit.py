import hashlib
import json
from pathlib import Path

import pytest

from building_model.cli import main
from tests.revit_fixture import synthetic_sheet


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    source = tmp_path / "set.json"
    source.write_text(json.dumps({"sheets": [synthetic_sheet()], "buildings": []}))
    model = tmp_path / "model_0.json"
    assert main(["build", "--input", str(source), "--page", "0", "--out", str(model)]) == 0
    return {"source": source, "model": model, "dir": tmp_path}


def _approve(files: dict[str, Path]) -> Path:
    out = files["dir"] / "approval.json"
    code = main(
        ["approve", "--input", str(files["source"]), "--model", str(files["model"]),
         "--page", "0", "--by", "Тестовый Человек", "--out", str(out)]
    )  # fmt: skip
    assert code == 0
    return out


def test_revit_refuses_without_approval_or_flag(
    files: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    out = files["dir"] / "package.json"
    assert main(["revit", "--model", str(files["model"]), "--out", str(out)]) == 2
    assert "--approval" in capsys.readouterr().err
    assert not out.exists()


def test_revit_refuses_both_approval_and_flag(files: dict[str, Path]) -> None:
    approval = _approve(files)
    out = files["dir"] / "package.json"
    args = ["revit", "--model", str(files["model"]), "--approval", str(approval), "--out", str(out)]
    assert main([*args, "--unapproved-test"]) == 2
    assert not out.exists()


def test_revit_with_approval_is_reproducible(files: dict[str, Path]) -> None:
    approval = _approve(files)
    digests = []
    for name in ("a.json", "b.json"):
        out = files["dir"] / name
        args = [
            "revit",
            "--model",
            str(files["model"]),
            "--approval",
            str(approval),
            "--out",
            str(out),
        ]
        assert main(args) == 0
        digests.append(hashlib.sha256(out.read_bytes()).hexdigest())
    assert digests[0] == digests[1]
    data = json.loads((files["dir"] / "a.json").read_text(encoding="utf-8"))
    assert data["manifest"]["scale_status"] == "human"
    assert data["manifest"]["approval"]["by"] == "Тестовый Человек"


def test_revit_unapproved_test_marks_candidate(files: dict[str, Path]) -> None:
    out = files["dir"] / "t.json"
    assert (
        main(["revit", "--model", str(files["model"]), "--unapproved-test", "--out", str(out)]) == 0
    )
    manifest = json.loads(out.read_text(encoding="utf-8"))["manifest"]
    assert manifest["approval"] is None
    assert manifest["scale_status"] == "candidate"


def test_revit_refuses_changed_model(
    files: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    approval = _approve(files)
    files["model"].write_text(files["model"].read_text(encoding="utf-8") + "\n", encoding="utf-8")
    out = files["dir"] / "package.json"
    code = main(
        ["revit", "--model", str(files["model"]), "--approval", str(approval), "--out", str(out)]
    )
    assert code == 2
    assert "sha256" in capsys.readouterr().err
    assert not out.exists()


def test_revit_schema_command(tmp_path: Path) -> None:
    out = tmp_path / "schema.json"
    assert main(["revit-schema", "--out", str(out)]) == 0
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert schema["title"] == "RevitPackage"
    assert schema["additionalProperties"] is False


def test_run_with_input_builds_models_and_no_packages(
    files: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = files["dir"] / "run"
    code = main(["run", "--input", str(files["source"]), "--out-dir", str(out_dir)])
    printed = capsys.readouterr().out
    assert code == 0
    assert (out_dir / "model_0.json").is_file()
    assert (out_dir / "index.html").is_file()
    assert not list(out_dir.glob("package*"))
    assert "approve" in printed
