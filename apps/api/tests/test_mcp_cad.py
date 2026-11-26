"""Юнит-тесты CAD-инструментов MCP-сервера (чтение результатов чертежей, замечания, перестроение).

Тесты работают через `httpx.MockTransport` с настоящим `mcp_server.Caller` и `mcp_server.dispatch`:
проверяют маршруты, параметры, валидацию входов, ограничения размера и проброс отказов прав (403)
без зависимости от БД и POSIX-модулей.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import httpx
import pytest

from app.domain import JobType
from app.services import cad as cad_service
from app.services import mcp_server

PROJECT_ID = str(uuid.uuid4())
REVISION_ID = str(uuid.uuid4())
CONVERT_JOB_ID = str(uuid.uuid4())
WALLS_JOB_ID = str(uuid.uuid4())
REBUILD_JOB_ID = str(uuid.uuid4())
RECONVERT_JOB_ID = str(uuid.uuid4())
DXF_SHA = "a" * 64


def _rpc(method: str, params: dict[str, Any] | None = None, msg_id: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


async def _call(
    handler: Any, tool: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any], list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _dispatch(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        res: httpx.Response = handler(request)
        return res

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_dispatch), base_url="http://quantor.internal"
    ) as client:
        answer = await mcp_server.dispatch(
            _rpc("tools/call", {"name": tool, "arguments": arguments}),
            mcp_server.Caller(client),
        )
    assert isinstance(answer, dict) and "result" in answer
    result: dict[str, Any] = answer["result"]
    return result, seen


async def test_tools_list_exposes_cad_tools_with_expected_annotations() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _req: httpx.Response(200, json={})),
        base_url="http://quantor.internal",
    ) as client:
        listed = await mcp_server.dispatch(_rpc("tools/list"), mcp_server.Caller(client))
    assert isinstance(listed, dict)
    by_name = {t["name"]: t for t in listed["result"]["tools"]}
    for name in (
        "get_cad_pipeline",
        "get_cad_project_context",
        "get_cad_view",
        "get_cad_view_images",
        "get_cad_artifact",
    ):
        assert name in by_name
        assert by_name[name]["annotations"]["readOnlyHint"] is True
    for name in ("add_cad_remark", "rebuild_cad_view"):
        assert name in by_name
        assert by_name[name]["annotations"]["readOnlyHint"] is False


async def test_get_cad_pipeline_project_and_revision_modes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v1/projects/{PROJECT_ID}/ai-pipeline":
            return httpx.Response(
                200,
                json={
                    "sheets": [
                        {
                            "document_name": "АР2.pdf",
                            "revision_id": REVISION_ID,
                            "page_index": 7,
                            "sheet_title": "План 2 этажа",
                            "convert_job_id": CONVERT_JOB_ID,
                            "view": 1,
                            "walls_job_id": WALLS_JOB_ID,
                            "stage1": {"state": "ok"},
                            "stage4": {"open_remarks": 2, "approved": False},
                        }
                    ]
                },
            )
        if (
            request.url.path
            == f"/api/v1/projects/{PROJECT_ID}/revisions/{REVISION_ID}/cad/pipeline"
        ):
            return httpx.Response(
                200,
                json={
                    "sheets": [
                        {
                            "page_index": 7,
                            "title": "План 2 этажа",
                            "convert": {"job_id": CONVERT_JOB_ID, "status": "succeeded"},
                            "views": [
                                {
                                    "view": 1,
                                    "walls": {"job_id": WALLS_JOB_ID, "status": "succeeded"},
                                    "approved": True,
                                }
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    by_project, _ = await _call(handler, "get_cad_pipeline", {"project": PROJECT_ID})
    assert by_project["isError"] is False
    assert "АР2.pdf" in by_project["content"][0]["text"]
    assert "замечаний=2" in by_project["content"][0]["text"]

    by_revision, _ = await _call(
        handler, "get_cad_pipeline", {"project": PROJECT_ID, "revision_id": REVISION_ID}
    )
    assert by_revision["isError"] is False
    assert "одобрен" in by_revision["content"][0]["text"]

    bad, _ = await _call(
        handler, "get_cad_pipeline", {"project": PROJECT_ID, "revision_id": "bad-uuid"}
    )
    assert bad["isError"] is True and "revision_id" in bad["content"][0]["text"]


async def test_get_cad_view_combines_constructions_diagnostics_and_remarks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == (
            f"/api/v1/projects/{PROJECT_ID}/cad/{CONVERT_JOB_ID}/views/7/1/constructions"
        ):
            return httpx.Response(
                200,
                json={
                    "walls_job_id": WALLS_JOB_ID,
                    "generator": "cad_walls.v1.26",
                    "summary": {"total_count": 90},
                    "totals": [
                        {
                            "kind": "masonry",
                            "thickness_mm": 200,
                            "material": "aerated_concrete",
                            "count": 12,
                            "length_m": 45.2,
                            "wall_area_m2": 120.5,
                            "volume_m3": 24.1,
                        }
                    ],
                    "warnings": [],
                    "hints_applied": [{"id": "ai-1", "status": "applied"}],
                    "constructions": [{"id": "w1"}, {"id": "w2"}],
                    "openings": [{"id": "d1", "kind": "door"}],
                },
            )
        if request.url.path == (
            f"/api/v1/projects/{PROJECT_ID}/revisions/{REVISION_ID}/cad/{CONVERT_JOB_ID}/views/7/1"
        ):
            return httpx.Response(
                200,
                json={
                    "attempt": 2,
                    "status": "succeeded",
                    "scale_status": "dimension_checks_passed",
                    "frame": {"confirmed": True},
                    "dxf": {"sha256": DXF_SHA},
                    "files": [{"name": "PDF_008_Вид_01/scale.json", "size": 512}],
                },
            )
        if request.url.path == (
            f"/api/v1/projects/{PROJECT_ID}/revisions/{REVISION_ID}/cad/{CONVERT_JOB_ID}/remarks"
        ):
            assert request.url.params["attempt"] == "2"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "ai-1",
                        "type": "missing_wall",
                        "status": "open",
                        "reviewer": "Инженер",
                        "bbox_pt": [10.0, 20.0, 30.0, 40.0],
                        "comment": "Пропущена стена шахты",
                    }
                ],
            )
        return httpx.Response(404, json={"detail": "not found"})

    compact, _ = await _call(
        handler,
        "get_cad_view",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
        },
    )
    assert compact["isError"] is False
    text_out = compact["content"][0]["text"]
    assert "ai-1 [missing_wall] (Инженер) bbox_pt=[10.0, 20.0, 30.0, 40.0]" in text_out
    assert "Пропущена стена шахты" in text_out
    data = compact["structuredContent"]
    assert data["constructions"]["constructions_count"] == 2
    assert "constructions" not in data["constructions"]
    assert data["diagnostics"]["attempt"] == 2
    assert len(data["remarks"]) == 1

    detailed, _ = await _call(
        handler,
        "get_cad_view",
        {
            "project": PROJECT_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
            "include_constructions": True,
            "include_openings": True,
        },
    )
    assert detailed["isError"] is False
    assert len(detailed["structuredContent"]["constructions"]["constructions"]) == 2
    assert len(detailed["structuredContent"]["constructions"]["openings"]) == 1


async def test_get_cad_artifact_json_limits_and_safety() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/scale.json"):
            return httpx.Response(
                200,
                content=json.dumps({"status": "passed"}).encode("utf-8"),
                headers={"X-Content-SHA256": DXF_SHA},
            )
        if request.url.path.endswith("/huge.dxf"):
            return httpx.Response(200, content=b"x" * (mcp_server.MAX_MCP_ARTIFACT_BYTES + 1))
        if request.url.path.endswith("/binary.bin"):
            return httpx.Response(200, content=b"\xff\xfe\x00\x01")
        return httpx.Response(404, json={"detail": "not found"})

    ok, reqs = await _call(
        handler,
        "get_cad_artifact",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "name": "PDF_008_Вид_01/scale.json",
            "attempt": 1,
        },
    )
    assert ok["isError"] is False
    assert ok["structuredContent"]["content"] == {"status": "passed"}
    assert ok["structuredContent"]["sha256"] == DXF_SHA
    assert reqs[0].url.params["attempt"] == "1"

    oversized, _ = await _call(
        handler,
        "get_cad_artifact",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "name": "huge.dxf",
        },
    )
    assert oversized["isError"] is True and "предела MCP" in oversized["content"][0]["text"]

    binary, _ = await _call(
        handler,
        "get_cad_artifact",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "name": "binary.bin",
        },
    )
    assert binary["isError"] is True and "бинарный" in binary["content"][0]["text"]

    traversal, _ = await _call(
        handler,
        "get_cad_artifact",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "name": "../secret.json",
        },
    )
    assert traversal["isError"] is True and ".." in traversal["content"][0]["text"]


async def test_add_cad_remark_resolves_attempt_and_enforces_validation() -> None:
    captured_body: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == (
            f"/api/v1/projects/{PROJECT_ID}/revisions/{REVISION_ID}/cad/{CONVERT_JOB_ID}/views/7/1"
        ):
            return httpx.Response(200, json={"attempt": 3, "dxf": {"sha256": DXF_SHA}})
        if request.method == "PUT" and "/remarks/mcp-" in request.url.path:
            captured_body.update(json.loads(request.content))
            return httpx.Response(
                200,
                json={"id": request.url.path.rsplit("/", 1)[-1], **captured_body},
            )
        return httpx.Response(403, json={"detail": {"message": "Недостаточно прав"}})

    res, reqs = await _call(
        handler,
        "add_cad_remark",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
            "type": "missing_wall",
            "bbox_pt": [100.0, 200.0, 180.0, 240.0],
            "comment": "Пропущена перегородка санузла",
            "reviewer": "Gemini (MCP)",
        },
    )
    assert res["isError"] is False
    assert captured_body["reviewer"] == "Gemini (MCP)"
    assert captured_body["dxf_sha256"] == DXF_SHA
    assert captured_body["status"] == "open"
    put_req = next(r for r in reqs if r.method == "PUT")
    assert put_req.url.params["attempt"] == "3"
    assert put_req.url.params["page_index"] == "7"
    assert put_req.url.params["view"] == "1"

    bad_box, _ = await _call(
        handler,
        "add_cad_remark",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
            "type": "missing_wall",
            "bbox_pt": [200.0, 200.0, 100.0, 240.0],
            "comment": "Неверная рамка",
        },
    )
    assert bad_box["isError"] is True and "bbox_pt" in bad_box["content"][0]["text"]


@pytest.mark.parametrize(
    ("mode", "expected_path", "expected_job_id"),
    [
        (
            "rebuild_walls",
            f"/api/v1/projects/{PROJECT_ID}/cad/{CONVERT_JOB_ID}/views/7/1/walls/rebuild-by-remarks",
            REBUILD_JOB_ID,
        ),
        (
            "reconvert_pdf",
            f"/api/v1/projects/{PROJECT_ID}/revisions/{REVISION_ID}/cad/{CONVERT_JOB_ID}/views/7/1/reconvert-by-remarks",
            RECONVERT_JOB_ID,
        ),
    ],
)
async def test_rebuild_cad_view_modes(mode: str, expected_path: str, expected_job_id: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == expected_path:
            return httpx.Response(202, json={"job_id": expected_job_id, "status": "queued"})
        return httpx.Response(404, json={"detail": "not found"})

    args: dict[str, Any] = {
        "project": PROJECT_ID,
        "job_id": CONVERT_JOB_ID,
        "page_index": 7,
        "view": 1,
        "mode": mode,
    }
    if mode == "reconvert_pdf":
        args["revision_id"] = REVISION_ID
    res, _ = await _call(handler, "rebuild_cad_view", args)
    assert res["isError"] is False
    assert res["structuredContent"]["job"]["job_id"] == expected_job_id


async def test_rebuild_cad_view_reconvert_requires_revision_id() -> None:
    res, _ = await _call(
        lambda _req: httpx.Response(200, json={}),
        "rebuild_cad_view",
        {
            "project": PROJECT_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
            "mode": "reconvert_pdf",
        },
    )
    assert res["isError"] is True and "revision_id" in res["content"][0]["text"]


async def test_get_cad_view_images_returns_mcp_image_blocks_and_render_meta() -> None:
    plan_png = b"\x89PNG\r\n\x1a\nplan-bytes"
    overlay_png = b"\x89PNG\r\n\x1a\noverlay-bytes"
    render_json = {
        "clip": [10.0, 20.0, 1010.0, 520.0],
        "zoom": 2.0,
        "width_px": 2000,
        "height_px": 1000,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == (
            f"/api/v1/projects/{PROJECT_ID}/cad/{CONVERT_JOB_ID}/views/7/1/constructions"
        ):
            return httpx.Response(200, json={"walls_job_id": WALLS_JOB_ID})
        base = (
            f"/api/v1/projects/{PROJECT_ID}/revisions/{REVISION_ID}"
            f"/cad/{WALLS_JOB_ID}/artifacts/views/p008_v01"
        )
        if request.url.path == f"{base}/render.json":
            return httpx.Response(200, json=render_json)
        if request.url.path == f"{base}/plan.png":
            return httpx.Response(200, content=plan_png, headers={"X-Content-SHA256": DXF_SHA})
        if request.url.path == f"{base}/overlay.png":
            return httpx.Response(200, content=overlay_png, headers={"X-Content-SHA256": DXF_SHA})
        return httpx.Response(404, json={"detail": "not found"})

    res, _ = await _call(
        handler,
        "get_cad_view_images",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
        },
    )
    assert res["isError"] is False
    blocks = res["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[1] == {
        "type": "image",
        "data": base64.b64encode(plan_png).decode("ascii"),
        "mimeType": "image/png",
    }
    assert blocks[2] == {
        "type": "image",
        "data": base64.b64encode(overlay_png).decode("ascii"),
        "mimeType": "image/png",
    }
    assert res["structuredContent"]["render"] == render_json
    assert res["structuredContent"]["walls_job_id"] == WALLS_JOB_ID


async def test_get_cad_view_images_handles_missing_and_invalid_png() -> None:
    def missing_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/constructions"):
            return httpx.Response(200, json={"walls_job_id": WALLS_JOB_ID})
        return httpx.Response(404, json={"detail": "not found"})

    missing, _ = await _call(
        missing_handler,
        "get_cad_view_images",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
        },
    )
    assert (
        missing["isError"] is True and "пересчитайте конструкции" in missing["content"][0]["text"]
    )

    def bad_png_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/render.json"):
            return httpx.Response(
                200,
                json={
                    "clip": [0.0, 0.0, 100.0, 100.0],
                    "zoom": 1.0,
                    "width_px": 100,
                    "height_px": 100,
                },
            )
        if request.url.path.endswith("/plan.png"):
            return httpx.Response(200, content=b"not-a-png")
        return httpx.Response(404)

    bad, _ = await _call(
        bad_png_handler,
        "get_cad_view_images",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "walls_job_id": WALLS_JOB_ID,
            "page_index": 7,
            "view": 1,
            "which": "plan",
        },
    )
    assert bad["isError"] is True and "не PNG" in bad["content"][0]["text"]


async def test_add_cad_remark_converts_bbox_px_via_render_json() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/constructions"):
            return httpx.Response(200, json={"walls_job_id": WALLS_JOB_ID})
        if request.url.path.endswith("/render.json"):
            return httpx.Response(
                200,
                json={
                    "clip": [10.0, 20.0, 510.0, 420.0],
                    "zoom": 2.0,
                    "width_px": 1000,
                    "height_px": 800,
                },
            )
        if request.url.path == (
            f"/api/v1/projects/{PROJECT_ID}/revisions/{REVISION_ID}/cad/{CONVERT_JOB_ID}/views/7/1"
        ):
            return httpx.Response(200, json={"attempt": 1, "dxf": {"sha256": DXF_SHA}})
        if request.method == "PUT":
            captured.update(json.loads(request.content))
            return httpx.Response(200, json={"id": "mcp-px", **captured})
        return httpx.Response(404)

    res, _ = await _call(
        handler,
        "add_cad_remark",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
            "type": "missing_door",
            "bbox_px": [200.0, 100.0, 260.0, 160.0],
            "comment": "Нет двери в санузел",
            "reviewer": "Gemini (MCP)",
        },
    )
    assert res["isError"] is False
    # clip=[10, 20, 510, 420], zoom=2, pad=6 -> [10+100-6, 20+50-6, 10+130+6, 20+80+6]
    assert captured["bbox_pt"] == [104.0, 64.0, 146.0, 106.0]

    both, _ = await _call(
        handler,
        "add_cad_remark",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "page_index": 7,
            "view": 1,
            "type": "missing_door",
            "bbox_pt": [10.0, 10.0, 20.0, 20.0],
            "bbox_px": [10.0, 10.0, 20.0, 20.0],
            "comment": "Оба поля сразу",
        },
    )
    assert both["isError"] is True and "ровно одно" in both["content"][0]["text"]


def test_cad_walls_image_artifacts_are_allowed_in_cad_service() -> None:
    assert JobType.CAD_WALLS in cad_service.CAD_ARTIFACT_JOB_TYPES
    assert cad_service.content_type_for("views/p008_v01/plan.png") == "image/png"
    assert cad_service.content_type_for("views/p008_v01/slab_overlay.png") == "image/png"
    for suffix in ("walls.json", "plan.png", "overlay.png", "slab_overlay.png", "render.json"):
        assert cad_service.WALLS_ARTIFACT_NAME.fullmatch(f"views/p008_v01/{suffix}") is not None


async def test_get_cad_project_context_and_slab_overlay_images() -> None:
    png_stub = b"\x89PNG\r\n\x1a\n" + b"0" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/api/v1/projects/{PROJECT_ID}/cad/project-context":
            focus = (
                {
                    "view_key": f"{REVISION_ID}:7:1",
                    "revision_id": REVISION_ID,
                    "page_index": 7,
                    "view": 1,
                    "placement": {
                        "base_z_mm": 6460,
                        "floor_height_mm": 4080,
                        "floor_height_known": True,
                        "slab_thickness_mm": 220,
                        "slab_thickness_known": True,
                        "offset_mm": [0.0, 0.0],
                        "rotation_deg": 0.0,
                    },
                    "below_label": "1 эт.",
                    "below_z_mm": 0,
                    "above_label": "3 эт.",
                    "above_z_mm": 10540,
                    "zones": [{"id": "z1", "name": "Терраса"}],
                    "apartment_zones_count": 1,
                    "mop_zones_count": 0,
                    "balcony_terrace_zones_count": 1,
                }
                if "revision_id" in request.url.params
                else None
            )
            return httpx.Response(
                200,
                json={
                    "schema": "quantor.cad_project_context.v1",
                    "project_id": PROJECT_ID,
                    "project_name": "Капельский",
                    "coordination": {
                        "source": "live_building3d",
                        "note": "Живая сетка",
                        "coordination": {
                            "groups": [
                                {
                                    "group_label": "Корпус 1",
                                    "axes": [{"label": "1"}, {"label": "А"}],
                                    "storeys": [{"base_z_mm": 6460}],
                                }
                            ]
                        },
                    },
                    "views": [{"view_key": f"{REVISION_ID}:7:1"}],
                    "sections": [{"elevation_mm": 6460, "clear_height_mm": 3760}],
                    "kr_levels": [{"corps": "1", "floor": 2, "z_mm": 6360}],
                    "project_slab_mm": 220,
                    "project_slab_ref": "КР2 л. 4",
                    "facades": [{"title": "Фасад 1-12"}],
                    "focus_view": focus,
                },
            )
        if request.url.path == (
            f"/api/v1/projects/{PROJECT_ID}/revisions/{REVISION_ID}/cad/{WALLS_JOB_ID}"
            "/artifacts/views/p008_v01/render.json"
        ):
            return httpx.Response(
                200,
                json={
                    "clip": [0.0, 0.0, 1000.0, 600.0],
                    "zoom": 2.0,
                    "width_px": 2000,
                    "height_px": 1200,
                },
            )
        if request.url.path.endswith(("/plan.png", "/overlay.png", "/slab_overlay.png")):
            return httpx.Response(200, content=png_stub, headers={"x-content-sha256": "b" * 64})
        return httpx.Response(404, json={"detail": "not found"})

    ctx, seen = await _call(
        handler,
        "get_cad_project_context",
        {"project": PROJECT_ID, "revision_id": REVISION_ID, "page_index": 7, "view": 1},
    )
    assert ctx["isError"] is False
    text = ctx["content"][0]["text"]
    assert "live_building3d" in text and "балконы/террасы=1" in text and "КР2 л. 4" in text
    assert seen[0].url.params["page_index"] == "7"

    partial, _ = await _call(
        handler, "get_cad_project_context", {"project": PROJECT_ID, "revision_id": REVISION_ID}
    )
    assert partial["isError"] is True and "вместе" in partial["content"][0]["text"]

    slab_only, _ = await _call(
        handler,
        "get_cad_view_images",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "walls_job_id": WALLS_JOB_ID,
            "page_index": 7,
            "view": 1,
            "which": "slab",
        },
    )
    assert slab_only["isError"] is False
    assert [c["type"] for c in slab_only["content"]] == ["text", "image"]
    assert "slab_overlay.png" in slab_only["content"][0]["text"]

    all_imgs, _ = await _call(
        handler,
        "get_cad_view_images",
        {
            "project": PROJECT_ID,
            "revision_id": REVISION_ID,
            "job_id": CONVERT_JOB_ID,
            "walls_job_id": WALLS_JOB_ID,
            "page_index": 7,
            "view": 1,
            "which": "all",
        },
    )
    assert all_imgs["isError"] is False
    assert [c["type"] for c in all_imgs["content"]] == ["text", "image", "image", "image"]


def test_convert_hints_merge_preserves_previous_and_supports_250_limit() -> None:
    from app.contracts.cad_convert_hints import MAX_CONVERT_HINTS, CadConvertHint
    from app.models import Job
    from app.services.cad_convert_hints import merge_hints, previous_hints_of

    assert MAX_CONVERT_HINTS == 250
    prev_job = Job(
        job_type=JobType.CAD_PDF_CONVERT,
        payload={
            "params": {
                "convert_hints": {
                    "schema": "quantor.cad_convert_hints.v1",
                    "page": 8,
                    "hints": [
                        {
                            "id": "old-1",
                            "type": "missing_wall",
                            "bbox_pt": [1.0, 2.0, 3.0, 4.0],
                            "comment": "старая",
                        },
                        {
                            "id": "shared",
                            "type": "missing_wall",
                            "bbox_pt": [5.0, 6.0, 7.0, 8.0],
                            "comment": "до правки",
                        },
                    ],
                }
            }
        },
    )
    prev = previous_hints_of(prev_job)
    assert [h.id for h in prev] == ["old-1", "shared"]
    cur = [
        CadConvertHint(id="shared", type="missing_wall", bbox_pt=(5, 6, 9, 10), comment="после"),
        CadConvertHint(id="new-1", type="missing_wall", bbox_pt=(10, 20, 30, 40), comment="новая"),
    ]
    merged = merge_hints(prev, cur)
    assert [h.id for h in merged] == ["old-1", "shared", "new-1"]
    assert merged[1].comment == "после"
    trimmed = merge_hints(prev, cur, limit=2)
    assert [h.id for h in trimmed] == ["shared", "new-1"]
