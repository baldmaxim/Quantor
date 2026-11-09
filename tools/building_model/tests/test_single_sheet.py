import json
from pathlib import Path

import pytest

from building_model.cli import main
from building_model.pipeline import TenderArgs, build_model
from building_model.reader import SheetValidationError, UnsupportedVersionError, document_from_json
from tests.synth import make_sheet, wall


def _page_output(page: int = 7) -> dict[str, object]:
    """Форма выхода parse_page: верхнего page нет, номер лежит в source.page."""
    sheet = make_sheet(page=page, walls=[wall("W0", (0, 0), (4000, 0))])
    del sheet["page"]
    return sheet


def test_single_sheet_without_top_level_page_is_accepted() -> None:
    doc = document_from_json(_page_output(7))
    assert doc.pages() == [7]
    model = build_model(doc, 7, TenderArgs())
    assert len(model.walls) == 1
    assert model.stats["sheet"] == {
        "page": 7,
        "section": "",
        "kind": "plan",
        "verdict": "needs_review",
        "building_group": None,
        "floors": [3],
    }


def test_single_sheet_with_page_still_works() -> None:
    assert document_from_json(make_sheet(page=3, walls=[])).pages() == [3]


def test_single_sheet_without_any_page_number_is_an_error() -> None:
    raw = _page_output()
    raw["source"] = {"width_pt": 1.0, "height_pt": 1.0}
    with pytest.raises(SheetValidationError, match="номера страницы"):
        document_from_json(raw)


def test_version_gate_stays_strict_for_single_sheet() -> None:
    raw = _page_output()
    raw["plangeom_version"] = "0.2.0"
    with pytest.raises(UnsupportedVersionError):
        document_from_json(raw)


def test_build_command_reads_single_sheet_file(tmp_path: Path) -> None:
    source = tmp_path / "page.json"
    source.write_text(json.dumps(_page_output(7)), encoding="utf-8")
    out = tmp_path / "m.json"
    assert main(["build", "--input", str(source), "--page", "7", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["stats"]["sheet"]["page"] == 7
