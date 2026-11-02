import json
from pathlib import Path

import pytest

from building_model.cli import main
from building_model.params import Params
from building_model.pipeline import TenderArgs
from building_model.survey import run_survey
from tests.synth import document, make_sheet, wall


def _write(path: Path, *sheets: dict[str, object]) -> Path:
    path.write_text(json.dumps({"sheets": list(sheets), "buildings": [{"sheets": [0, 1]}]}))
    return path


def test_build_command_writes_identical_files(tmp_path: Path) -> None:
    source = _write(tmp_path / "set.json", make_sheet(walls=[wall("W0", (0, 0), (4000, 0))]))
    outputs = []
    for name in ("a.json", "b.json"):
        assert (
            main(["build", "--input", str(source), "--page", "0", "--out", str(tmp_path / name)])
            == 0
        )
        outputs.append((tmp_path / name).read_bytes())
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["walls"][0]["thickness_mm"] == 200.0


def test_build_command_refuses_unknown_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _write(tmp_path / "set.json", make_sheet(plangeom_version="9.9.9"))
    code = main(["build", "--input", str(source), "--page", "0", "--out", str(tmp_path / "m.json")])
    assert code == 2
    assert "9.9.9" in capsys.readouterr().err
    assert not (tmp_path / "m.json").exists()


def test_survey_counts_plans_exclusions_and_picks_typical_sheet() -> None:
    plan = make_sheet(page=0, title={"floors": [3], "level_m": 9.9})
    typical = make_sheet(
        page=1,
        title={"floors": [4, 5], "level_m": 13.2},
        walls=[wall("W0", (0, 0), (4000, 0))],
    )
    section = make_sheet(page=2, kind={"kind": "section"})
    doc = document(plan, typical, section, buildings=[{"sheets": [0, 1]}])
    result = run_survey(doc, Params(), TenderArgs())
    assert result["excluded_by_reason"] == {"kind:section": 1}
    totals = result["totals"]
    assert isinstance(totals, dict)
    assert totals["plan_sheets_built"] == 2
    assert result["typical_candidate"] is not None
    candidate = result["typical_candidate"]
    assert isinstance(candidate, dict)
    assert candidate["page"] == 1
