"""Легенда листа: материал стен из текстового слоя PDF (синтетические страницы)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import pymupdf
import pytest
from shapely.geometry import box

from cad_walls.constructions import Construction
from cad_walls.errors import WallsError
from cad_walls.legend import (
    Evidence,
    Legend,
    LegendEntry,
    LegendLine,
    material_hints,
    parse_legend,
    read_legend,
)
from tests import synth

PAGE_W, PAGE_H = 800.0, 600.0
HEADING = "Условные обозначения:"
Item = tuple[float, float, str, float | None]  # x, y, текст, ширина переноса


class _Writer(Protocol):
    def append(
        self, pos: tuple[float, float], text: str, /, *, font: object, fontsize: int
    ) -> object: ...

    def fill_textbox(
        self, rect: object, text: str, /, *, font: object, fontsize: int
    ) -> object: ...

    def write_text(self, page: object, /) -> None: ...


class _Page(Protocol):
    rect: object


class _Doc(Protocol):
    def new_page(self, *, width: float, height: float) -> _Page: ...

    def save(self, path: str, /) -> None: ...

    def close(self) -> None: ...


# Аннотации PyMuPDF неполны: типизированная граница для сборки синтетической страницы.
_new_doc = cast(Callable[[], _Doc], pymupdf.open)
_new_writer = cast(Callable[[object], _Writer], pymupdf.TextWriter)
_new_rect = cast(Callable[[float, float, float, float], object], pymupdf.Rect)


def make_page(path: Path, items: list[Item]) -> Path:
    """PDF с одной страницей: строки в заданных точках, при ширине — с переносом внутри блока."""
    doc = _new_doc()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    for x, y, text, width in items:
        tw = _new_writer(page.rect)
        if width is None:
            tw.append((x, y), text, font=synth.FONT, fontsize=9)
        else:
            rect = _new_rect(x, y, x + width, y + 60)
            tw.fill_textbox(rect, text, font=synth.FONT, fontsize=9)
        tw.write_text(page)
    doc.save(str(path))
    doc.close()
    return path


def legend_items() -> list[Item]:
    return [
        (400, 300, HEADING, None),
        (430, 330, "Перегородки из газобетонных блоков 100 мм", None),
        (430, 350, "Перегородки из пазогребневых плит 80 мм", None),
        (430, 370, "Перегородки из силикатных блоков 120 мм", None),
        (430, 390, "Перегородки из керамического блока 120 мм", None),
        (430, 410, "Кирпичные стены 250 мм", None),
        (430, 440, "Наружные стены из пустотелого кирпича толщиной 380 мм", 170),
        (430, 500, "Монолитные железобетонные конструкции", None),
        (50, 330, "Стены из газобетона 400 мм", None),  # вне колонки легенды
        (50, 360, "размеры кабины 1400х1100х2400 мм", None),
    ]


def test_legend_block(tmp_path: Path) -> None:
    pdf = make_page(tmp_path / "legend.pdf", legend_items())
    legend = read_legend(pdf, 0)
    assert legend.heading_found
    assert {t: e.code for t, e in legend.masonry.items()} == {
        100: "aerated_concrete",
        80: "gypsum_tongue_groove",
        380: "brick_hollow",
    }
    assert sorted(legend.conflicts) == [120]
    assert {e.code for e in legend.conflicts[120]} == {"silicate_block", "ceramic_block"}
    assert 120 not in legend.masonry
    assert legend.monolith is not None
    assert legend.monolith.code == "monolith_concrete"
    assert legend.monolith.thickness_mm is None
    assert [u.text for u in legend.unparsed] == ["Кирпичные стены 250 мм"]
    # Строка из двух строк текста склеена, рамка охватывает обе.
    ev = legend.masonry[380].evidence
    assert "кирпича" in ev.text
    assert ev.text.endswith("380 мм")
    assert ev.page_index == 0
    x0, y0, _, y1 = ev.bbox
    assert y1 - y0 > 15
    assert x0 >= 430 - 1


def test_legend_deterministic(tmp_path: Path) -> None:
    pdf = make_page(tmp_path / "legend.pdf", legend_items())
    first, second = read_legend(pdf, 0), read_legend(pdf, 0)
    assert first == second
    assert first.to_json() == second.to_json()


def test_fallback_without_heading(tmp_path: Path) -> None:
    pdf = make_page(
        tmp_path / "plain.pdf",
        [
            (60, 100, "Стёны из ГАЗОБЕТОНА 100 мм", None),
            (60, 130, "Перегородки ПГП 80 мм", None),
            (60, 160, "Блоки газобетонные 200 мм", None),  # нет слов стена/перегородка/кладка
            (60, 190, "Монолитные конструкции", None),  # нет слов стена/перегородка/кладка
        ],
    )
    legend = read_legend(pdf, 0)
    assert not legend.heading_found
    assert {t: e.code for t, e in legend.masonry.items()} == {
        100: "aerated_concrete",
        80: "gypsum_tongue_groove",
    }
    assert legend.monolith is None


def test_brick_qualifiers() -> None:
    lines = [
        LegendLine("Условные обозначения", 0, (100, 100, 200, 110)),
        LegendLine("Кладка из полнотелого кирпича 250 мм", 0, (110, 130, 300, 140)),
        LegendLine("Кладка из щелевого кирпича 380 мм", 0, (110, 150, 300, 160)),
        LegendLine("Кладка из кирпича 120 мм", 0, (110, 170, 300, 180)),
    ]
    legend = parse_legend(lines, PAGE_W, PAGE_H)
    assert {t: e.code for t, e in legend.masonry.items()} == {
        250: "brick_solid",
        380: "brick_hollow",
    }
    assert [u.text for u in legend.unparsed] == ["Кладка из кирпича 120 мм"]


def test_broken_line_other_order() -> None:
    """Толщина в первой строке, материал во второй: строки одного блока склеиваются."""
    lines = [
        LegendLine("Условные обозначения", 0, (100, 100, 200, 110), 1),
        LegendLine("Перегородки 100 мм", 0, (110, 130, 300, 140), 2),
        LegendLine("из газобетонных блоков", 0, (110, 141, 300, 151), 2),
    ]
    legend = parse_legend(lines, PAGE_W, PAGE_H)
    assert list(legend.masonry) == [100]
    assert legend.masonry[100].code == "aerated_concrete"


def test_bad_page(tmp_path: Path) -> None:
    pdf = make_page(tmp_path / "legend.pdf", legend_items())
    with pytest.raises(WallsError):
        read_legend(pdf, 5)


def _entry(code: str, thickness: int | None) -> LegendEntry:
    return LegendEntry(code, thickness, Evidence(f"{code} {thickness}", 0, (0.0, 0.0, 1.0, 1.0)))


def _cons(
    cid: str, kind: str, nominal: float | None, measured: float | None = None
) -> Construction:
    t = measured if measured is not None else (nominal or 0.0)
    return Construction(
        id=cid,
        kind=kind,
        family="monolith" if kind.startswith("monolith") else "masonry",
        polygon=box(0, 0, 3000, t),
        axis=[],
        thickness_measured=t,
        thickness_nominal=nominal,
        length_axis=3000.0,
    )


def _legend() -> Legend:
    return Legend(
        masonry={80: _entry("gypsum_tongue_groove", 80), 100: _entry("aerated_concrete", 100)},
        monolith=_entry("monolith_concrete", None),
        conflicts={120: [_entry("silicate_block", 120), _entry("ceramic_block", 120)]},
    )


def test_hints_statuses() -> None:
    cons = [
        _cons("b", "masonry", 100),
        _cons("a", "masonry", 120),
        _cons("c", "masonry", 150),
        _cons("d", "masonry", None, 83.0),
        _cons("e", "masonry", None, 160.0),
        _cons("f", "monolith_wall", 200),
        _cons("g", "frame_partition", 100),
    ]
    snapshot = [(c.id, c.kind, c.thickness_nominal, c.thickness_measured) for c in cons]
    hints = material_hints(cons, _legend(), 12.0)
    assert list(hints) == ["a", "b", "c", "d", "e", "f"]  # порядок по id, каркасные без подсказки
    assert (hints["b"].status, hints["b"].value) == ("matched", "aerated_concrete")
    assert hints["b"].source == "legend"
    assert (hints["a"].status, hints["a"].value) == ("conflict", None)
    assert {e.text.split()[0] for e in hints["a"].evidence} == {"silicate_block", "ceramic_block"}
    assert (hints["c"].status, hints["c"].value) == ("not_in_legend", None)
    assert (hints["d"].status, hints["d"].value) == ("matched", "gypsum_tongue_groove")
    assert hints["e"].status == "not_in_legend"
    assert (hints["f"].status, hints["f"].value) == ("matched", "monolith_concrete")
    assert snapshot == [(c.id, c.kind, c.thickness_nominal, c.thickness_measured) for c in cons]


def test_hints_no_legend_and_no_monolith() -> None:
    cons = [_cons("a", "masonry", 100), _cons("b", "monolith_column", 400)]
    hints = material_hints(cons, Legend(), 12.0)
    assert {k: h.status for k, h in hints.items()} == {"a": "no_legend", "b": "no_legend"}
    only_masonry = Legend(masonry={100: _entry("aerated_concrete", 100)})
    again = material_hints(cons, only_masonry, 12.0)
    assert again["b"].status == "not_in_legend"
    assert again["b"].value is None


def test_hints_json_deterministic() -> None:
    cons = [_cons("b", "masonry", 100), _cons("a", "masonry", 80)]
    first = {k: h.to_json() for k, h in material_hints(cons, _legend(), 12.0).items()}
    second = {k: h.to_json() for k, h in material_hints(cons[::-1], _legend(), 12.0).items()}
    assert first == second
    assert list(first) == ["a", "b"]
    assert first["a"]["evidence"] == [
        {"text": "gypsum_tongue_groove 80", "page_index": 0, "bbox": [0.0, 0.0, 1.0, 1.0]}
    ]
