"""Материал из условных обозначений и каркасные перегородки (ADR-0040): чистые функции без базы."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.cad_worker import walls_handler
from app.cad_worker.handler import CadError
from app.contracts.cad_constructions import (
    CadConstructionProps,
    CadSheetLevelsRead,
    WallsDocument,
)
from app.models import Job
from app.services import cad_constructions as calc
from app.services import cad_walls as cad_walls_service
from tests.test_cad_constructions_calc import construction, document, opening
from tests.test_cad_mep import FOLDER

NO_LEVELS = CadSheetLevelsRead(floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None)

EVIDENCE = {
    "text": "Внутренние стены из газобетонных блоков 100 мм",
    "page_index": 81,
    "bbox": [1.0, 2.0, 3.0, 4.0],
}


def hinted(status: str, value: str | None, key: str = "c1") -> dict[str, Any]:
    item = construction(key)
    item["material_hint"] = {
        "value": value,
        "source": "legend",
        "status": status,
        "evidence": [EVIDENCE] if status == "matched" else [],
    }
    return item


def run(doc: WallsDocument, props: CadConstructionProps | None = None) -> calc.SheetResult:
    entries = {} if props is None else {c.id: (props, False) for c in doc.constructions}
    return calc.compute_sheet(doc, entries, NO_LEVELS)


def test_old_walls_json_without_new_fields_works() -> None:
    doc = document([construction()])
    assert doc.frame_partitions == []
    result = run(doc)
    item = result.constructions[0]
    assert item.material.value is None and item.material.source is None
    assert item.material.hint_status is None and item.material.evidence == []
    assert "material_check" not in item.computed.warnings
    assert item.computed.status == "ok"


def test_matched_hint_gives_document_material_without_touching_props() -> None:
    result = run(document([hinted("matched", "aerated_concrete")]))
    item = result.constructions[0]
    assert item.material.value == "aerated_concrete"
    assert item.material.source == "document"
    assert item.material.hint_status == "matched"
    assert item.material.evidence[0].text == EVIDENCE["text"]
    assert item.props.material is None
    assert "material_check" not in item.computed.warnings
    assert result.totals[0].material == "aerated_concrete"


def test_props_override_hint_as_manual() -> None:
    props = CadConstructionProps(material="brick_solid")
    result = run(document([hinted("matched", "aerated_concrete")]), props)
    item = result.constructions[0]
    assert item.material.value == "brick_solid" and item.material.source == "manual"
    assert result.totals[0].material == "brick_solid"


@pytest.mark.parametrize("status", ["conflict", "not_in_legend"])
def test_unmatched_hint_gives_material_check_without_status_change(status: str) -> None:
    item = run(document([hinted(status, None)])).constructions[0]
    assert item.material.value is None and item.material.source is None
    assert item.material.hint_status == status
    assert "material_check" in item.computed.warnings
    assert item.computed.status == "ok"


def test_no_legend_has_no_material_check() -> None:
    item = run(document([hinted("no_legend", None)])).constructions[0]
    assert "material_check" not in item.computed.warnings


def test_manual_material_removes_material_check() -> None:
    props = CadConstructionProps(material="other")
    item = run(document([hinted("conflict", None)]), props).constructions[0]
    assert "material_check" not in item.computed.warnings


def test_totals_group_by_effective_material() -> None:
    doc = document(
        [
            hinted("matched", "aerated_concrete", "a"),
            hinted("matched", "aerated_concrete", "b"),
            hinted("conflict", None, "c"),
        ]
    )
    result = run(doc)
    by_material = {t.material: t.count for t in result.totals}
    assert by_material == {"aerated_concrete": 2, None: 1}


def test_frame_partition_area_without_volume_in_own_group() -> None:
    partition = construction("p1", kind="frame_partition", nominal=100.0, axis=4000.0)
    doc = document([construction("c1")])
    doc = WallsDocument.model_validate(
        {**doc.model_dump(by_alias=True), "frame_partitions": [partition]}
    )
    result = run(doc)
    assert [c.id for c in result.constructions] == ["c1", "p1"]
    computed = result.constructions[1].computed
    # H = 3000 - 200 = 2800; длина 4 м -> 11,2 м2
    assert computed.length_m == pytest.approx(4.0)
    assert computed.wall_area_m2 == pytest.approx(11.2)
    assert computed.volume_m3 is None
    group = next(t for t in result.totals if t.kind == "frame_partition")
    assert group.count == 1 and group.volume_m3 is None
    assert group.wall_area_m2 == pytest.approx(11.2)
    assert result.summary.total_count == 2
    masonry = next(t for t in result.totals if t.kind == "masonry")
    assert masonry.volume_m3 is not None


def test_frame_partition_door_host_counted() -> None:
    partition = construction("p1", kind="frame_partition", nominal=100.0, axis=4000.0)
    doc = WallsDocument.model_validate(
        {
            **document([], [opening("o1", "p1")]).model_dump(by_alias=True),
            "frame_partitions": [partition],
        }
    )
    result = run(doc)
    # надпроёмная часть: 1000 x (2800 - 2100) мм = 0,7 м2
    assert result.constructions[0].computed.wall_area_m2 == pytest.approx(11.2 + 0.7)
    assert result.summary.door_openings_without_host == 0


def test_hint_evidence_text_limit() -> None:
    item = hinted("matched", "aerated_concrete")
    item["material_hint"]["evidence"][0]["text"] = "x" * 201
    with pytest.raises(ValidationError):
        document([item])


def _walls_file(tmp_path: Path, partition_id: str) -> tuple[Path, str]:
    doc = document([construction("c1")]).model_dump(by_alias=True)
    doc["frame_partitions"] = [construction(partition_id, kind="frame_partition")]
    out = tmp_path / "out"
    name = f"{FOLDER}/{cad_walls_service.WALLS_JSON}"
    (out / name).parent.mkdir(parents=True)
    (out / name).write_text(json.dumps(doc), encoding="utf-8")
    return out, name


def _verify(out: Path) -> tuple[list[dict[str, Any]], WallsDocument]:
    params = cad_walls_service.WallsParams(
        path=out / "params.json",
        sha256="0" * 64,
        generator_version="cad_walls.v1",
        params_version="v1",
    )
    job = Job(payload={"view_dxf_sha256": "1" * 64})
    source = walls_handler._Input(Job(payload={}), FOLDER, 0, 0)
    return walls_handler._verified_output(out, source, job, params, "1" * 64)


def test_handler_rejects_duplicate_id_between_arrays(tmp_path: Path) -> None:
    out, _name = _walls_file(tmp_path, "c1")
    with pytest.raises(CadError):
        _verify(out)


def test_handler_accepts_unique_ids_across_arrays(tmp_path: Path) -> None:
    out, _name = _walls_file(tmp_path, "p1")
    _files, parsed = _verify(out)
    assert [c.id for c in parsed.frame_partitions] == ["p1"]
