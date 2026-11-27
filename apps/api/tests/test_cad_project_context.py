"""Юнит-тесты проектного контекста CAD (`cad_project_context`) и рендера `slab_overlay.png`."""

from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad import CadFrameRead
from app.contracts.cad_building3d import (
    CadBuilding3dAlignment,
    CadBuilding3dFloorRead,
    CadBuilding3dRead,
)
from app.contracts.cad_constructions import CadSheetLevelsRead
from app.contracts.tender_exchange import (
    ObjectBaseCoordination,
    ObjectBaseCoordinationAxis,
    ObjectBaseCoordinationGroup,
    ObjectBaseCoordinationStorey,
)
from app.models import (
    CadFacadeView,
    CadProjectLevels,
    CadSectionLevel,
    CadZone,
    DocumentRevision,
    Project,
    TenderBaseRelease,
)
from app.services import (
    cad_building3d,
    cad_building3d_assembly,
    cad_project_context,
    cad_project_levels,
    sheet_passports,
    tender_base,
)


def _floor(
    *,
    revision_id: uuid.UUID,
    page_index: int,
    view: int = 1,
    label: str = "2 эт.",
    base_z_mm: int = 6460,
    floor_height_mm: int = 4080,
    alignment: CadBuilding3dAlignment = "reference",
    offset_mm: tuple[float, float] = (0.0, 0.0),
) -> CadBuilding3dFloorRead:
    return CadBuilding3dFloorRead(
        job_id=uuid.uuid4(),
        revision_id=revision_id,
        page_index=page_index,
        view=view,
        document_id=uuid.uuid4(),
        label=label,
        elevation_known=True,
        base_z_mm=base_z_mm,
        floor_height_mm=floor_height_mm,
        floor_height_known=True,
        slab_thickness_mm=200,
        slab_thickness_known=False,
        outline=[[0.0, 0.0], [10000.0, 0.0], [10000.0, 5000.0], [0.0, 5000.0]],
        outline_source="slab",
        bbox=[0.0, 0.0, 10000.0, 5000.0],
        corps="1",
        section="1",
        group_key="c1-s1",
        group_label="Корпус 1 · секция 1",
        offset_mm=offset_mm,
        rotation_deg=0.0,
        alignment=alignment,
        alignment_axes=["1", "А"],
        alignment_message=None,
        kind="floor",
    )


class _FakeSession:
    """Минимальный async-заменитель сессии: выдаёт заданные результаты по порядку вызовов."""

    def __init__(
        self,
        *,
        scalars_seq: list[list[Any]],
        scalar_seq: list[Any],
    ) -> None:
        self._scalars_seq = list(scalars_seq)
        self._scalar_seq = list(scalar_seq)

    async def scalar(self, _query: Any) -> Any:
        return self._scalar_seq.pop(0) if self._scalar_seq else None

    async def scalars(self, _query: Any) -> list[Any]:
        return self._scalars_seq.pop(0) if self._scalars_seq else []


async def test_build_project_context_live_coordination_levels_facades_and_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    rev_id = uuid.uuid4()
    project = Project(id=proj_id, workspace_id=ws_id, name="341. Капельский (тест)")

    f1 = _floor(revision_id=rev_id, page_index=6, label="1 эт.", base_z_mm=0, floor_height_mm=6460)
    f2 = _floor(
        revision_id=rev_id,
        page_index=7,
        label="2 эт.",
        base_z_mm=6460,
        floor_height_mm=4080,
        alignment="axes",
        offset_mm=(100.0, -50.0),
    )
    f3 = _floor(
        revision_id=rev_id,
        page_index=8,
        label="3 эт.",
        base_z_mm=10540,
        floor_height_mm=3300,
        alignment="axes",
    )
    building = CadBuilding3dRead(units="mm", floors=[f1, f2, f3], groups=[], warnings=[])
    monkeypatch.setattr(
        cad_building3d_assembly, "build_building3d", AsyncMock(return_value=building)
    )

    sheet_refs = [
        cad_building3d.SheetRef(
            job_id=f.job_id,
            revision_id=rev_id,
            document_id=f.document_id or uuid.uuid4(),
            page_index=f.page_index,
            view=f.view,
            label=f.label,
            order=(0.0, 0.0, f.page_index, f.view),
            overrides=CadSheetLevelsRead(
                floor_height_mm=None, slab_thickness_mm=None, door_height_mm=None
            ),
            walls_key=f"walls/{f.page_index}.json",
            scale_key=f"scale/{f.page_index}.json",
            checks_key=f"checks/{f.page_index}.json",
        )
        for f in (f1, f2, f3)
    ]
    monkeypatch.setattr(
        cad_building3d, "collect_sheets", AsyncMock(return_value=(sheet_refs, [], None))
    )
    frame = CadFrameRead(
        confirmed=True, reason=None, units="mm", origin_pt=(10.0, 800.0), mm_per_pdf_point=35.277
    )
    axes = cad_building3d.FloorAxes(vertical={"1": 1000.0}, horizontal={"А": 2000.0}, message=None)
    monkeypatch.setattr(
        cad_project_context, "_read_frame_and_axes", AsyncMock(return_value=(frame, axes))
    )
    monkeypatch.setattr(
        cad_project_levels,
        "load_project_levels",
        AsyncMock(
            return_value={
                ("1", 2): cad_project_levels.ProjectLevel(z_mm=6360, ref="КР2 · лист 4"),
            }
        ),
    )
    monkeypatch.setattr(
        sheet_passports,
        "latest_pdf_revisions",
        AsyncMock(return_value=[DocumentRevision(id=rev_id)]),
    )

    sec_row = CadSectionLevel(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        project_id=proj_id,
        job_id=uuid.uuid4(),
        revision_id=rev_id,
        seq=0,
        page_index=25,
        cut="1-1",
        corps="1",
        section="1",
        floor=2,
        elevation_mm=6460,
        upper_elevation_mm=10540,
        clear_height_mm=3760,
        structure_mm=320,
        evidence="Разрез 1-1: +6.460 -> +10.540",
        markup={},
        status="accepted",
        auto_accepted=True,
    )
    facade_row = CadFacadeView(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        project_id=proj_id,
        job_id=uuid.uuid4(),
        revision_id=rev_id,
        seq=0,
        page_index=30,
        view_key="p31v1",
        title="Фасад в осях 1-12",
        axis_from="1",
        axis_to="12",
        corps="1",
        section="1",
        body="vector",
        scale_status="fitted",
        mm_per_pt=35.2,
        residual_mm=4.0,
        bbox=[0.0, 0.0, 1.0, 1.0],
        axes=[{"label": "1", "label_full": "1"}, {"label": "12"}],
        marks=[],
        floors=[],
        windows=[
            {"z_bottom_mm": 7360, "z_top_mm": 9660, "width_mm": 2400},
            {"z_bottom_mm": True, "z_top_mm": float("nan"), "width_mm": float("inf")},
        ],
        window_count=2,
        status="accepted",
    )
    zones = [
        CadZone(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            project_id=proj_id,
            revision_id=rev_id,
            page_index=7,
            kind="room_apartment",
            apartment_no="1",
            room_mark="13",
            name="Терраса",
            points=[[0.1, 0.1], [0.2, 0.1], [0.2, 0.2]],
            source="auto",
            quality_status="ok",
            expl_area_m2=40.4,
            generator_area_m2=40.1,
        ),
        CadZone(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            project_id=proj_id,
            revision_id=rev_id,
            page_index=7,
            kind="door",
            name="Выход на террасу",
            points=[[0.2, 0.1], [0.2, 0.2]],
            door_height_mm=2100,
            source="human",
            quality_status="ok",
        ),
        CadZone(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            project_id=proj_id,
            revision_id=rev_id,
            page_index=7,
            kind="room_mop",
            room_mark="02.3",
            name="Лестничная клетка",
            points=[[0.3, 0.3], [0.4, 0.3], [0.4, 0.4]],
            source="auto",
            quality_status="ok",
            expl_area_m2=18.0,
            generator_area_m2=17.9,
        ),
    ]
    proj_slab = CadProjectLevels(
        project_id=proj_id,
        workspace_id=ws_id,
        slab_thickness_mm=220,
        slab_source_ref="КР2 л. 4",
    )
    # Порядок scalar: 1) TenderBaseRelease (None -> live_building3d), 2) CadProjectLevels
    # Порядок scalars: 1) CadSectionLevel, 2) CadFacadeView, 3) CadZone (focus_view)
    session = _FakeSession(
        scalar_seq=[None, proj_slab],
        scalars_seq=[[sec_row], [facade_row], zones],
    )

    result = await cad_project_context.build_project_context(
        cast(AsyncSession, session),
        AsyncMock(),
        project=project,
        focus_revision_id=rev_id,
        focus_page_index=7,
        focus_view=1,
    )

    assert result.schema_name == "quantor.cad_project_context.v1"
    assert result.coordination.source == "live_building3d"
    assert result.coordination.coordination is not None
    assert len(result.coordination.coordination.groups) == 1
    group = result.coordination.coordination.groups[0]
    assert {a.label for a in group.axes} == {"1", "А"}
    assert len(group.storeys) == 3

    assert len(result.views) == 3
    assert result.views[1].slab_area_m2 == 50.0
    assert result.views[1].frame == [10.0, 800.0, 35.277]

    assert result.project_slab_mm == 220 and result.project_slab_ref == "КР2 л. 4"
    assert len(result.sections) == 1 and result.sections[0].clear_height_mm == 3760
    assert len(result.kr_levels) == 1 and result.kr_levels[0].z_mm == 6360
    assert len(result.facades) == 1 and result.facades[0].axes == ["1", "12"]
    assert result.facades[0].windows_sample[0].z_bottom_mm == 7360
    # bool / NaN / inf безопасно отфильтровываются в None
    assert result.facades[0].windows_sample[1].z_bottom_mm is None
    assert result.facades[0].windows_sample[1].z_top_mm is None
    assert result.facades[0].windows_sample[1].width_mm is None

    assert result.focus_view is not None
    assert result.focus_view.below_label == "1 эт." and result.focus_view.below_z_mm == 0
    assert result.focus_view.above_label == "3 эт." and result.focus_view.above_z_mm == 10540
    # Дверь с названием «Выход на террасу» не попадает в счётчик комнат-террас
    assert result.focus_view.balcony_terrace_zones_count == 1
    assert result.focus_view.mop_zones_count == 1
    assert result.focus_view.apartment_zones_count == 1
    assert "building_mm" in result.focus_view.coordinate_bridge


async def test_build_project_context_prefers_active_base_release_coordination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws_id = uuid.uuid4()
    proj_id = uuid.uuid4()
    rel_id = uuid.uuid4()
    project = Project(id=proj_id, workspace_id=ws_id, name="Проект с выпуском базы")

    monkeypatch.setattr(
        cad_building3d_assembly,
        "build_building3d",
        AsyncMock(return_value=CadBuilding3dRead(units="mm", floors=[], groups=[], warnings=[])),
    )
    monkeypatch.setattr(cad_project_levels, "load_project_levels", AsyncMock(return_value={}))
    monkeypatch.setattr(sheet_passports, "latest_pdf_revisions", AsyncMock(return_value=[]))

    coord = ObjectBaseCoordination(
        schema_name="quantor.object_base.coordination.v1",
        units="mm",
        frame="building_mm",
        groups=[
            ObjectBaseCoordinationGroup(
                group_key="c1",
                group_label="Корпус 1",
                axes=[
                    ObjectBaseCoordinationAxis(
                        label="1",
                        orient="vertical",
                        point_mm=[0, 0],
                        direction=[0.0, 1.0],
                        views=2,
                        spread_mm=0,
                    )
                ],
                storeys=[
                    ObjectBaseCoordinationStorey(
                        label="2 эт.",
                        base_z_mm=6460,
                        floor_height_mm=4080,
                        elevation_known=True,
                        view_keys=[],
                    )
                ],
            )
        ],
        doubts=[],
    )
    release = TenderBaseRelease(
        id=rel_id,
        workspace_id=ws_id,
        project_id=proj_id,
        number=3,
        comment="Выпуск 3",
        include_dxf=False,
        views=[],
        package_key="tender/base.zip",
        package_sha256="a" * 64,
        manifest_sha256="b" * 64,
        size_bytes=1234,
    )
    monkeypatch.setattr(
        tender_base,
        "read_package_member",
        AsyncMock(return_value=json.dumps(coord.model_dump(mode="json", by_alias=True)).encode()),
    )
    session = _FakeSession(scalar_seq=[release, None], scalars_seq=[[], []])

    result = await cad_project_context.build_project_context(
        cast(AsyncSession, session),
        AsyncMock(),
        project=project,
    )
    assert result.coordination.source == "base_release"
    assert result.coordination.release_id == rel_id
    assert result.coordination.release_number == 3
    assert result.coordination.coordination is not None
    assert result.coordination.coordination.groups[0].axes[0].label == "1"


def test_render_slab_overlay_draws_slab_holes_levels_openings_and_grid(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    pil_image: Any = importlib.import_module("PIL.Image")

    from app.cad_worker.view_render_cli import render_slab_overlay

    base = pil_image.new("RGB", (600, 400), (255, 255, 255))
    walls: dict[str, Any] = {
        "slab": {"shell": [[0.0, 0.0], [10000.0, 0.0], [10000.0, 6000.0], [0.0, 6000.0]]},
        "slab_holes": [
            {
                "id": "h1",
                "shell": [
                    [2000.0, 2000.0],
                    [3500.0, 2000.0],
                    [3500.0, 3500.0],
                    [2000.0, 3500.0],
                ],
            }
        ],
        "levels": {
            "zones": [
                {"shell": [[5000.0, 1000.0], [8000.0, 1000.0], [8000.0, 4000.0], [5000.0, 4000.0]]}
            ]
        },
        "openings": [
            {
                "id": "w1",
                "kind": "window",
                "lintel": [[0.0, 2500.0], [200.0, 2500.0], [200.0, 4000.0], [0.0, 4000.0]],
            }
        ],
    }
    out_path = tmp_path / "slab_overlay.png"
    render_slab_overlay(
        base_rgb=base,
        walls=walls,
        frame=(10.0, 180.0, 25.0),
        zoom=1.0,
        pix_x=0,
        pix_y=0,
        out_path=out_path,
    )
    assert out_path.is_file()
    raw = out_path.read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    rendered = pil_image.open(out_path)
    assert rendered.size == (600, 400)
    # Изображение не осталось пустым белым (наложены плита, отверстие, проём и сетка).
    assert rendered.getextrema() != ((255, 255), (255, 255), (255, 255))


def test_slab_rings_take_all_parts_or_fall_back_to_shell() -> None:
    from app.cad_worker.view_render_cli import slab_rings

    first = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0]]
    second = [[5000.0, 0.0], [6000.0, 0.0], [6000.0, 1000.0]]
    both = {"shell": first, "parts": [{"shell": first}, {"shell": second}]}
    assert slab_rings(both) == [first, second]
    assert slab_rings({"shell": first}) == [first]
    assert slab_rings({"shell": first, "parts": []}) == [first]
    assert slab_rings(None) == []


def test_render_slab_overlay_draws_every_slab_part(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    pil_image: Any = importlib.import_module("PIL.Image")

    from app.cad_worker.view_render_cli import render_slab_overlay

    first = [[0.0, 0.0], [3000.0, 0.0], [3000.0, 3000.0], [0.0, 3000.0]]
    second = [[8000.0, 0.0], [10000.0, 0.0], [10000.0, 3000.0], [8000.0, 3000.0]]

    def second_part_pixel(slab: dict[str, Any]) -> tuple[int, int, int]:
        out_path = tmp_path / f"slab_{len(slab)}.png"
        render_slab_overlay(
            base_rgb=pil_image.new("RGB", (600, 400), (255, 255, 255)),
            walls={"slab": slab},
            frame=(10.0, 180.0, 25.0),
            zoom=1.0,
            pix_x=0,
            pix_y=0,
            out_path=out_path,
        )
        # Центр второй части: x = 10 + 9000/25 = 370, y = 180 - 1500/25 = 120.
        pixel: tuple[int, int, int] = pil_image.open(out_path).convert("RGB").getpixel((370, 120))
        return pixel

    assert second_part_pixel({"shell": first}) == (255, 255, 255)
    two_parts = {"shell": first, "parts": [{"shell": first}, {"shell": second}]}
    assert second_part_pixel(two_parts) != (255, 255, 255)


def test_slab_area_sums_extra_outline_parts() -> None:
    floor = _floor(revision_id=uuid.uuid4(), page_index=0)
    assert cad_project_context._slab_area_m2(floor) == 50.0
    two = floor.model_copy(
        update={"outline_parts": [[[20000.0, 0.0], [22000.0, 0.0], [22000.0, 3000.0]]]}
    )
    assert cad_project_context._slab_area_m2(two) == 53.0
