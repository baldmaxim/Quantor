"""ЭОМ и СС этажа (`cad_eom_route`): постановка по одобренному виду, обработчик, чтение 3D.

Как в тестах трасс механики: родитель `cad_pdf_convert` выставляется прямо в базе и хранилище, а
генератор подменён заглушкой, которая пишет файлы по CLI-контракту `cad_eom`. Отметка пола 88888 -
код выхода 3 («не построено»), 77777 - не хватает файла, остальное - успех.
"""

from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker import HANDLERS
from app.cad_worker.eom_handler import execute_cad_eom_route, generator_failure
from app.contracts.cad_eom import CadEomFileElement, element_out
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import ErrorCode
from app.main import create_app
from app.models import Job
from app.services import cad_eom as cad_eom_service
from app.services import cad_queue
from app.services import jobs as jobs_service
from tests.cad_pins_helper import _entry, write_pins
from tests.conftest import FakeObjectStorage, clean_settings, make_context
from tests.test_cad_mep import APPROVAL, FOLDER, PARAMS, _parent

EOM_PARAMS = {"holders_per_m": {"value": 3, "unit": "шт/м", "source": "assumed", "note": "тест"}}

STUB = """
import argparse, json, pathlib, sys

parser = argparse.ArgumentParser()
for name in ("pdf", "page-index", "view-dxf", "scale", "preview", "params", "out", "view-folder",
             "floor-elevation-mm", "floor-height-mm", "approval-id",
             "clear-height-mm", "slab-thickness-mm"):
    parser.add_argument("--" + name)
args = parser.parse_args()
for name in ("pdf", "view_dxf", "scale", "preview", "params"):
    if not pathlib.Path(getattr(args, name)).is_file():
        print(json.dumps({"code": "input_missing", "message": name}), file=sys.stderr)
        sys.exit(2)
elevation = 47600 if args.floor_elevation_mm is None else int(args.floor_elevation_mm)
height = 3300 if args.floor_height_mm is None else int(args.floor_height_mm)
if elevation == 88888:
    print(json.dumps({"code": "no_panels", "message": "Нет шахты ЭО"}), file=sys.stderr)
    sys.exit(3)
folder = pathlib.Path(args.out) / "views" / args.view_folder
folder.mkdir(parents=True)
(folder / "eom_routes.dxf").write_bytes(b"0\\nSECTION\\n9\\n$ACADVER\\n1\\nAC1032\\n0\\nEOF\\n")
(folder / "eom_routes3d.json").write_text(json.dumps({
    "schema": "cad_eom_routes3d.v1", "frame": "view_dxf_mm",
    "floor_elevation_mm": elevation, "floor_height_mm": height,
    "slab_bottom_mm": 3000, "ceiling_mm": 2700,
    "polylines": [
        {"layer": "E-EO-FEED", "pts": [[0, 0, 2880.4], [1000, 0, 2880]], "shape": "round",
         "dn_mm": 40, "w_mm": None, "h_mm": None, "item": "Труба ПВХ Ø40", "apt": "Кв 1"},
        {"layer": "E-SS-TRAY", "pts": [[0, 500, 2840], [1000, 500, 2840]], "shape": "rect",
         "dn_mm": None, "w_mm": 100, "h_mm": 50, "item": "Лоток СБ 100×50", "apt": None}],
    "elements": [
        {"type": "device", "subtype": "panel_floor", "layer": "E-EO-DEV",
         "pos": [0, 0, 1900], "axis": [0, 1, 0], "w_mm": 800, "h_mm": 1400, "d_mm": 160,
         "outer_d_mm": None, "length_mm": None, "name": "ЩЭ 1400×800", "apt": None},
        {"type": "sleeve", "subtype": "sleeve_32", "layer": "E-SS-DEV",
         "pos": [1000, 500, 2840], "axis": [1, 0, 0], "w_mm": None, "h_mm": None, "d_mm": None,
         "outer_d_mm": 32, "length_mm": 200, "name": "Гильза Ø32", "apt": "Кв 1"}]}))
if elevation != 77777:
    (folder / "eom_candidate.json").write_text(json.dumps({
        "schema": "quantor.cad_eom.candidate.v1", "status": "candidate_requires_review",
        "provenance": {"generator_version": "cad_eom.v0.1", "page_index": int(args.page_index)},
        "elevation": {"floor_elevation_mm": {"value": elevation, "source": "observed"},
                      "floor_height_mm": {"value": height, "source": "derived"}},
        "panels": [{"id": "ЩЭ-1"}], "apartments": [{"number": "Кв 1"}, {"number": "Кв 2"}],
        "quantities": [
            {"system": "ЭОМ: питающие линии", "item": "ППГнг(А)-HF 5×6", "unit": "м", "qty": 12.5,
             "route_m": 10.0, "formula": "(10 + 2×1,5) × 1,07", "source": "ИОС1.1 л.67"},
            {"system": "СС: трассы", "item": "Лоток СБ", "unit": "м", "qty": "много"}],
        "issues": [{"code": "tray_assumed", "message": "Сечение лотка условное"}]}))
"""


@pytest.fixture
def tools(tmp_path: Path) -> Path:
    """Каталог генераторов: заглушка `cad_eom` и параметры `cad_mep` (их пин нужен уровням)."""
    root = tmp_path / "generators"
    for name, params in (("cad_mep", PARAMS), ("cad_eom", EOM_PARAMS)):
        (root / name / "params").mkdir(parents=True)
        (root / name / "params" / "v1.json").write_text(json.dumps(params), encoding="utf-8")
    (root / "cad_eom" / "run_eom.py").write_text(STUB, encoding="utf-8")
    return root


def eom_settings(tools: Path, tmp_path: Path) -> Settings:
    pins = Path(write_pins(tmp_path, mep=tools / "cad_mep" / "params" / "v1.json"))
    data = json.loads(pins.read_text(encoding="utf-8"))
    data["generators"]["cad_eom"] = _entry(tools / "cad_eom" / "params" / "v1.json", "cad_eom.v0.1")
    pins.write_text(json.dumps(data), encoding="utf-8")
    return clean_settings(
        environment="test",
        feature_flags="cad.export=true",
        cad_engine_python=sys.executable,
        cad_eom_runner=str(tools / "cad_eom" / "run_eom.py"),
        cad_eom_params=str(tools / "cad_eom" / "params" / "v1.json"),
        cad_engine_pins=str(pins),
        cad_work_root=str(tmp_path / "work"),
        cad_total_timeout_seconds=60,
    )


async def _approve_and_queue_eom(
    api: AsyncClient, base: str, job_id: str, elevation: int = 47600
) -> str:
    view = f"{base}/{job_id}/views/0/1"
    assert (await api.post(f"{view}/approval", json=APPROVAL)).status_code == 201
    queued = await api.post(
        f"{view}/eom-routes",
        json={"attempt": 1, "floor_elevation_mm": elevation, "floor_height_mm": 3300},
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["status"] == "queued"
    return str(queued.json()["job_id"])


async def _run_eom_worker(
    session: AsyncSession, storage: FakeObjectStorage, settings: Settings, job_id: str
) -> Job:
    job = await jobs_service.claim(
        session, worker_id="cad-eom-test", job_types=[t.value for t in HANDLERS], lease_seconds=600
    )
    await session.commit()
    assert job is not None and str(job.id) == job_id
    handler = HANDLERS[job.job_type]
    assert handler is execute_cad_eom_route
    job = await handler(session, job, storage, settings)
    await session.commit()
    return job


# ------------------------------------------------------------------ без базы


def test_eom_routes_are_in_openapi_and_job_type_is_registered() -> None:
    paths = create_app(clean_settings()).openapi()["paths"]
    base = "/api/v1/projects/{project_id}/revisions/{revision_id}/cad/{job_id}"
    assert f"{base}/views/{{page_index}}/{{view}}/eom-routes" in paths
    assert "/api/v1/projects/{project_id}/cad/eom/routes3d" in paths
    assert "/api/v1/projects/{project_id}/cad/eom/job" in paths
    assert HANDLERS[JobType.CAD_EOM_ROUTE] is execute_cad_eom_route
    assert JobType.CAD_EOM_ROUTE in cad_queue.QUEUE_JOB_TYPES


def test_device_is_placed_at_its_box_centre_with_the_axis_scaled_like_mep() -> None:
    wall = CadEomFileElement.model_validate(
        {"type": "device", "subtype": "panel_shell", "layer": "E-EO-DEV", "pos": [100, 200, 1700],
         "axis": [0, 2, 0], "w_mm": 220, "h_mm": 300, "d_mm": 100}
    )
    out = element_out(wall)
    assert out.pos == (100, 250, 1700) and out.axis == (0, 1000, 0)
    ceiling = CadEomFileElement.model_validate(
        {"type": "device", "subtype": "light_temp", "layer": "E-EO-DEV", "pos": [0, 0, 3000],
         "axis": [0, 0, -1], "w_mm": 170, "h_mm": 170, "d_mm": 65}
    )
    assert element_out(ceiling).pos == (0, 0, 2968)
    sleeve = CadEomFileElement.model_validate(
        {"type": "sleeve", "subtype": "sleeve_50", "layer": "E-SS-RISER", "pos": [5, 5, 3100],
         "axis": [0, 0, 1], "outer_d_mm": 50, "length_mm": 200}
    )
    assert element_out(sleeve).pos == (5, 5, 3100), "у гильзы pos - центр, без сдвига"


def test_idempotency_key_changes_with_levels_and_version() -> None:
    approval = uuid.uuid4()

    def key(**changes: object) -> str:
        values: dict[str, object] = {
            "params_sha256": "a" * 64,
            "generator_version": "cad_eom.v0.1",
            "floor_elevation_mm": 47600,
            "floor_height_mm": 3300,
            "clear_height_mm": None,
            "slab_thickness_mm": None,
        } | changes
        return cad_eom_service.eom_idempotency_key(approval, **values)  # type: ignore[arg-type]

    base = key()
    assert base.startswith("cadeom:") and base == key()
    assert len({base, key(floor_height_mm=3000), key(slab_thickness_mm=250),
                key(generator_version="cad_eom.v0.2")}) == 4


def test_generator_exit_codes_map_to_eom_errors() -> None:
    line = json.dumps({"code": "no_panels", "message": "Нет шахты ЭО"}).encode()
    assert generator_failure(3, b"log\n" + line).code is ErrorCode.CAD_EOM_NOT_BUILT
    assert generator_failure(2, line).code is ErrorCode.CAD_INPUT_INVALID
    assert generator_failure(1, b"Traceback").code is ErrorCode.CAD_ENGINE_FAILED
    found = generator_failure(2, json.dumps({"code": "elevation_not_found"}).encode())
    assert found.code is ErrorCode.CAD_ELEVATION_NOT_FOUND


# ------------------------------------------------------------------ с базой


async def test_worker_builds_eom_and_the_sheet_reads_it_in_3d(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = eom_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        sheet = f"/api/v1/projects/{project_id}/cad/eom"
        query = {"revision_id": revision_id, "page_index": 0, "view": 1}
        none = await api.get(f"{sheet}/routes3d", params=query)
        assert none.status_code == 404 and none.json()["detail"]["code"] == "CAD_EOM_NOT_FOUND"

        eom_id = await _approve_and_queue_eom(api, base, job_id)
        queued = (await api.get(f"{sheet}/job", params=query)).json()
        assert queued["job_id"] == eom_id and queued["status"] == "queued"
        assert queued["generator_version"] == "cad_eom.v0.1"

        job = await _run_eom_worker(db_session, fake_storage, settings, eom_id)
        assert job.status is JobStatus.SUCCEEDED, (job.error_code, job.error_message)
        assert not any((tmp_path / "work").rglob("*")), "каталог попытки не удалён"
        names = {a["name"] for a in job.payload["cad_result"]["artifacts"]}
        assert names == {
            "report.json",
            "manifest.json",
            f"{FOLDER}/eom_routes3d.json",
            f"{FOLDER}/eom_candidate.json",
            f"{FOLDER}/eom_routes.dxf",
        }
        assert job.payload["cad_result"]["floor_elevation"]["value_mm"] == 47600

        read = await api.get(f"{sheet}/routes3d", params=query)
        assert read.status_code == 200, read.text
        data = read.json()
        assert data["job_id"] == eom_id and data["floor_height_mm"] == 3300
        feed, tray = data["polylines"]
        assert feed["layer"] == "E-EO-FEED" and feed["pts"][0] == [0, 0, 2880]
        assert feed["shape"] == "round" and feed["dn_mm"] == 40 and feed["apt"] == "Кв 1"
        assert tray["shape"] == "rect" and (tray["w_mm"], tray["h_mm"]) == (100, 50)
        panel, sleeve = data["elements"]
        assert panel["type"] == "device" and panel["pos"] == [0, 80, 1900]
        assert panel["axis"] == [0, 1000, 0] and panel["d_mm"] == 160
        assert sleeve["type"] == "sleeve" and sleeve["outer_d_mm"] == 32
        # строка ведомости с нечисловым количеством отбрасывается, остальные - как в файле
        [row] = data["quantities"]
        assert row["item"] == "ППГнг(А)-HF 5×6" and row["qty"] == 12.5 and row["route_m"] == 10.0
        assert data["apartments"] == 2 and data["issues"] == ["Сечение лотка условное"]
        done = (await api.get(f"{sheet}/job", params=query)).json()
        assert done["status"] == "succeeded"


@pytest.mark.parametrize(
    ("elevation", "error_code", "message"),
    [
        (88888, "CAD_EOM_NOT_BUILT", "Нет шахты ЭО"),
        (77777, "CAD_ENGINE_FAILED", "состав out/"),
    ],
)
async def test_failed_generator_publishes_nothing(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
    elevation: int,
    error_code: str,
    message: str,
) -> None:
    settings = eom_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        project_id, revision_id, job_id, base = await _parent(api, db_session, fake_storage)
        before = set(fake_storage.objects)
        eom_id = await _approve_and_queue_eom(api, base, job_id, elevation)
        job = await _run_eom_worker(db_session, fake_storage, settings, eom_id)
        assert job.status is JobStatus.FAILED
        assert job.error_code == error_code and message in (job.error_message or "")
        assert set(fake_storage.objects) == before, "неудачная попытка ничего не публикует"
        state = await api.get(
            f"/api/v1/projects/{project_id}/cad/eom/job",
            params={"revision_id": revision_id, "page_index": 0, "view": 1},
        )
        assert state.json()["status"] == "failed" and state.json()["error_code"] == error_code


async def test_eom_needs_the_approved_view(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    fake_storage: FakeObjectStorage,
    tools: Path,
    tmp_path: Path,
) -> None:
    settings = eom_settings(tools, tmp_path)
    async with build_api(make_context(), settings=settings) as api:
        _, _, job_id, base = await _parent(api, db_session, fake_storage)
        refused = await api.post(
            f"{base}/{job_id}/views/0/1/eom-routes",
            json={"attempt": 1, "floor_elevation_mm": 47600, "floor_height_mm": 3300},
        )
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "CAD_VIEW_NOT_APPROVED"
