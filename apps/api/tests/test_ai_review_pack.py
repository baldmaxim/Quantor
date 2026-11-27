"""Пакет входа ИИ-правщика/проверщика: сводка, тайлы, белый список REMOTE, причина отказа Claude."""

import io
import json
import random
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest

from app.cad_worker import ai_review, ai_review_cli, ai_review_pack
from app.cad_worker.ai_review_pack import (
    SUMMARY_LIMIT_BYTES,
    TileMap,
    build_walls_summary,
    dump_summary,
    grid_positions,
    grid_step,
    plan_tiles,
    tile_zoom,
)

FRAME = (100.0, 700.0, 35.0)
ZOOM = 1.4
PIX_X, PIX_Y = 411, 119


def _rect(x: float, y: float, w: float, h: float) -> dict[str, Any]:
    ring = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return {"shell": ring, "holes": []}


def _walls(constructions: int, openings: int, warnings: int = 3, layers: int = 1) -> dict[str, Any]:
    rng = random.Random(7)  # noqa: S311
    rows = []
    for index in range(constructions):
        x, y = rng.uniform(0, 50000), rng.uniform(0, 30000)
        length = rng.uniform(100, 9000)
        rows.append(
            {
                "id": f"c{index:011d}",
                "kind": rng.choice(["masonry", "monolith_wall"]),
                "source_layers": [f"01_КЛАДКА_ТОЛЩИНА_НЕ_ОПРЕДЕЛЕНА_{index % layers}"],
                "polygon": _rect(x, y, length, 200),
                "thickness_nominal_mm": None if index % 9 == 0 else 200.0,
                "thickness_measured_mm": 198.4,
                "length_axis_mm": length,
                "bbox": [x, y, x + length, y + 200],
            }
        )
    gaps = [
        {
            "id": f"o{index:011d}",
            "kind": "gap",
            "status": "no_data",
            "width_mm": 900.0 + index,
            "thickness_mm": 200.0,
            "center": [1000.0 + index, 2000.0],
            "lintel": [[0, 0], [900, 0], [900, 200], [0, 200]],
        }
        for index in range(openings)
    ]
    return {
        "generator": "cad_walls.v1.26",
        "constructions": rows,
        "frame_partitions": [],
        "openings": gaps,
        "totals": [
            {"kind": "masonry", "thickness_nominal_mm": 80.0, "count": 2, "length_axis_mm": 5.0}
        ],
        "slab": {"basis": "walls_only", "needs_review": True, "area_mm2": 4.4e8},
        "slab_holes": [],
        "checks": {
            "residue_ratio": 0.0,
            "warnings": [
                {"code": f"w{index}", "message": "сообщение диагностики " * 40}
                for index in range(warnings)
            ],
        },
    }


def _summary(walls: dict[str, Any]) -> dict[str, Any]:
    return build_walls_summary(
        walls,
        frame=FRAME,
        zoom=ZOOM,
        pix_x=PIX_X,
        pix_y=PIX_Y,
        width_px=2001,
        height_px=1093,
        view_zone=[411.7, 119.0, 1829.7, 893.6],
    )


def test_summary_small_sheet_is_complete_and_bbox_matches_overlay_transform() -> None:
    walls = _walls(5, 2)
    summary = _summary(walls)
    text = dump_summary(summary)

    assert len(text.encode()) <= SUMMARY_LIMIT_BYTES
    assert "truncated" not in summary
    assert json.loads(text)["schema"] == ai_review_pack.SUMMARY_SCHEMA
    row = next(r for r in summary["constructions"] if r["id"] == walls["constructions"][1]["id"])
    x0, y0, x1, y1 = walls["constructions"][1]["bbox"]
    # Те же формулы, что у overlay.png: Y перевёрнут, начало пиксмапа вычитается.
    expected = [
        round((FRAME[0] + x0 / FRAME[2]) * ZOOM - PIX_X),
        round((FRAME[1] - y1 / FRAME[2]) * ZOOM - PIX_Y),
        round((FRAME[0] + x1 / FRAME[2]) * ZOOM - PIX_X),
        round((FRAME[1] - y0 / FRAME[2]) * ZOOM - PIX_Y),
    ]
    assert row["bbox_px"] == expected
    assert summary["scale"]["mm_per_pt"] == 35.0
    # Отсутствующий номинал - null, не 0.
    assert any(
        r["thickness_mm"] is None and "thickness_measured_mm" in r for r in summary["constructions"]
    )


def test_summary_is_one_record_per_line() -> None:
    text = dump_summary(_summary(_walls(5, 2)))
    lines = text.splitlines()
    assert lines[0] == "{" and lines[-1] == "}"
    ids = [line for line in lines if line.startswith('{"id"')]
    assert len(ids) == 7  # 5 конструкций и 2 проёма, по одной записи на строку


def test_summary_huge_sheet_truncates_to_limit_dropping_short_constructions_first() -> None:
    walls = _walls(4000, 900, warnings=60)
    summary = _summary(walls)
    text = dump_summary(summary)

    assert len(text.encode("utf-8")) <= SUMMARY_LIMIT_BYTES
    json.loads(text)
    kept, total = (int(v) for v in summary["truncated"]["constructions"].split("/"))
    assert total == 4000 and 0 < kept < total
    longest = sorted((r["length_axis_mm"] for r in walls["constructions"]), reverse=True)
    lengths = [r["length_mm"] for r in summary["constructions"]]
    assert lengths == sorted(lengths, reverse=True)
    assert lengths[-1] >= round(longest[kept - 1]) - 1
    assert summary["counts"]["constructions"] == 4000


def test_summary_lines_stay_short_even_with_many_warnings_holes_and_layers() -> None:
    walls = _walls(300, 40, warnings=40, layers=80)
    walls["slab_holes"] = [
        {"id": f"h{i}", "shell": _rect(i * 100, 0, 50, 50)["shell"], "area_mm2": 1.0}
        for i in range(30)
    ]
    walls["totals"] = [
        {"kind": "masonry", "thickness_nominal_mm": 10.0 * i, "count": 1, "length_axis_mm": 1.0}
        for i in range(60)
    ]
    text = dump_summary(_summary(walls))

    assert len(text.encode()) <= SUMMARY_LIMIT_BYTES
    assert max(len(line) for line in text.splitlines()) < 700
    assert json.loads(text)["diagnostics"]["warnings"]
    assert len(text.splitlines()) > 100  # warnings, holes и слои - по строке на запись


def test_summary_fails_loudly_when_fixed_part_cannot_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_review_pack, "_SUMMARY_TARGET_BYTES", 100)
    with pytest.raises(ValueError, match="не помещается"):
        _summary(_walls(1, 1))


def test_summary_without_constructions_still_within_limit() -> None:
    summary = _summary(_walls(0, 0, warnings=500))
    assert len(dump_summary(summary).encode()) <= SUMMARY_LIMIT_BYTES


def test_tile_point_round_trip_and_overlap() -> None:
    tiles = plan_tiles(2001, 1093)
    assert [(t.row, t.col) for t in tiles] == [(r, c) for r in range(2) for c in range(3)]
    assert tiles[0].bbox_px[0] == 0 and tiles[-1].bbox_px[2:] == (2001.0, 1093.0)
    assert tiles[1].bbox_px[0] < tiles[0].bbox_px[2]  # перекрытие соседей
    zoom = tile_zoom(tiles, ZOOM)
    assert 2.0 < zoom / ZOOM < 3.5

    tile = TileMap(zoom, 1037, 301, 1800, 1500, ZOOM, PIX_X, PIX_Y)
    for point in ((0.0, 0.0), (700.5, 313.25), (1799.0, 1499.0)):
        back = tile.to_plan_px(*tile.from_plan_px(*point))
        assert back == pytest.approx(point, abs=1e-6)
    u, v = tile.from_plan_px(*tile.to_plan_px(123.0, 456.0))
    assert (u, v) == pytest.approx((123.0, 456.0), abs=1e-6)
    # Пиксель тайла и пиксель plan.png указывают на одну точку страницы (pt).
    x, y = tile.to_plan_px(10.0, 20.0)
    assert (PIX_X + x) / ZOOM == pytest.approx((tile.pix_x + 10.0) / zoom)
    assert (PIX_Y + y) / ZOOM == pytest.approx((tile.pix_y + 20.0) / zoom)
    bbox_pt = tile.bbox_pt()
    assert bbox_pt[0] == pytest.approx((PIX_X + tile.bbox_plan_px()[0]) / ZOOM)


@pytest.mark.parametrize("span", [180, 400, 733, 1093, 2001, 5000])
def test_grid_has_five_to_eight_lines(span: int) -> None:
    step = grid_step(span)
    lines = grid_positions(1000, 1000 + span, step)
    assert 3 <= len(lines) <= 8
    if span >= 400:
        assert len(lines) >= 5 - 1  # допуск на привязку к кратным шагу


def test_tiles_rendered_from_pdf_with_labels(tmp_path: Path) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("PIL")
    with pymupdf.open() as document:
        page = document.new_page(width=800, height=500)
        page.draw_rect(pymupdf.Rect(100, 100, 400, 300), color=(0, 0, 0))
        document.save(tmp_path / "source.pdf")
    walls = _walls(3, 1)
    for row in walls["constructions"]:
        row["polygon"] = _rect(5000, 5000, 3000, 200)
    zoom = 2000 / 800
    description = ai_review_pack.render_tiles(
        tmp_path,
        walls,
        frame=(0.0, 500.0, 35.0),
        plan_zoom=zoom,
        plan_pix_x=0,
        plan_pix_y=0,
        plan_width=2000,
        plan_height=1250,
    )
    assert len(description["tiles"]) == 6
    total = 0
    for tile in description["tiles"]:
        for name in (tile["pdf"], tile["overlay"]):
            total += (tmp_path / name).stat().st_size
        assert max(tile["size_px"]) <= 1900
    assert total <= ai_review_pack.TILES_TOTAL_LIMIT_BYTES
    assert json.loads((tmp_path / "tiles.json").read_text())["tiles"][0]["id"] == "r0c0"


# --- блок промта -----------------------------------------------------------------------------


def test_pack_prompt_block_is_short_and_templates_stay_below_gate_limit() -> None:
    from app.services.ai_prompts import FULL_CONTEXT_PROMPT_TEMPLATES

    block = ai_review.PACK_PROMPT_BLOCK
    assert len(block.strip().splitlines()) <= 25
    assert "walls_summary.json" in block and "tiles.json" in block and "bbox_px" in block
    for role in ("corrector", "verifier"):
        text = FULL_CONTEXT_PROMPT_TEMPLATES[role]
        assert len((text + block).encode()) < 65536  # предел шлюза kg_claude


# --- REMOTE ----------------------------------------------------------------------------------


def _bundle(extra: dict[str, bytes], source: Path, omit: str | None = None) -> bytes:
    manifest = {"model": "m1", "sources": {"src": str(source)}}
    files: dict[str, bytes] = {
        "manifest.json": json.dumps(manifest).encode(),
        "walls.json": b"{}",
        "project_context.json": b"{}",
        "source.pdf": b"%PDF",
        "plan.png": b"png",
        "overlay.png": b"png",
        "slab_overlay.png": b"png",
        "prompt.txt": b"prompt",
        "schema.json": b"{}",
        "render.json": b"{}",
        "walls_summary.json": b"{}",
        "tiles.json": b"{}",
        **extra,
    }
    if omit is not None:
        del files[omit]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _run_remote(
    tmp_path: Path, package: bytes, claude_script: str
) -> subprocess.CompletedProcess[bytes]:
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    claude = home / ".local/bin/claude"
    claude.write_text("#!/bin/sh\ncat >/dev/null\n" + claude_script, encoding="utf-8")
    claude.chmod(0o755)
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", ai_review_cli.REMOTE, "30"],
        input=package,
        capture_output=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path)},
        check=False,
    )


_OK = """printf '%s' '{"structured_output":{"findings":[]},"usage":{}}'\n"""


def test_remote_accepts_tiles_by_strict_pattern(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("источник", encoding="utf-8")
    package = _bundle({"tiles/r0c0_pdf.png": b"x", "tiles/r12c3_overlay.png": b"y"}, source)

    result = _run_remote(tmp_path, package, _OK)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["report"] == {"findings": []}


@pytest.mark.parametrize(
    "name",
    [
        "tiles/../x.png",
        "tiles/a.png",
        "tiles/r0c0_pdf.png.bak",
        "tiles/r0c0_other.png",
        "tiles//r0c0_pdf.png",
        "/tiles/r0c0_pdf.png",
        "tiles/sub/r0c0_pdf.png",
        "tiles/r0c0_pdf.png\n",
    ],
)
def test_remote_rejects_foreign_tile_names(tmp_path: Path, name: str) -> None:
    source = tmp_path / "src.md"
    source.write_text("источник", encoding="utf-8")

    result = _run_remote(tmp_path, _bundle({name: b"x"}, source), _OK)

    assert result.returncode != 0
    assert b"Invalid review package" in result.stderr
    assert not (tmp_path.parent / "x.png").exists()


def test_remote_requires_summary_and_tiles_description(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("источник", encoding="utf-8")
    result = _run_remote(tmp_path, _bundle({}, source, omit="tiles.json"), _OK)

    assert result.returncode != 0
    assert b"Incomplete review package" in result.stderr


def test_remote_prints_failure_tail_when_claude_reports_error(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("источник", encoding="utf-8")
    error = (
        '{"is_error":true,"subtype":"error_max_turns","num_turns":7,"duration_ms":1234,'
        '"result":"' + "x" * 900 + '"}'
    )

    result = _run_remote(tmp_path, _bundle({}, source), f"printf '%s' '{error}'\n")

    assert result.returncode == 3
    tail = ai_review.failure_tail(result.stderr)
    assert "subtype=error_max_turns" in tail and "num_turns=7" in tail
    assert len(tail) <= 600
    line = json.loads(result.stderr.decode().strip().splitlines()[-1])
    assert len(line["result"]) == 500


def test_remote_prints_failure_tail_when_claude_exits_nonzero(tmp_path: Path) -> None:
    source = tmp_path / "src.md"
    source.write_text("источник", encoding="utf-8")

    result = _run_remote(tmp_path, _bundle({}, source), "exit 2\n")

    assert result.returncode == 3
    assert "claude exit code 2" in ai_review.failure_tail(result.stderr)


def test_failure_tail_ignores_foreign_output_and_limits_length() -> None:
    noise = b"Warning: Permanently added host\nTraceback (most recent call last):\n"
    assert ai_review.failure_tail(noise) == ""
    assert ai_review.failure_tail(b'{"token":"secret-value"}\n') == ""
    payload = {
        "subtype": "error_during_execution",
        "is_error": True,
        "num_turns": 3,
        "duration_ms": 10,
        "result": "z " * 500,
        "token": "must-not-leak",
    }
    tail = ai_review.failure_tail(noise + json.dumps(payload).encode() + b"\n")
    assert tail.startswith("subtype=error_during_execution; is_error=True; num_turns=3")
    assert len(tail) <= 600
    assert "must-not-leak" not in tail
