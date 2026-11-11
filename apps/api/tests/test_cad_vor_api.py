"""ВОР Заказчика в контуре CAD (ADR-0038 п. 5): загрузка, строки, подсказки, связи, сверка листа.

Книги синтетические. Для сверки листа используется заглушка скрипта cad_walls из теста
конструкций: группы листа - masonry|200|, masonry|100|, monolith_column|400|.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.main import create_app
from app.models import CadVorDocument, CadVorItem, CadVorLink, Workspace
from app.services import cad_vor as vor_service
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_constructions_api import PARAMS, STUB, _ready_sheet, _url, walls_settings
from tests.test_cad_vor_import import HEADER, workbook_bytes

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ROWS: list[list[object]] = [
    ["Ведомость объёмов работ"],
    HEADER,
    ["Раздел 1. Кладка"],
    [1, "Кладка перегородок из газобетона 100 мм", "м2", "120,5"],
    [2, "Кладка перегородок из кирпича толщиной 120 мм", "м2", 40],
    [3, "Устройство монолитных стен толщиной 200 мм", "м3", 15.5],
    [4, "Кладка наружных стен из газобетонных блоков 200 мм", "м2", 300],
    ["Раздел 2. Прочее"],
    [5, "Монолитные колонны 400х400", "м3", 7],
    [6, "Окна ПВХ", "шт", 50],
]


@pytest.fixture
def walls_tools(tmp_path: Path) -> Path:
    """Параметры и заглушка скрипта конструкций: то, что в образе лежит в tools/cad_walls."""
    root = tmp_path / "tools" / "cad_walls"
    (root / "params").mkdir(parents=True)
    (root / "cad_walls").mkdir()
    (root / "params" / "v1.json").write_text(json.dumps(PARAMS), encoding="utf-8")
    (root / "cad_walls" / "version.py").write_text('GENERATOR_VERSION = "cad_walls.v1"\n')
    (root / "run_walls.py").write_text(STUB, encoding="utf-8")
    return root


def vor_settings(*, flag: bool = True) -> Settings:
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true" if flag else "",
        cad_engine_python=sys.executable,
    )


async def _project(api: AsyncClient) -> str:
    response = await api.post("/api/v1/projects", json={"name": f"ВОР {uuid.uuid4().hex[:6]}"})
    return str(response.json()["id"])


async def _upload(
    api: AsyncClient,
    project_id: str,
    rows: list[list[object]] | None = None,
    name: str = "ВОР.xlsx",
    data: bytes | None = None,
) -> Any:
    content = data if data is not None else workbook_bytes({"ВОР": rows or ROWS})
    return await api.post(
        f"/api/v1/projects/{project_id}/cad/vor", files={"file": (name, content, XLSX)}
    )


def _by_name(items: list[dict[str, Any]], part: str) -> dict[str, Any]:
    return next(item for item in items if part in item["name"])


# ------------------------------------------------------------------ доступ


async def test_routes_are_closed_when_the_flag_is_off(
    db_session: AsyncSession, build_api: Callable[..., AsyncClient]
) -> None:
    fake = str(uuid.uuid4())
    async with build_api(make_context(), settings=vor_settings(flag=False)) as api:
        base = f"/api/v1/projects/{fake}/cad/vor"
        calls: list[tuple[str, str, dict[str, Any]]] = [
            ("get", base, {}),
            ("get", f"{base}/links", {}),
            ("get", f"{base}/suggest?group_key=masonry%7C100%7C", {}),
            ("get", f"{base}/{fake}/items", {}),
            ("put", f"{base}/links/masonry%7C100%7C", {"json": {"vor_item_ids": []}}),
            ("delete", f"{base}/{fake}", {}),
            ("post", base, {"files": {"file": ("a.xlsx", b"x", XLSX)}}),
            ("post", f"{base}/from-revision", {"json": {"revision_id": fake}}),
            ("get", _url(fake, fake, "vor-coverage"), {}),
        ]
        for method, url, kwargs in calls:
            response = await api.request(method, url, **kwargs)
            assert response.status_code == 403, url
            assert response.json()["detail"]["code"] == "FEATURE_DISABLED", url


async def test_foreign_workspace_gets_404(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    second_workspace: Workspace,
) -> None:
    second_id = second_workspace.id
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        uploaded = await _upload(api, project_id)
        assert uploaded.status_code == 201, uploaded.text
        document_id = uploaded.json()["id"]
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=vor_settings()) as foreign:
        base = f"/api/v1/projects/{project_id}/cad/vor"
        for method, url, kwargs in (
            ("get", base, {}),
            ("get", f"{base}/links", {}),
            ("get", f"{base}/suggest?group_key=masonry%7C100%7C", {}),
            ("get", f"{base}/{document_id}/items", {}),
            ("put", f"{base}/links/masonry%7C100%7C", {"json": {"vor_item_ids": []}}),
            ("delete", f"{base}/{document_id}", {}),
            ("post", base, {"files": {"file": ("a.xlsx", workbook_bytes({"a": [HEADER]}), XLSX)}}),
            ("get", _url(project_id, str(uuid.uuid4()), "vor-coverage"), {}),
        ):
            response = await foreign.request(method, url, **kwargs)
            assert response.status_code == 404, url
    assert (await db_session.scalar(select(func.count()).select_from(CadVorDocument))) == 1


# ------------------------------------------------------------------ загрузка и строки


async def test_upload_lists_documents_and_items(
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    db_session: AsyncSession,
) -> None:
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        base = f"/api/v1/projects/{project_id}/cad/vor"
        assert (await api.get(base)).json() == []

        first = await _upload(api, project_id)
        assert first.status_code == 201, first.text
        document = first.json()
        assert document["file_name"] == "ВОР.xlsx" and document["rows_count"] == 6
        assert document["sheet_names"] == ["ВОР"] and document["header_row"] == 2
        assert document["columns"] == [
            {
                "sheet": "ВОР",
                "header_row": 2,
                "rows_count": 6,
                "columns": {"code": 1, "name": 2, "unit": 3, "quantity": 4},
            }
        ]
        stored = [key for key in fake_storage.objects if key.startswith("cad-vor/")]
        assert stored == [f"cad-vor/{project_id}/{document['id']}.xlsx"]

        second = await _upload(api, project_id, [HEADER, [1, "Кладка 80 мм", "м2", 1]], "ВОР2.xlsx")
        assert second.status_code == 201
        listed = (await api.get(base)).json()
        assert [d["id"] for d in listed] == [second.json()["id"], document["id"]]

        items = (await api.get(f"{base}/{document['id']}/items")).json()
        assert items["total"] == 6
        gas = _by_name(items["items"], "газобетона 100")
        assert gas["quantity"] == 120.5 and gas["unit"] == "м2" and gas["code"] == "1"
        assert gas["thickness_hint_mm"] == 100 and gas["kind_hint"] == "masonry"
        assert gas["section"] == "Раздел 1. Кладка" and gas["row_no"] == 4

        by_word = (
            await api.get(f"{base}/{document['id']}/items", params={"q": "ГАЗОБЕТОН блоков"})
        ).json()
        assert [i["code"] for i in by_word["items"]] == ["4"]
        by_kind = (
            await api.get(f"{base}/{document['id']}/items", params={"kind": "monolith"})
        ).json()
        assert {i["code"] for i in by_kind["items"]} == {"3", "5"}
        by_thickness = (
            await api.get(f"{base}/{document['id']}/items", params={"thickness": 200})
        ).json()
        assert {i["code"] for i in by_thickness["items"]} == {"3", "4"}
        page = (
            await api.get(f"{base}/{document['id']}/items", params={"limit": 2, "offset": 4})
        ).json()
        assert page["total"] == 6 and len(page["items"]) == 2
        # Подстановочные символы в запросе - обычный текст, а не шаблон.
        assert (await api.get(f"{base}/{document['id']}/items", params={"q": "%"})).json()[
            "total"
        ] == 0
        missing = await api.get(f"{base}/{uuid.uuid4()}/items")
        assert missing.status_code == 404


async def test_upload_rejects_bad_files(
    build_api: Callable[..., AsyncClient], fake_storage: FakeObjectStorage
) -> None:
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        cases: list[tuple[str, bytes, int, str]] = [
            ("ВОР.xlsx", b"\x00" * 0, 400, "EMPTY_FILE"),
            ("ВОР.xlsx", "просто текст".encode(), 422, "CAD_VOR_PARSE_FAILED"),
            ("ВОР.csv", b"a;b", 422, "CAD_VOR_PARSE_FAILED"),
            (
                "ВОР.xlsx",
                workbook_bytes({"x": [["без", "заголовка"]]}),
                422,
                "CAD_VOR_PARSE_FAILED",
            ),
            ("ВОР.xlsx", b"PK\x03\x04" + b"\x00" * (21 * 1024 * 1024), 413, "UPLOAD_TOO_LARGE"),
        ]
        for name, data, code, error in cases:
            response = await _upload(api, project_id, name=name, data=data)
            assert response.status_code == code, (name, response.text)
            assert response.json()["detail"]["code"] == error
        parse_error = await _upload(
            api, project_id, data=workbook_bytes({"x": [["без", "заголовка"]]})
        )
        assert "заголовка" in parse_error.json()["detail"]["message"]
    assert not [key for key in fake_storage.objects if key.startswith("cad-vor/")]


# ------------------------------------------------------------------ ВОР из документов проекта


async def _document_revision(
    api: AsyncClient, project_id: str, name: str, data: bytes, content_type: str = XLSX
) -> str:
    """Кладёт файл в документы проекта общей загрузкой и возвращает id его ревизии."""
    response = await api.post(
        f"/api/v1/projects/{project_id}/uploads", files={"file": (name, data, content_type)}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["revision"]["id"])


async def test_import_from_revision_copies_the_book(
    build_api: Callable[..., AsyncClient], fake_storage: FakeObjectStorage
) -> None:
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        revision_id = await _document_revision(
            api, project_id, "ВОР Заказчика.xlsx", workbook_bytes({"ВОР": ROWS})
        )
        base = f"/api/v1/projects/{project_id}/cad/vor"
        response = await api.post(f"{base}/from-revision", json={"revision_id": revision_id})
        assert response.status_code == 201, response.text
        document = response.json()
        assert document["file_name"] == "ВОР Заказчика.xlsx" and document["rows_count"] == 6
        assert (await api.get(base)).json()[0]["id"] == document["id"]

        # Копия лежит в своём ключе; объект документа проекта остался на месте.
        copy_key = f"cad-vor/{project_id}/{document['id']}.xlsx"
        assert copy_key in fake_storage.objects
        originals = [key for key in fake_storage.objects if not key.startswith("cad-vor/")]
        assert len(originals) == 1
        assert fake_storage.objects[copy_key] == fake_storage.objects[originals[0]]

        # Удаление ВОР не задевает файл документа.
        assert (await api.delete(f"{base}/{document['id']}")).status_code == 204
        assert copy_key not in fake_storage.objects
        assert originals[0] in fake_storage.objects


async def test_import_from_revision_rejects_foreign_and_unknown_revisions(
    build_api: Callable[..., AsyncClient], second_workspace: Workspace
) -> None:
    second_id = second_workspace.id
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        other_project_id = await _project(api)
        revision_id = await _document_revision(
            api, project_id, "ВОР.xlsx", workbook_bytes({"ВОР": ROWS})
        )
        # Ревизия документа другого проекта того же пространства.
        wrong_project = await api.post(
            f"/api/v1/projects/{other_project_id}/cad/vor/from-revision",
            json={"revision_id": revision_id},
        )
        assert wrong_project.status_code == 404
        unknown = await api.post(
            f"/api/v1/projects/{project_id}/cad/vor/from-revision",
            json={"revision_id": str(uuid.uuid4())},
        )
        assert unknown.status_code == 404
    stranger = make_context(platform_admin=False, workspace_id=second_id)
    async with build_api(stranger, settings=vor_settings()) as foreign:
        response = await foreign.post(
            f"/api/v1/projects/{project_id}/cad/vor/from-revision",
            json={"revision_id": revision_id},
        )
        assert response.status_code == 404


async def test_import_from_revision_rejects_non_xlsx_and_bad_books(
    build_api: Callable[..., AsyncClient], fake_storage: FakeObjectStorage
) -> None:
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        url = f"/api/v1/projects/{project_id}/cad/vor/from-revision"
        pdf = await _document_revision(
            api, project_id, "чертёж.pdf", b"%PDF-1.7\n" + b"0" * 64, "application/pdf"
        )
        no_header = await _document_revision(
            api, project_id, "пустая.xlsx", workbook_bytes({"x": [["без", "заголовка"]]})
        )
        for revision_id in (pdf, no_header):
            response = await api.post(url, json={"revision_id": revision_id})
            assert response.status_code == 422, response.text
            assert response.json()["detail"]["code"] == "CAD_VOR_PARSE_FAILED"
        assert (await api.get(f"/api/v1/projects/{project_id}/cad/vor")).json() == []
    assert not [key for key in fake_storage.objects if key.startswith("cad-vor/")]


# ------------------------------------------------------------------ подсказки и связи


async def test_suggest_ranks_by_thickness_kind_and_material(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        base = f"/api/v1/projects/{project_id}/cad/vor"
        assert (await api.get(f"{base}/suggest?group_key=masonry%7C100%7C")).json() == []
        await _upload(api, project_id)

        plain = (await api.get(f"{base}/suggest", params={"group_key": "masonry|100|"})).json()
        assert plain[0]["item"]["code"] == "1"
        assert plain[0]["reasons"] == ["thickness", "kind"]
        # Монолитная стена той же толщины 200 - позже по виду; кладка 200 мм - первая.
        wall = (
            await api.get(f"{base}/suggest", params={"group_key": "masonry|200|aerated_concrete"})
        ).json()
        assert wall[0]["item"]["code"] == "4"
        assert "material" in wall[0]["reasons"]
        mono = (await api.get(f"{base}/suggest", params={"group_key": "monolith_wall|200|"})).json()
        assert mono[0]["item"]["code"] == "3"
        assert len(wall) <= 10 and all(s["score"] > 0 for s in wall)

        by_material = (
            await api.get(f"{base}/suggest", params={"group_key": "masonry|150|brick_solid"})
        ).json()
        assert by_material[0]["item"]["code"] == "2" and by_material[0]["reasons"] == [
            "kind",
            "material",
        ]

        bad = await api.get(f"{base}/suggest", params={"group_key": "wall|100|"})
        assert bad.status_code == 422
        unknown = await api.get(
            f"{base}/suggest",
            params={"group_key": "masonry|100|", "document_id": str(uuid.uuid4())},
        )
        assert unknown.status_code == 404


async def test_links_put_get_replace_and_validation(
    build_api: Callable[..., AsyncClient], db_session: AsyncSession
) -> None:
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        other_project = await _project(api)
        base = f"/api/v1/projects/{project_id}/cad/vor"
        document = (await _upload(api, project_id)).json()
        foreign_document = (await _upload(api, other_project)).json()
        items = (await api.get(f"{base}/{document['id']}/items")).json()["items"]
        foreign_items = (
            await api.get(
                f"/api/v1/projects/{other_project}/cad/vor/{foreign_document['id']}/items"
            )
        ).json()["items"]
        one, four = _by_name(items, "газобетона 100")["id"], _by_name(items, "блоков 200")["id"]
        key = "masonry|100|aerated_concrete"
        url = f"{base}/links/{key}"

        assert (await api.get(f"{base}/links")).json() == []
        put = await api.put(url, json={"vor_item_ids": [one, four, one]})
        assert put.status_code == 200, put.text
        assert {i["id"] for i in put.json()} == {one, four}
        links = (await api.get(f"{base}/links")).json()
        assert {(link["group_key"], link["item"]["id"]) for link in links} == {
            (key, one),
            (key, four),
        }
        assert _by_name([link["item"] for link in links], "100 мм")["quantity"] == 120.5

        # Замена набора: остаётся ровно переданное, у другой группы связи свои.
        await api.put(f"{base}/links/masonry%7C200%7C", json={"vor_item_ids": [four]})
        replaced = await api.put(url, json={"vor_item_ids": [four]})
        assert [i["id"] for i in replaced.json()] == [four]
        links = (await api.get(f"{base}/links")).json()
        assert sorted((link["group_key"], link["item"]["id"]) for link in links) == sorted(
            [(key, four), ("masonry|200|", four)]
        )

        assert (await api.put(url, json={"vor_item_ids": []})).json() == []
        assert [link["group_key"] for link in (await api.get(f"{base}/links")).json()] == [
            "masonry|200|"
        ]

        # Чужая строка и несуществующая строка не принимаются; неверный ключ - 422.
        for bad in ([foreign_items[0]["id"]], [str(uuid.uuid4())]):
            response = await api.put(url, json={"vor_item_ids": bad})
            assert response.status_code == 422, response.text
        assert (await api.put(f"{base}/links/oops", json={"vor_item_ids": []})).status_code == 422
        too_many = await api.put(
            url, json={"vor_item_ids": [str(uuid.uuid4()) for _ in range(201)]}
        )
        assert too_many.status_code == 422
    assert await db_session.scalar(select(func.count()).select_from(CadVorLink)) == 1


async def test_delete_cascades_items_and_links_and_removes_the_file(
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    db_session: AsyncSession,
) -> None:
    async with build_api(make_context(), settings=vor_settings()) as api:
        project_id = await _project(api)
        base = f"/api/v1/projects/{project_id}/cad/vor"
        document = (await _upload(api, project_id)).json()
        items = (await api.get(f"{base}/{document['id']}/items")).json()["items"]
        await api.put(f"{base}/links/masonry%7C100%7C", json={"vor_item_ids": [items[0]["id"]]})
        assert await db_session.scalar(select(func.count()).select_from(CadVorLink)) == 1

        assert (await api.delete(f"{base}/{document['id']}")).status_code == 204
        assert (await api.delete(f"{base}/{document['id']}")).status_code == 404
        assert (await api.get(base)).json() == []
        assert (await api.get(f"{base}/links")).json() == []
    assert await db_session.scalar(select(func.count()).select_from(CadVorItem)) == 0
    assert await db_session.scalar(select(func.count()).select_from(CadVorLink)) == 0
    assert fake_storage.deleted == [f"cad-vor/{project_id}/{document['id']}.xlsx"]


# ------------------------------------------------------------------ сверка листа


async def test_coverage_marks_unlinked_groups_and_missing_thicknesses(
    build_api: Callable[..., AsyncClient],
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    walls_tools: Path,
    tmp_path: Path,
) -> None:
    settings = walls_settings(walls_tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, _rev, job_id, _walls = await _ready_sheet(
            api, db_session, fake_storage, settings
        )
        coverage_url = _url(project_id, job_id, "vor-coverage")
        base = f"/api/v1/projects/{project_id}/cad/vor"

        # ВОРа нет: подсвечивать нечего, группы честно «не в ВОР».
        empty = (await api.get(coverage_url)).json()
        assert empty["has_vor"] is False
        assert empty["not_in_vor_keys"] == [] and empty["thickness_not_in_vor"] == []
        assert [g["group_key"] for g in empty["groups"]] == [
            "masonry|100|",
            "masonry|200|",
            "monolith_column|400|",
        ]
        assert {g["status"] for g in empty["groups"]} == {"not_in_vor"}

        document = (await _upload(api, project_id)).json()
        items = (await api.get(f"{base}/{document['id']}/items")).json()["items"]
        await api.put(
            f"{base}/links/masonry%7C100%7C",
            json={"vor_item_ids": [_by_name(items, "газобетона 100")["id"]]},
        )
        body = (await api.get(coverage_url)).json()
        assert body["has_vor"] is True and body["job_id"] == job_id
        by_key = {g["group_key"]: g for g in body["groups"]}
        assert by_key["masonry|100|"]["status"] == "linked"
        linked_item = by_key["masonry|100|"]["items"][0]
        assert linked_item["quantity"] == 120.5 and linked_item["code"] == "1"
        assert (
            by_key["masonry|200|"]["status"] == "not_in_vor"
            and by_key["masonry|200|"]["items"] == []
        )
        # a - кладка 200, d - колонна 400; b (100 мм) связана, c без номинала в итоги не входит.
        assert body["not_in_vor_keys"] == ["aaaaaaaaaaaa", "dddddddddddd"]
        assert body["vor_thicknesses"] == [100, 120, 200]
        assert body["thickness_not_in_vor"] == ["monolith_column|400|"]

        # Связь с материалом отделяет группу: masonry|200|aerated_concrete - другой ключ.
        await api.put(
            f"{base}/links/masonry%7C200%7C",
            json={"vor_item_ids": [_by_name(items, "блоков 200")["id"]]},
        )
        again = (await api.get(coverage_url)).json()
        assert again["not_in_vor_keys"] == ["dddddddddddd"]

        # Новый документ - текущий: список толщин берётся по нему, связи остаются.
        await _upload(api, project_id, [HEADER, [1, "Окна", "шт", 1]], "ВОР2.xlsx")
        latest = (await api.get(coverage_url)).json()
        assert latest["vor_thicknesses"] == [] and latest["thickness_not_in_vor"] == []
        assert latest["not_in_vor_keys"] == ["dddddddddddd"]

        for document_row in (await api.get(base)).json():
            await api.delete(f"{base}/{document_row['id']}")
        gone = (await api.get(coverage_url)).json()
        assert gone["has_vor"] is False and {g["status"] for g in gone["groups"]} == {"not_in_vor"}

        not_ready = await api.get(_url(project_id, job_id, "vor-coverage", view=7))
        assert not_ready.status_code == 404


def test_routes_are_in_openapi_and_group_key_is_one_function() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/cad/vor"
    assert set(paths[base]) == {"get", "post"}
    assert set(paths[f"{base}/links"]) == {"get"}
    assert set(paths[f"{base}/links/{{group_key}}"]) == {"put"}
    assert set(paths[f"{base}/suggest"]) == {"get"}
    assert set(paths[f"{base}/{{document_id}}/items"]) == {"get"}
    assert set(paths[f"{base}/{{document_id}}"]) == {"delete"}
    coverage = "/api/v1/projects/{project_id}/cad/{job_id}/views/{page_index}/{view}/vor-coverage"
    assert set(paths[coverage]) == {"get"}
    assert vor_service.group_key("masonry", 100.0, None) == "masonry|100|"
    assert vor_service.group_key("masonry", 137.5, "brick_solid") == "masonry|137.5|brick_solid"
    parts = vor_service.parse_group_key("monolith_wall|200|")
    assert parts is not None and parts.thickness_mm == 200.0 and parts.material == ""
    assert vor_service.parse_group_key("wall|200|") is None
