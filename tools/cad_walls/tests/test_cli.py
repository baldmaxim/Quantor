"""Командная строка, детерминизм вывода, параметры."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cad_walls.cli import main
from cad_walls.errors import WallsError
from cad_walls.params import DEFAULT_PARAMS_PATH, canonical_sha256, load_params
from tests import synth


def _dxf(tmp_path: Path) -> Path:
    doc, msp = synth.new_doc()
    synth.add_union(msp, synth.MASONRY, (0, 0, 3000, 200), (1400, 200, 1500, 1800))
    synth.add_rect(msp, synth.MONOLITH, 5000, 0, 5400, 400)
    synth.add_rect(msp, synth.MASONRY, 6000, 0, 7000, 100)
    synth.add_rect(msp, synth.MASONRY, 8000, 0, 9000, 100)
    synth.add_door(doc, msp, "AR_DOOR_BLOCK_010", 7000, -400, 8000, 500)
    path = tmp_path / "plan.dxf"
    doc.saveas(str(path))
    return path


def test_two_runs_give_identical_bytes(tmp_path: Path) -> None:
    dxf = _dxf(tmp_path)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert main(["--dxf", str(dxf), "--out", str(a)]) == 0
    assert main(["--dxf", str(dxf), "--out", str(b)]) == 0
    assert a.read_bytes() == b.read_bytes()


def test_document_header_and_hashes(tmp_path: Path) -> None:
    dxf = _dxf(tmp_path)
    out = tmp_path / "walls.json"
    assert main(["--dxf", str(dxf), "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "quantor.cad_walls.v1"
    assert doc["generator"] == "cad_walls.v1.2"
    assert doc["params_version"] == "v1"
    assert doc["units"] == "mm"
    assert doc["dxf_sha256"] == hashlib.sha256(dxf.read_bytes()).hexdigest()
    raw = json.loads(DEFAULT_PARAMS_PATH.read_text(encoding="utf-8"))
    assert doc["params_sha256"] == canonical_sha256(raw)
    assert set(doc) == {
        "schema", "generator", "params_version", "params_sha256", "dxf_sha256", "units",
        "heights", "legend", "constructions", "frame_partitions", "openings", "slab", "slab_holes",
        "totals", "checks",
    }  # fmt: skip
    assert {o["kind"] for o in doc["openings"]} == {"door"}


def test_params_sha256_changes_with_content(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_PARAMS_PATH.read_text(encoding="utf-8"))
    raw["slab_thickness_mm"]["value"] = 220
    changed = tmp_path / "v2.json"
    changed.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    base, other = load_params(), load_params(changed)
    assert base.sha256 != other.sha256
    assert other.version == "v2"
    assert other.count("slab_thickness_mm") == 220


def test_params_missing_key_is_error(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_PARAMS_PATH.read_text(encoding="utf-8"))
    del raw["split_angle_deg"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(WallsError) as info:
        load_params(path)
    assert info.value.code == "params_invalid"


def test_missing_dxf_returns_json_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--dxf", str(tmp_path / "none.dxf"), "--out", str(tmp_path / "w.json")])
    assert code == 2
    err = json.loads(capsys.readouterr().err)
    assert err["code"] == "dxf_unreadable"


def test_bad_arguments_return_json_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--out", "x.json"])
    assert info.value.code == 2
    assert json.loads(capsys.readouterr().err)["code"] == "bad_arguments"


def test_pdf_requires_page(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dxf = _dxf(tmp_path)
    code = main(["--dxf", str(dxf), "--out", str(tmp_path / "w.json"), "--pdf", "x.pdf"])
    assert code == 2
    assert json.loads(capsys.readouterr().err)["code"] == "bad_arguments"
