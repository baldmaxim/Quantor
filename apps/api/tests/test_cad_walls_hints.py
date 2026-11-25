"""Перестроение конструкций по замечаниям: перевод рамки, подсказки, версия, аргументы скрипта."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.cad_worker import walls_handler
from app.core.config import Settings
from app.errors import DomainError, ErrorCode
from app.models import CadRemark
from app.services import cad_walls


def _pt_from_mm(x: float, y: float, frame: tuple[float, float, float]) -> tuple[float, float]:
    """Кадр движка вперёд: `pt = origin + (x_mm, -y_mm) / k` (как у отрисовки проверки)."""
    ox, oy, k = frame
    return ox + x / k, oy - y / k


def test_bbox_pt_to_view_mm_round_trip() -> None:
    frame = (120.5, 700.25, 2.5)
    x0, y0, x1, y1 = 1000.0, 2000.0, 3500.0, 2600.0
    ax, ay = _pt_from_mm(x0, y0, frame)
    bx, by = _pt_from_mm(x1, y1, frame)
    # В пт верх-лево: большему Y мм соответствует меньший Y пт.
    result = walls_handler.bbox_pt_to_view_mm((ax, by, bx, ay), frame)
    assert result == pytest.approx((x0, y0, x1, y1))
    assert result[0] < result[2] and result[1] < result[3]


def test_bbox_pt_to_view_mm_flips_y_and_normalizes() -> None:
    result = walls_handler.bbox_pt_to_view_mm((10, 20, 30, 50), (0.0, 100.0, 2.0))
    assert result == (20.0, 100.0, 60.0, 160.0)
    swapped = walls_handler.bbox_pt_to_view_mm((30, 50, 10, 20), (0.0, 100.0, 2.0))
    assert swapped == result
    assert all(math.isfinite(v) for v in result)


def _remark(key: str, kind: str, status: str = "open") -> CadRemark:
    now = datetime.now(UTC)
    return CadRemark(
        remark_key=key,
        type=kind,
        comment=f"к {key}",
        status=status,
        bbox_x0=10.0,
        bbox_y0=20.0,
        bbox_x1=30.0,
        bbox_y1=50.0,
        created_at=now,
        updated_at=now,
    )


def test_hints_from_remarks_filters_type_and_status() -> None:
    remarks = [
        _remark("b", "missing_door"),
        _remark("a", "missing_wall"),
        _remark("c", "false_wall"),
        _remark("d", "monolith"),
        _remark("e", "missing_wall", status="resolved"),
    ]
    hints = cad_walls.hints_from_remarks(remarks)
    assert [h["id"] for h in hints] == ["a", "b", "c"]
    assert hints[0] == {
        "id": "a",
        "type": "missing_wall",
        "bbox_pt": [10.0, 20.0, 30.0, 50.0],
        "construction_ids": [],
        "comment": "к a",
    }
    assert cad_walls.hints_from_remarks([_remark("d", "monolith")]) == []


def test_hints_sha256_and_idempotency_key() -> None:
    hints = cad_walls.hints_from_remarks([_remark("a", "missing_wall")])
    assert cad_walls.hints_sha256(None) == "" == cad_walls.hints_sha256([])
    assert len(cad_walls.hints_sha256(hints)) == 64
    changed = [{**hints[0], "comment": "другое"}]
    assert cad_walls.hints_sha256(changed) != cad_walls.hints_sha256(hints)

    import uuid

    parent = uuid.uuid4()
    kwargs = {
        "parent_attempt": 1,
        "page_index": 2,
        "view": 0,
        "params_sha256": "p",
        "generator_version": "cad_walls.v1.26",
        "sequence": 0,
    }
    plain = cad_walls.idempotency_key(parent, **kwargs)
    assert plain == cad_walls.idempotency_key(parent, hints_sha256="", **kwargs)
    with_hints = cad_walls.idempotency_key(
        parent, hints_sha256=cad_walls.hints_sha256(hints), **kwargs
    )
    assert with_hints != plain


@pytest.mark.parametrize(
    ("version", "supported"),
    [
        ("cad_walls.v1.25", False),
        ("cad_walls.v1.26", True),
        ("cad_walls.v1.27", True),
        ("cad_walls.v2", True),
        ("garbage", False),
    ],
)
def test_ensure_hints_supported(version: str, supported: bool) -> None:
    if supported:
        cad_walls.ensure_hints_supported(version)
        return
    with pytest.raises(DomainError) as caught:
        cad_walls.ensure_hints_supported(version)
    assert caught.value.code is ErrorCode.CAD_ENGINE_UNAVAILABLE
    assert caught.value.detail == "Движок не поддерживает перестроение по замечаниям"


def test_hints_document_translates_frame() -> None:
    payload = {
        "view_frame": [0.0, 100.0, 2.0],
        "hints": [
            {
                "id": "r1",
                "type": "missing_wall",
                "bbox_pt": [10, 20, 30, 50],
                "construction_ids": [],
                "comment": "стена",
            }
        ],
    }
    document = walls_handler._hints_document(payload)
    assert document is not None
    assert document["schema"] == "quantor.cad_walls_hints.v1"
    assert document["hints"][0]["bbox_mm"] == [20.0, 100.0, 60.0, 160.0]
    assert walls_handler._hints_document({"view_frame": [0, 1, 2]}) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"hints": [{"id": "a", "type": "missing_wall", "bbox_pt": [1, 2, 3, 4]}]},
        {"view_frame": [0, 100, 2], "hints": "x"},
        {"view_frame": [0, 100, 2], "hints": [{"id": "a", "type": "t", "bbox_pt": [1, 2]}]},
    ],
)
def test_hints_document_rejects_bad_input(payload: dict[str, object]) -> None:
    with pytest.raises(walls_handler.CadError):
        walls_handler._hints_document(payload)


def test_argv_passes_hints(tmp_path: Path) -> None:
    python = tmp_path / "python"
    runner = tmp_path / "run_walls.py"
    python.write_text("")
    runner.write_text("")
    settings = Settings(cad_engine_python=str(python), cad_walls_runner=str(runner))
    hints = tmp_path / "hints.json"
    hints.write_text(json.dumps({}))
    common = {
        "dxf": tmp_path / "a.dxf",
        "params": tmp_path / "v1.json",
        "out": tmp_path / "walls.json",
        "pdf": tmp_path / "s.pdf",
        "page_index": 0,
    }
    argv = walls_handler._argv(settings, hints=hints, **common)
    assert argv[-2:] == ["--hints", str(hints)]
    assert "--hints" not in walls_handler._argv(settings, **common)
