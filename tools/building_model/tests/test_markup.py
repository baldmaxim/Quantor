import json
from pathlib import Path

from building_model import overlay
from building_model.cli import main
from building_model.markup import (
    MarkupResult,
    SheetRow,
    render_index,
    run_markup,
    scale_ratio,
    write_index,
)
from tests.synth import door, gap_item, make_sheet, wall


def _write_set(path: Path) -> Path:
    plan = make_sheet(
        page=1,
        title={"floors": [4, 5], "level_m": 12.0},
        walls=[wall("W0", (0, 0), (6000, 0))],
        doors=[door("D0", (1000, 0), (2000, 0), (1000, 1000), 1000)],
        openings=[gap_item("H0", (9000, 9000), (9800, 9000))],
    )
    section = make_sheet(page=2, kind={"kind": "section"})
    other = make_sheet(page=3, title={"floors": [6], "level_m": 15.3})
    path.write_text(json.dumps({"sheets": [plan, section, other], "buildings": []}))
    return path


def test_scale_ratio() -> None:
    assert scale_ratio(35.2778) == 100
    assert scale_ratio(None) is None
    assert scale_ratio(0.0) is None


def test_old_overlay_colors_keep_their_meaning() -> None:
    assert overlay.BLUE == (30, 70, 220)
    assert overlay.ORANGE == (255, 140, 0)
    assert overlay.RED == (220, 30, 30)
    assert overlay.GREEN == (20, 160, 60)
    legend = {name: color for name, color, _ in overlay.LEGEND}
    assert legend["синий"] == overlay.BLUE
    assert legend["оранжевый"] == overlay.ORANGE
    assert legend["красный"] == overlay.RED
    assert legend["зелёный"] == overlay.GREEN
    assert overlay.PURPLE not in (overlay.BLUE, overlay.ORANGE, overlay.RED, overlay.GREEN)


def test_markup_without_pdf_builds_models_and_page_without_pictures(tmp_path: Path) -> None:
    source = _write_set(tmp_path / "set.json")
    out = tmp_path / "out"
    result = run_markup(source, None, out)
    assert [r.page for r in result.rows] == [1, 3]
    assert result.excluded == {"kind:section": 1}
    assert (result.models_built, result.models_reused, result.images) == (2, 0, 0)
    assert (out / "model_1.json").is_file() and (out / "model_3.json").is_file()
    row = result.rows[0]
    assert (row.walls, row.openings, row.openings_no_host) == (1, 2, 1)
    assert row.floors == [4, 5]
    assert row.ratio == 99
    assert row.blockers == 1 and row.image is None
    again = run_markup(source, None, out)
    assert (again.models_built, again.models_reused) == (0, 2)


def test_page_contains_table_legend_command_and_no_external_resources(tmp_path: Path) -> None:
    source = _write_set(tmp_path / "set.json")
    out = tmp_path / "out"
    assert main(["markup", "--input", str(source), "--out-dir", str(out), "--pages", "1"]) == 0
    text = (out / "index.html").read_text(encoding="utf-8")
    assert '<meta name="viewport"' in text
    assert "prefers-color-scheme:dark" in text
    assert 'class="scroll"' in text and "overflow:auto" in text
    for needle in ("пурпурный", "бирюзовая", "approve", "--page 1", "ФИО подтверждающего"):
        assert needle in text
    assert "<script" not in text
    assert "http://" not in text and "https://" not in text
    assert "href=" not in text
    assert "без PDF картинки нет" in text


def _row(**changes: object) -> SheetRow:
    base = SheetRow(
        page=1, floors=[2], ratio=100, scale_method="axes", scale_confident=True,
        verdict="accepted", walls=1, openings=2, openings_no_host=1, blockers=0, warnings=3,
        model_file="model_1.json", image="overlay_1.png", note=None, approve_command="cmd",
    )  # fmt: skip
    return base.__class__(**{**base.__dict__, **changes})


def test_strings_are_escaped() -> None:
    evil = '<script>alert("x")</script>&'
    row = _row(
        scale_method=evil, verdict=evil, note=evil, image=None, approve_command=evil, floors=[]
    )
    page = render_index(MarkupResult([row], {evil: 1}, 1, 0, 0), title=evil)
    assert "<script" not in page
    assert "&lt;script&gt;" in page
    assert "&amp;" in page


def test_image_link_and_blocker_marker() -> None:
    page = render_index(MarkupResult([_row(blockers=2)], {}, 1, 0, 1))
    assert '<a href="overlay_1.png">PNG</a>' in page
    assert 'class="num bad"' in page


def test_markup_noisy_sheet_gets_note_and_accept_flag(tmp_path: Path) -> None:
    openings = [
        gap_item(f"H{i}", (9000 + 1000 * i, 9000), (9800 + 1000 * i, 9000)) for i in range(100)
    ]
    quiet = make_sheet(page=1, walls=[wall("W0", (0, 0), (6000, 0))])
    noisy = make_sheet(page=2, walls=[wall("W0", (0, 0), (6000, 0))], openings=openings)
    source = tmp_path / "set.json"
    source.write_text(json.dumps({"sheets": [quiet, noisy], "buildings": []}))
    result = run_markup(source, None, tmp_path / "out")
    write_index(result, tmp_path / "out")
    rows = {r.page: r for r in result.rows}
    assert not rows[1].noisy and "--accept-noise" not in rows[1].approve_command
    assert rows[2].noisy and rows[2].approve_command.endswith("--accept-noise")
    text = (tmp_path / "out" / "index.html").read_text(encoding="utf-8")
    assert text.count("шумный лист: сначала проверьте") == 1
    assert text.count("--accept-noise") == 1
