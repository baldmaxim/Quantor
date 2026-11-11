"""Реестр стояков cad_risers.v1: разбор и проверка входного файла."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_mep.errors import MepError
from cad_mep.risers import load_risers, parse_risers, registry_json

ROW = {
    "system": "V1",
    "mark": "В1.1.1",
    "dn_mm": 50,
    "role": "own",
    "count": 1,
    "shaft_id": None,
    "source": "ИОС2.1 л.2",
    "note": None,
}


def _doc(*rows: dict[str, object]) -> dict[str, object]:
    return {"schema": "cad_risers.v1", "risers": list(rows)}


def test_valid_registry_roundtrip() -> None:
    row2 = {**ROW, "system": "FS", "mark": "В2.6", "count": 2, "shaft_id": "S12", "dn_mm": None}
    entries = parse_risers(_doc(ROW, row2))
    assert [e.system for e in entries] == ["V1", "FS"]
    assert entries[1].shaft_id == "S12" and entries[1].dn_mm is None
    assert registry_json(entries) == _doc(ROW, row2)
    assert entries[0].label() == "В1.1.1 Ø50"
    assert parse_risers(_doc({**ROW, "role": "transit"}))[0].label() == "В1.1.1 Ø50 транзит"


def test_defaults_and_extra_keys() -> None:
    short = {"system": "T3", "mark": "Т3.1", "role": "own", "extra": 1}
    (entry,) = parse_risers(_doc(short))
    assert entry.count == 1 and entry.dn_mm is None and entry.source is None


def test_empty_list_is_allowed() -> None:
    assert parse_risers(_doc()) == []


@pytest.mark.parametrize(
    "bad",
    [
        {**ROW, "system": "T1"},
        {**ROW, "mark": ""},
        {**ROW, "mark": "x" * 33},
        {**ROW, "dn_mm": 5},
        {**ROW, "dn_mm": 401},
        {**ROW, "dn_mm": True},
        {**ROW, "dn_mm": "50"},
        {**ROW, "role": "both"},
        {**ROW, "count": 0},
        {**ROW, "count": 9},
        {**ROW, "shaft_id": "s12"},
        {**ROW, "shaft_id": "S1"},
        {**ROW, "source": "x" * 201},
        {**ROW, "note": 5},
        "строка",
    ],
)
def test_invalid_row_is_rejected(bad: object) -> None:
    with pytest.raises(MepError) as err:
        parse_risers({"schema": "cad_risers.v1", "risers": [bad]})
    assert err.value.code == "risers_invalid"


def test_invalid_document_is_rejected() -> None:
    docs: list[object] = [
        [],
        {"schema": "cad_risers.v2", "risers": []},
        {"schema": "cad_risers.v1", "risers": {}},
        _doc(*([ROW] * 41)),
    ]
    for doc in docs:
        with pytest.raises(MepError) as err:
            parse_risers(doc)
        assert err.value.code == "risers_invalid"
    assert len(parse_risers(_doc(*([ROW] * 40)))) == 40


def test_load_errors(tmp_path: Path) -> None:
    with pytest.raises(MepError) as err:
        load_risers(tmp_path / "нет.json")
    assert err.value.code == "risers_unreadable"
    broken = tmp_path / "broken.json"
    broken.write_text("{не json", encoding="utf-8")
    with pytest.raises(MepError) as err:
        load_risers(broken)
    assert err.value.code == "risers_invalid"
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_doc(ROW), ensure_ascii=False), encoding="utf-8")
    assert len(load_risers(ok)) == 1
