import pytest

from building_model.reader import (
    Excluded,
    UnsupportedVersionError,
    document_from_json,
    read_sheet,
)
from tests.synth import OX, OY, axis, build, document, make_sheet, wall


def test_version_gate_refuses_unknown_version() -> None:
    sheet = make_sheet(plangeom_version="0.2.0")
    with pytest.raises(UnsupportedVersionError, match=r"0\.2\.0"):
        document(sheet)


def test_version_gate_refuses_missing_version() -> None:
    sheet = make_sheet()
    del sheet["plangeom_version"]
    with pytest.raises(UnsupportedVersionError):
        document(sheet)


def test_single_sheet_output_of_parse_page_is_accepted() -> None:
    doc = document_from_json(make_sheet(page=4))
    assert doc.pages() == [4]


def test_sheet_with_wrong_kind_or_verdict_is_excluded_with_reason() -> None:
    section = document(make_sheet(kind={"kind": "section"}))
    empty = document(make_sheet(verdict="empty"))
    no_kind = make_sheet()
    del no_kind["kind"]
    missing = document(no_kind)
    for doc, reason in (
        (section, "kind:section"),
        (empty, "verdict:empty"),
        (missing, "kind:missing"),
    ):
        result = read_sheet(doc, 0)
        assert isinstance(result, Excluded)
        assert result.reason == reason


def test_excluded_sheet_is_not_built() -> None:
    with pytest.raises(ValueError, match="kind:section"):
        build(make_sheet(kind={"kind": "section"}))


def test_origin_is_axes_intersection_with_y_up_and_no_rotation() -> None:
    sheet = make_sheet(walls=[wall("W0", (0, 0), (4000, 0)), wall("W1", (0, 500), (4000, 500))])
    model = build(sheet)
    assert model.origin.source == "axes"
    assert model.origin.sheet_mm == (OX, OY)
    assert model.origin.axes == ["1", "A"]
    assert [(w.a, w.b) for w in model.walls] == [
        ((0.0, 0.0), (4000.0, 0.0)),
        ((0.0, 500.0), (4000.0, 500.0)),
    ]


def test_origin_pair_is_the_one_with_most_bubbles() -> None:
    axes = [
        axis("1", (1.0, 0.0), OX, 2),
        axis("2", (1.0, 0.0), OX + 6000, 4),
        axis("A", (0.0, 1.0), OY, 2),
        axis("B", (0.0, 1.0), OY - 5000, 4),
    ]
    model = build(make_sheet(axes=axes))
    assert model.origin.sheet_mm == (OX + 6000, OY - 5000)
    assert model.origin.axes == ["2", "B"]


def test_origin_tie_does_not_depend_on_axes_order() -> None:
    axes = [
        axis("1", (1.0, 0.0), OX, 2),
        axis("2", (1.0, 0.0), OX + 6000, 2),
        axis("A", (0.0, 1.0), OY, 2),
        axis("B", (0.0, 1.0), OY - 5000, 2),
    ]
    forward = build(make_sheet(axes=axes)).origin
    backward = build(make_sheet(axes=list(reversed(axes)))).origin
    assert forward == backward


def test_axes_at_45_degrees_are_not_a_pair() -> None:
    axes = [axis("1", (1.0, 0.0), OX), axis("2", (0.70710678, 0.70710678), 0.0)]
    model = build(make_sheet(axes=axes))
    assert model.origin.source == "sheet_corner"


def test_no_axes_origin_blocker_and_sheet_corner() -> None:
    model = build(make_sheet(axes=[]))
    codes = {i.code for i in model.review.items if i.severity == "blocker"}
    assert "no_axes_origin" in codes
    assert model.origin.axes is None
    assert model.origin.sheet_mm == (0.0, 1400.0 * 35.0)
