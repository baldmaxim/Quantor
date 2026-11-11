"""walls.json: подсказки материала из легенды, блок legend, массив frame_partitions (синтетика)."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Protocol, cast

import pytest
from ezdxf.document import Drawing

from cad_walls.cli import main
from cad_walls.params import load_params
from tests import synth
from tests.test_legend import HEADING, Item, make_page

FRAME_LAYER = "07_C112_КАРКАСНАЯ_ЗОНА_50"
API_ROOT = Path(__file__).resolve().parents[3] / "apps" / "api"
LEGEND_ITEMS: list[Item] = [
    (400, 300, HEADING, None),
    (430, 330, "Перегородки из газобетонных блоков 100 мм", None),
    (430, 360, "Монолитные железобетонные конструкции", None),
]


class _Validator(Protocol):
    def model_validate(self, obj: object, /) -> object: ...


def _doc() -> Drawing:
    doc, msp = synth.new_doc()
    doc.layers.add(FRAME_LAYER)
    synth.add_rect(msp, synth.MASONRY, 0, 0, 3000, 100)  # 100 мм: есть в легенде
    synth.add_rect(msp, synth.MASONRY, 0, 4000, 3000, 4150)  # 150 мм: нет в легенде
    synth.add_rect(msp, synth.MONOLITH, 6000, 0, 6400, 400)
    synth.add_rect(msp, FRAME_LAYER, 0, 8000, 2500, 8100)
    return doc


def _run(tmp_path: Path, with_pdf: bool) -> dict[str, object]:
    if not with_pdf:
        return synth.run(tmp_path, _doc())
    pdf = make_page(tmp_path / "legend.pdf", LEGEND_ITEMS)
    return synth.run(tmp_path, _doc(), pdf, 0)


def _items(doc: dict[str, object], key: str) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], doc[key])


def _hint(item: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], item["material_hint"])


def test_hints_legend_and_frame_partitions(tmp_path: Path) -> None:
    doc = _run(tmp_path, True)
    assert doc["generator"] == "cad_walls.v1.6"
    legend = cast(dict[str, object], doc["legend"])
    assert legend["heading_found"] is True
    assert cast(dict[str, object], legend["masonry"]).keys() == {"100"}
    by_thickness = {c["thickness_nominal_mm"]: c for c in _items(doc, "constructions")}
    masonry100, masonry150 = by_thickness[100], by_thickness[150]
    assert (_hint(masonry100)["status"], _hint(masonry100)["value"]) == (
        "matched",
        "aerated_concrete",
    )
    assert _hint(masonry100)["source"] == "legend"
    assert cast(list[object], _hint(masonry100)["evidence"])
    assert (_hint(masonry150)["status"], _hint(masonry150)["value"]) == ("not_in_legend", None)
    monolith = next(c for c in _items(doc, "constructions") if str(c["kind"]).startswith("mono"))
    assert _hint(monolith)["value"] == "monolith_concrete"
    frames = _items(doc, "frame_partitions")
    assert len(frames) == 1
    assert frames[0]["kind"] == "frame_partition"
    assert frames[0]["thickness_nominal_mm"] == 100
    assert "material_hint" not in frames[0]
    assert all(c["kind"] != "frame_partition" for c in _items(doc, "constructions"))
    ids = [str(c["id"]) for key in ("constructions", "frame_partitions") for c in _items(doc, key)]
    assert len(ids) == len(set(ids))


def test_no_pdf_gives_no_legend_status(tmp_path: Path) -> None:
    doc = _run(tmp_path, False)
    legend = cast(dict[str, object], doc["legend"])
    assert legend["heading_found"] is False and legend["monolith"] is None
    assert legend["masonry"] == {}
    constructions = _items(doc, "constructions")
    assert constructions
    assert {_hint(c)["status"] for c in constructions} == {"no_legend"}
    assert len(_items(doc, "frame_partitions")) == 1


def test_existing_keys_unchanged_by_hints(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_legend, without = _run(tmp_path / "a", True), _run(tmp_path / "b", False)

    def bare(doc: dict[str, object]) -> list[dict[str, object]]:
        return [
            {k: v for k, v in c.items() if k != "material_hint"}
            for c in _items(doc, "constructions")
        ]

    assert bare(with_legend) == bare(without)
    for key in ("openings", "slab", "slab_holes", "totals", "frame_partitions"):
        assert with_legend[key] == without[key]


def test_deterministic_bytes(tmp_path: Path) -> None:
    dxf = tmp_path / "plan.dxf"
    _doc().saveas(str(dxf))
    pdf = make_page(tmp_path / "legend.pdf", LEGEND_ITEMS)
    outs = [tmp_path / "a.json", tmp_path / "b.json"]
    for out in outs:
        args = ["--dxf", str(dxf), "--pdf", str(pdf), "--page", "0", "--out", str(out)]
        assert main(args) == 0
    assert outs[0].read_bytes() == outs[1].read_bytes()
    assert "material_hint" in json.loads(outs[0].read_text(encoding="utf-8"))["constructions"][0]


def test_params_carry_new_keys() -> None:
    p = load_params()
    assert p.num("legend_tolerance_mm") == p.num("tolerance_masonry_mm")
    assert p.texts("frame_partition_layers") == ("07_C112_*",)
    assert p.nums("frame_partition_nominals_mm") == (75, 100, 125, 150, 175, 200)


def test_api_contract_accepts_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not (API_ROOT / "app").is_dir():
        pytest.skip("apps/api не найден рядом с tools/cad_walls")
    monkeypatch.syspath_prepend(str(API_ROOT))
    for name in [n for n in sys.modules if n == "app" or n.startswith("app.")]:
        monkeypatch.delitem(sys.modules, name)
    try:
        module = importlib.import_module("app.contracts.cad_constructions")
    except ImportError as exc:
        pytest.skip(f"контракты API не импортируются в этом окружении: {exc}")
    model = cast(_Validator, module.WallsDocument)
    model.model_validate(_run(tmp_path, True))
