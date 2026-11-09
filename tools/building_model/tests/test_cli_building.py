"""Команда `revit-building`: состав листов, акты, сообщения без путей. Только синтетика."""

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

from building_model.cli import main
from tests.revit_fixture import building_sheet
from tests.synth import make_sheet

GROUPS = [{"sheets": [0, 1, 2]}, {"sheets": [3]}]


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Path]:
    """Комплект: группа 0 — страницы 0 и 1 (этажи 5-6 и 7-8) и разрез 2; группа 1 — страница 3."""
    sheets = [
        building_sheet(0, [5, 6], [14.0, 17.3]),
        building_sheet(1, [7, 8], [20.6, 23.9], origin=("2", "B"), shift=(400.0, -700.0)),
        make_sheet(page=2, kind={"kind": "section"}),
        building_sheet(3, [5, 6], [14.0, 17.3]),
    ]
    source = tmp_path / "set.json"
    source.write_text(json.dumps({"sheets": sheets, "buildings": GROUPS}))
    models = tmp_path / "models"
    models.mkdir()
    for page in (0, 1, 3):
        out = models / f"model_{page}.json"
        assert main(["build", "--input", str(source), "--page", str(page), "--out", str(out)]) == 0
    return {"source": source, "models": models, "dir": tmp_path}


def _approve(env: dict[str, Path], pages: list[int]) -> Path:
    approvals = env["dir"] / "approvals"
    approvals.mkdir(exist_ok=True)
    for page in pages:
        args = [
            "approve",
            "--input",
            str(env["source"]),
            "--model",
            str(env["models"] / f"model_{page}.json"),
        ]
        args += [
            "--page",
            str(page),
            "--by",
            "Тестовый Человек",
            "--out",
            str(approvals / f"approval_{page}.json"),
        ]
        assert main(args) == 0
    return approvals


def _run(env: dict[str, Path], *extra: str, group: str = "0", out: str = "b.json") -> int:
    args = ["revit-building", "--input", str(env["source"]), "--models-dir", str(env["models"])]
    return main([*args, "--building", group, "--out", str(env["dir"] / out), *extra])


def _manifest(env: dict[str, Path], out: str = "b.json") -> dict[str, object]:
    data = json.loads((env["dir"] / out).read_text(encoding="utf-8"))
    manifest: dict[str, object] = data["manifest"]
    return manifest


def test_unapproved_test_builds_group_and_records_skipped_page(env: dict[str, Path]) -> None:
    assert _run(env, "--unapproved-test") == 0
    manifest = _manifest(env)
    building = manifest["building"]
    assert isinstance(building, dict)
    assert building["skipped_pages"] == [{"page": 2, "reason": "kind:section"}]
    assert building["added_pages"] == [] and building["excluded_pages"] == []
    assert manifest["scale_status"] == "candidate"
    sheets = manifest["sheets"]
    assert isinstance(sheets, list) and [s["page"] for s in sheets] == [0, 1]
    assert building["input_sha256"] == hashlib.sha256(env["source"].read_bytes()).hexdigest()


def test_requires_exactly_one_of_approvals_dir_and_flag(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(env) == 2
    assert "--approvals-dir" in capsys.readouterr().err
    approvals = _approve(env, [0, 1])
    assert _run(env, "--unapproved-test", "--approvals-dir", str(approvals)) == 2
    assert not (env["dir"] / "b.json").exists()


def test_with_approvals_dir_is_human_and_reproducible(env: dict[str, Path]) -> None:
    approvals = _approve(env, [0, 1])
    digests = []
    for name in ("a.json", "b.json"):
        assert _run(env, "--approvals-dir", str(approvals), out=name) == 0
        digests.append(hashlib.sha256((env["dir"] / name).read_bytes()).hexdigest())
    assert digests[0] == digests[1]
    manifest = _manifest(env, "a.json")
    assert manifest["scale_status"] == "human"


def test_missing_approval_lists_all_pages_without_paths(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    approvals = _approve(env, [])
    assert _run(env, "--approvals-dir", str(approvals)) == 2
    err = capsys.readouterr().err
    assert "0, 1" in err and "approval_" in err
    assert str(env["dir"]) not in err
    assert not (env["dir"] / "b.json").exists()
    _approve(env, [0])
    assert _run(env, "--approvals-dir", str(approvals)) == 2
    err = capsys.readouterr().err
    assert "страниц: 1" in err


def test_exclude_page_and_add_page_are_recorded(env: dict[str, Path]) -> None:
    assert _run(env, "--unapproved-test", "--exclude-page", "1", "--exclude-page", "9") == 0
    building = _manifest(env)["building"]
    assert isinstance(building, dict)
    assert building["excluded_pages"] == [1, 9]
    sheets = _manifest(env)["sheets"]
    assert isinstance(sheets, list) and [s["page"] for s in sheets] == [0]
    # Страница 3 из другой группы с теми же уровнями L5/L6: конфликт, пакета нет.
    assert _run(env, "--unapproved-test", "--add-page", "3", out="c.json") == 2
    assert not (env["dir"] / "c.json").exists()
    assert (
        _run(env, "--unapproved-test", "--add-page", "3", "--exclude-page", "0", out="d.json") == 0
    )
    added = _manifest(env, "d.json")["building"]
    assert isinstance(added, dict) and added["added_pages"] == [3]
    pages = _manifest(env, "d.json")["sheets"]
    assert isinstance(pages, list) and [s["page"] for s in pages] == [1, 3]


def test_add_page_conflict_message_names_keys_and_pages(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(env, "--unapproved-test", "--add-page", "3") == 2
    err = capsys.readouterr().err
    assert "конфликт уровней" in err and "L5" in err and "страница 3" in err
    assert str(env["dir"]) not in err


def test_unknown_group_and_unknown_page(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    for group in ("7", "-1"):
        assert _run(env, "--unapproved-test", group=group) == 2
        err = capsys.readouterr().err
        assert "нет группы зданий" in err and str(env["dir"]) not in err
    assert _run(env, "--unapproved-test", "--add-page", "99") == 2
    assert "99" in capsys.readouterr().err


def test_missing_model_file_has_no_path(
    env: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    (env["models"] / "model_1.json").unlink()
    assert _run(env, "--unapproved-test") == 2
    err = capsys.readouterr().err
    assert "нет файла модели для страницы 1" in err and str(env["dir"]) not in err


def test_second_group_alone(env: dict[str, Path]) -> None:
    assert _run(env, "--unapproved-test", group="1", out="g1.json") == 0
    manifest = _manifest(env, "g1.json")
    sheets = manifest["sheets"]
    assert isinstance(sheets, list) and [s["page"] for s in sheets] == [3]


def test_building_schema_command(tmp_path: Path) -> None:
    out = tmp_path / "schema.json"
    assert main(["revit-building-schema", "--out", str(out)]) == 0
    schema = json.loads(out.read_text(encoding="utf-8"))
    assert schema["title"] == "RevitBuildingPackage"
    assert schema["additionalProperties"] is False


def test_command_runs_with_blocked_plangeom_and_pillow(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Команда работает без plangeom и Pillow: модули импортируются заново."""
    saved = {k: v for k, v in sys.modules.items() if k.split(".")[0] == "building_model"}
    for name in saved:
        del sys.modules[name]
    for name in ("plangeom", "PIL", "pypdfium2"):
        monkeypatch.setitem(sys.modules, name, None)
    try:
        fresh_main = importlib.import_module("building_model.cli").main
        args = ["revit-building", "--input", str(env["source"]), "--models-dir", str(env["models"])]
        assert (
            fresh_main(
                [*args, "--building", "0", "--unapproved-test", "--out", str(env["dir"] / "f.json")]
            )
            == 0
        )
    finally:
        for name in [k for k in sys.modules if k.split(".")[0] == "building_model"]:
            del sys.modules[name]
        sys.modules.update(saved)
    assert (env["dir"] / "f.json").is_file()
