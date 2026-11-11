"""Стояки по реестру ИОС (cad_risers.v1) на синтетическом этаже: вода, пожаротушение, замечания."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from ezdxf.entities.text import Text
from ezdxf.filemanagement import readfile

from tests import synth
from tests.test_generator import FOLDER, _run, checks_topology_ok

JsonObj = dict[str, object]


def _dict(x: object) -> JsonObj:
    assert isinstance(x, dict)
    return x


def _strs(x: object) -> list[str]:
    """Стояки шахты без реестра — слои строками."""
    assert x is None or (isinstance(x, list) and all(isinstance(r, str) for r in x))
    return [str(r) for r in x] if isinstance(x, list) else []


def _list(x: object) -> list[JsonObj]:
    assert isinstance(x, list)
    return [_dict(i) for i in x]


def _row(
    system: str,
    mark: str,
    role: str = "own",
    count: int = 1,
    shaft_id: str | None = None,
    dn_mm: int | None = 50,
) -> JsonObj:
    return {
        "system": system,
        "mark": mark,
        "dn_mm": dn_mm,
        "role": role,
        "count": count,
        "shaft_id": shaft_id,
        "source": "ИОС (тест)",
        "note": None,
    }


FULL = [
    _row("V1", "В1.1.1"),
    _row("T3", "Т3.1.1"),
    _row("T4", "Т4.1.1", dn_mm=40),
    _row("V1", "В1.2.1", "transit"),
    _row("T3", "Т3.2.1", "transit"),
    _row("T4", "Т4.2.1", "transit", dn_mm=40),
    _row("VPV", "В2.1", count=2, dn_mm=65),
    _row("AUP", "В21.1", dn_mm=100),
    _row("FS", "В2.6", count=2, dn_mm=80),
]


class Built:
    def __init__(self, out: Path, reg_path: Path | None) -> None:
        self.dir = out / "views" / FOLDER
        self.reg_path = reg_path
        self.data: JsonObj = json.loads((self.dir / "candidate.json").read_text(encoding="utf-8"))

    def issues(self, code: str) -> list[str]:
        return [str(i["message"]) for i in _list(self.data["issues"]) if i["code"] == code]

    def shafts(self) -> dict[str, JsonObj]:
        return {str(s["id"]): s for s in _list(self.data["shafts"])}

    def apts(self) -> list[JsonObj]:
        return _list(self.data["apartments"])

    def water_shafts(self) -> set[object]:
        return {_dict(a["water"])["shaft"] for a in self.apts()}

    def marks(self, shaft: str) -> list[str]:
        risers = self.shafts()[shaft]["risers"]
        return [str(r["mark"]) for r in _list(risers or []) if r["mark"]]

    def by_layer(self, layer: str) -> dict[str, float]:
        by_layer = _dict(_dict(self.data["routes"])["by_layer"])
        row = _dict(by_layer.get(layer, {"plan_m": 0.0, "polylines": 0}))
        return {k: float(str(v)) for k, v in row.items()}

    def pk_ids(self) -> list[str]:
        return [i for i, s in self.shafts().items() if s["systems"] == ["ПК"]]

    def vk_mop_ids(self) -> list[str]:
        return [
            i for i, s in self.shafts().items() if s["systems"] == ["ВК"] and s["place"] == "mop"
        ]


def _build(
    tmp_path: Path,
    rows: list[JsonObj] | None,
    floor: synth.Floor | None = None,
    params: Path | None = None,
) -> Built:
    files = synth.write_inputs(floor or synth.build_floor(), tmp_path / "in")
    reg: Path | None = None
    if rows is not None:
        reg = tmp_path / "risers.json"
        reg.write_text(
            json.dumps({"schema": "cad_risers.v1", "risers": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
    proc = _run(files, tmp_path / "out", risers=reg, params=params)
    assert proc.returncode == 0, proc.stderr
    return Built(tmp_path / "out", reg)


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Built:
    return _build(tmp_path_factory.mktemp("full"), FULL)


@pytest.fixture(scope="module")
def two_vk(tmp_path_factory: pytest.TempPathFactory) -> Built:
    floor = synth.build_floor(shaft_labels=("ОВ", "ПК", "ВК", "ВК", "ПК", "ВК"))
    return _build(tmp_path_factory.mktemp("two_vk"), FULL, floor)


def test_provenance_and_registry_in_candidate(full: Built) -> None:
    prov = _dict(full.data["provenance"])
    assert full.reg_path is not None
    assert prov["generator_version"] == "cad_mep.v8"
    assert prov["risers_sha256"] == hashlib.sha256(full.reg_path.read_bytes()).hexdigest()
    assert full.data["risers_registry"] == {"schema": "cad_risers.v1", "risers": FULL}
    assert full.issues("risers_registry_missing") == []


def test_water_risers_in_one_shaft_with_marks(full: Built) -> None:
    (vk,) = full.vk_mop_ids()
    assert full.marks(vk) == ["В1.1.1", "Т3.1.1", "Т4.1.1", "В1.2.1", "Т3.2.1", "Т4.2.1"]
    water = [r for r in _list(full.shafts()[vk]["risers"]) if r["mark"]]
    assert [r["role"] for r in water] == ["own"] * 3 + ["transit"] * 3
    assert [r["dn_mm"] for r in water] == [50, 50, 40, 50, 50, 40]
    assert full.water_shafts() == {vk}


def test_transit_has_no_horizontal(tmp_path: Path) -> None:
    """Транзитный В1 — только вертикаль: длина слоя по плану та же, что без него."""
    base = _build(tmp_path / "a", [_row("V1", "В1.1.1"), _row("T3", "Т3.1.1")])
    only_transit = _build(tmp_path / "b", [_row("V1", "В1.2.1", "transit"), _row("T3", "Т3.1.1")])
    assert base.by_layer("M-VK-V1")["plan_m"] > 0
    assert only_transit.by_layer("M-VK-V1") == {"plan_m": 0.0, "len3d_m": 3.3, "polylines": 1}
    assert only_transit.by_layer("M-VK-T3") == base.by_layer("M-VK-T3")


def test_t4_runs_along_corridor_without_dangling_ends(full: Built) -> None:
    t4 = full.by_layer("M-VK-T4")
    assert 0 < t4["plan_m"] < full.by_layer("M-VK-T3")["plan_m"]  # без вводов в квартиры
    last = [a for a in full.apts() if _dict(a["water"])["t4_last_of_branch"]]
    assert len(last) == 2  # по одной на сторону от шахты
    assert checks_topology_ok(full.data)
    topo = _dict(full.data["topology"])
    assert _dict(_dict(topo["layers"])["M-VK-T4"])["dangling"] == 0
    assert _dict(topo["totals"])["same_layer_crossings"] == 0


def test_fire_risers_in_pk_niches(full: Built) -> None:
    pk1, pk2 = sorted(full.pk_ids())
    assert sorted(full.marks(pk1) + full.marks(pk2)) == sorted(
        ["В2.1", "В2.1", "В21.1", "В2.6", "В2.6"]
    )
    for pk in (pk1, pk2):
        assert "В2.1" in full.marks(pk)  # каждый из двух стояков ВПВ — в своей нише
    # горизонталей ВПВ нет: на слое только вертикали стояков (ВПВ и пожарные)
    assert full.by_layer("M-PT-VPV")["plan_m"] == 0.0
    assert full.by_layer("M-PT-VPV")["polylines"] == 4
    assert full.by_layer("M-PT-AUP")["plan_m"] > 0  # магистраль АУП — от стояка АУП
    assert _dict(_dict(full.data["checks"])["aup_coverage"])["passed"]
    fire = _dict(_dict(full.data["routes"])["fire"])
    assert fire["vpv_paths_m"] == [] and fire["source_shaft"] in {pk1, pk2}


def test_auto_and_shared_shaft_notes(full: Built) -> None:
    pk1, pk2 = sorted(full.pk_ids())
    auto = full.issues("riser_auto_shaft")
    assert len(auto) == 2 and all("поставлен в" in m and "автоматически" in m for m in auto)
    assert all("В2.1" in m for m in auto)
    assert {m.split(" поставлен в ")[1].split(" ")[0] for m in auto} == {pk1, pk2}
    shared = full.issues("riser_shaft_shared")  # ниш две: АУП и пожарные стояки — общие
    assert (
        len(shared) == 2 and any("В21.1" in m for m in shared) and any("В2.6" in m for m in shared)
    )
    assert full.issues("riser_shaft_missing") == []


def test_dxf_riser_labels(full: Built) -> None:
    doc = readfile(str(full.dir / "mep_routes.dxf"))
    texts = {e.dxf.text for e in doc.modelspace() if isinstance(e, Text)}
    assert {"В1.1.1 Ø50", "Т4.2.1 Ø40 транзит", "В21.1 Ø100", "В2.6 Ø80"} <= texts
    assert not doc.audit().errors


def test_unused_vk_shaft_is_noted(two_vk: Built) -> None:
    ids = two_vk.vk_mop_ids()
    assert len(ids) == 2
    used = [i for i in ids if two_vk.marks(i)]
    unused = [i for i in ids if not two_vk.marks(i)]
    assert len(used) == 1 and len(unused) == 1
    notes = two_vk.issues("riser_shaft_unused")
    assert len(notes) == 1 and unused[0] in notes[0] and used[0] in notes[0]
    assert two_vk.water_shafts() == set(used)
    assert checks_topology_ok(two_vk.data)


def test_without_registry_stems_follow_shaft_labels(tmp_path: Path) -> None:
    """Без реестра — как v5: стояки по подписям шахт, ВПВ от шахты ВК, справка про реестр."""
    floor = synth.build_floor(shaft_labels=("ОВ", "ПК", "ВК", "ВК", "ПК", "ВК"))
    built = _build(tmp_path, None, floor)
    assert _dict(built.data["provenance"])["risers_sha256"] is None
    assert built.data["risers_registry"] is None
    assert len(built.issues("risers_registry_missing")) == 1
    assert "справка: реестр стояков не задан" in built.issues("risers_registry_missing")[0]
    shafts = built.shafts()
    for s in shafts.values():
        _strs(s["risers"])
    # ВПВ и АУП — на шахте ВК у ПК, а не в нише ПК
    vpv = [sid for sid, s in shafts.items() if "M-PT-VPV" in _strs(s["risers"])]
    assert vpv and all(shafts[sid]["systems"] == ["ВК"] for sid in vpv)
    assert built.issues("riser_shaft_unused") == []


def test_explicit_shaft_id(tmp_path: Path) -> None:
    pk = _build(tmp_path / "probe", FULL).pk_ids()
    last = sorted(pk)[-1]
    rows = [
        _row("V1", "В1.1.1"),
        _row("T3", "Т3.1.1"),
        _row("VPV", "В2.1", shaft_id=last),
        _row("AUP", "В21.1", shaft_id="S99"),  # такой шахты нет — замечание и автоматика
    ]
    built = _build(tmp_path / "run", rows)
    assert "В2.1" in built.marks(last)
    assert built.issues("riser_shaft_invalid") and "S99" in built.issues("riser_shaft_invalid")[0]
    assert len(built.issues("riser_auto_shaft")) == 1  # только АУП; ВПВ задана явно
    assert built.issues("riser_system_absent") == [
        "справка: в реестре стояков нет системы Т4 — её трассы не строятся"
    ]


def test_missing_shafts_are_reported(tmp_path: Path) -> None:
    """Нет ниш ПК и шахты ВК в МОП: стояк не рисуется, замечание riser_shaft_missing."""
    floor = synth.build_floor(shaft_labels=("ОВ", "ОВ", "ОВ", "ОВ", "ОВ", "ВК"))
    built = _build(tmp_path, FULL, floor)
    missing = built.issues("riser_shaft_missing")
    assert len(missing) == len(FULL)
    assert all(not m.startswith("справка") for m in missing)
    assert all(not built.marks(sid) for sid in built.shafts())
    assert built.by_layer("M-VK-V1")["polylines"] == 0
    assert built.by_layer("M-PT-VPV")["polylines"] == 0
