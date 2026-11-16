"""Сопровождение пилота CAD (`app.services.cad_ops`): замечания и выгрузка задания для разбора.

Исполнитель не нужен: задания и их итоги кладутся прямо в базу и в хранилище в памяти так, как их
оставил бы исполнитель CAD (ключи артефактов — по контракту `artifact_storage_key`).
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.domain import DocumentKind, JobStatus, JobType
from app.models import CadRemark, Document, DocumentRevision, Job, Project
from app.services import cad as cad_service
from app.services import cad_ops, cad_risers
from tests.conftest import FakeObjectStorage

FOLDER = "views/p001_v01"
RISERS: list[dict[str, Any]] = [{"id": "Ст1", "system": "К1", "x_pt": 10.0, "y_pt": 20.0}]


def _artifact(
    storage: FakeObjectStorage, revision_id: uuid.UUID, job_id: uuid.UUID, name: str, data: bytes
) -> dict[str, Any]:
    key = cad_service.artifact_storage_key(revision_id, job_id, 1, name)
    storage.objects[key] = data
    return {"name": name, "key": key, "sha256": hashlib.sha256(data).hexdigest()}


async def _seed(
    session: AsyncSession, storage: FakeObjectStorage, workspace_id: uuid.UUID
) -> dict[str, Any]:
    project = Project(workspace_id=workspace_id, name="ЖК Тестовый")
    session.add(project)
    await session.flush()
    document = Document(project_id=project.id, display_name="АР", document_kind=DocumentKind.PDF)
    session.add(document)
    await session.flush()
    pdf = b"%PDF-1.7\n%test\n"
    revision = DocumentRevision(
        document_id=document.id,
        source_filename="АР1.1.pdf",
        source_mime="application/pdf",
        source_size=len(pdf),
        source_sha256=hashlib.sha256(pdf).hexdigest(),
        storage_key=f"test/{uuid.uuid4()}",
    )
    storage.objects[revision.storage_key] = pdf
    session.add(revision)
    await session.flush()

    parent_id, child_id = uuid.uuid4(), uuid.uuid4()
    parent_artifacts = [
        _artifact(storage, revision.id, parent_id, f"{FOLDER}/{name}", name.encode())
        for name in cad_ops.PARENT_VIEW_FILES
    ]
    child_artifacts = [
        _artifact(storage, revision.id, child_id, "report.json", b"{}"),
        _artifact(storage, revision.id, child_id, f"{FOLDER}/mep_routes.dxf", b"routes"),
        _artifact(storage, revision.id, child_id, f"{FOLDER}/routes3d.json", b'{"v":2}'),
    ]
    parent = Job(
        id=parent_id,
        workspace_id=workspace_id,
        project_id=project.id,
        job_type=JobType.CAD_PDF_CONVERT,
        status=JobStatus.SUCCEEDED,
        attempt=1,
        payload={
            "revision_id": str(revision.id),
            "cad_result": {"attempt": 1, "artifacts": parent_artifacts},
        },
    )
    child = Job(
        id=child_id,
        workspace_id=workspace_id,
        project_id=project.id,
        job_type=JobType.CAD_MEP_ROUTE,
        status=JobStatus.SUCCEEDED,
        attempt=1,
        payload={
            "revision_id": str(revision.id),
            "parent_job_id": str(parent_id),
            "parent_attempt": 1,
            "page_index": 0,
            "view": 1,
            "floor_elevation_mm": 42000,
            "floor_height_mm": None,
            "risers": RISERS,
            "risers_sha256": hashlib.sha256(cad_risers.registry_bytes(RISERS)).hexdigest(),
            "cad_result": {"attempt": 1, "artifacts": child_artifacts},
        },
    )
    session.add_all([parent, child])
    await session.flush()
    remarks = [
        CadRemark(
            workspace_id=workspace_id,
            project_id=project.id,
            revision_id=revision.id,
            job_id=child_id,
            attempt=1,
            page_index=0,
            view=1,
            remark_key=key,
            type="route",
            comment=comment,
            reviewer="Проверяющий",
            status=status,
            bbox_x0=10.0,
            bbox_y0=20.0,
            bbox_x1=110.0,
            bbox_y1=120.0,
        )
        for key, comment, status in (
            ("k-open", "Короба легли друг на друга", "open"),
            ("k-done", "Фреон сквозь короб", "resolved"),
        )
    ]
    session.add_all(remarks)
    await session.commit()
    return {"project": project, "revision": revision, "child": child, "remarks": remarks}


async def test_list_remarks_filters_and_describes_binding(
    db_session: AsyncSession, fake_storage: FakeObjectStorage, workspace_id: uuid.UUID
) -> None:
    seed = await _seed(db_session, fake_storage, workspace_id)

    open_only = await cad_ops.list_remarks(db_session, status="open")
    assert [row["remark_key"] for row in open_only] == ["k-open"]
    row = open_only[0]
    assert row["project_name"] == "ЖК Тестовый"
    assert row["revision_file"] == "АР1.1.pdf"
    assert row["job_type"] == "cad_mep_route"
    assert row["view_folder"] == FOLDER
    assert row["legacy_pdf_page"] == 1
    assert row["bbox_pt"] == [10.0, 20.0, 110.0, 120.0]
    assert row["stale"] is False

    every = await cad_ops.list_remarks(db_session, status=None, job_id=seed["child"].id)
    assert {row["remark_key"] for row in every} == {"k-open", "k-done"}
    assert await cad_ops.list_remarks(db_session, status=None, project_id=uuid.uuid4()) == []
    with pytest.raises(cad_ops.CadOpsError):
        await cad_ops.list_remarks(db_session, status="closed")


async def test_remark_on_recomputed_attempt_is_stale(
    db_session: AsyncSession, fake_storage: FakeObjectStorage, workspace_id: uuid.UUID
) -> None:
    seed = await _seed(db_session, fake_storage, workspace_id)
    payload = {**seed["child"].payload, "cad_result": {"attempt": 2, "artifacts": []}}
    await db_session.execute(update(Job).where(Job.id == seed["child"].id).values(payload=payload))
    await db_session.commit()

    (row,) = await cad_ops.list_remarks(db_session, status="open")
    assert row["result_attempt"] == 2
    assert row["stale"] is True


async def test_set_remark_status_changes_only_status(
    db_session: AsyncSession, fake_storage: FakeObjectStorage, workspace_id: uuid.UUID
) -> None:
    seed = await _seed(db_session, fake_storage, workspace_id)
    remark = seed["remarks"][0]

    view = await cad_ops.set_remark_status(db_session, remark_id=remark.id, status="resolved")
    await db_session.commit()
    assert view["status"] == "resolved"
    assert view["comment"] == "Короба легли друг на друга"
    assert view["reviewer"] == "Проверяющий"
    assert await cad_ops.list_remarks(db_session, status="open") == []

    with pytest.raises(cad_ops.CadOpsError):
        await cad_ops.set_remark_status(db_session, remark_id=uuid.uuid4(), status="open")
    with pytest.raises(cad_ops.CadOpsError):
        await cad_ops.set_remark_status(db_session, remark_id=remark.id, status="closed")


async def test_bundle_repeats_worker_layout(
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    tmp_path: Path,
) -> None:
    seed = await _seed(db_session, fake_storage, workspace_id)
    target = tmp_path / "bundle"
    target.mkdir()

    manifest = await cad_ops.build_bundle(
        db_session,
        fake_storage,
        job_id=seed["child"].id,
        attempt=None,
        include_pdf=True,
        target=target,
    )

    assert set(manifest["files"]) == {
        "out/report.json",
        f"out/{FOLDER}/mep_routes.dxf",
        f"out/{FOLDER}/routes3d.json",
        "in/source.pdf",
        "in/plan_candidates.dxf",
        "in/scale.json",
        "in/preview.json",
        "in/risers.json",
    }
    assert (target / "in" / "scale.json").read_bytes() == b"scale.json"
    assert (target / "out" / "views" / "p001_v01" / "mep_routes.dxf").read_bytes() == b"routes"
    risers = json.loads((target / "in" / "risers.json").read_bytes())
    assert risers == {"schema": "cad_risers.v1", "risers": RISERS}
    assert manifest["generator_flags"] == ["--floor-elevation-mm", "42000"]
    assert manifest["parent"]["view_folder"] == FOLDER
    assert manifest["job"]["bundle_attempt"] == 1
    assert manifest["remarks"] == 2
    saved = json.loads((target / "job.json").read_text(encoding="utf-8"))
    assert saved["revision"]["file"] == "АР1.1.pdf"
    remarks = json.loads((target / "remarks.json").read_text(encoding="utf-8"))
    assert {row["remark_key"] for row in remarks["remarks"]} == {"k-open", "k-done"}


async def test_bundle_without_pdf_and_rejects_tampered_artifact(
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    tmp_path: Path,
) -> None:
    seed = await _seed(db_session, fake_storage, workspace_id)
    first = tmp_path / "first"
    first.mkdir()
    manifest = await cad_ops.build_bundle(
        db_session,
        fake_storage,
        job_id=seed["child"].id,
        attempt=1,
        include_pdf=False,
        target=first,
    )
    assert "in/source.pdf" not in manifest["files"]

    key = cad_service.artifact_storage_key(
        seed["revision"].id, seed["child"].id, 1, f"{FOLDER}/mep_routes.dxf"
    )
    fake_storage.objects[key] = b"tampered"
    second = tmp_path / "second"
    second.mkdir()
    with pytest.raises(cad_ops.CadOpsError, match="SHA256"):
        await cad_ops.build_bundle(
            db_session,
            fake_storage,
            job_id=seed["child"].id,
            attempt=None,
            include_pdf=False,
            target=second,
        )


async def test_bundle_refuses_unknown_job_and_missing_attempt(
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    tmp_path: Path,
) -> None:
    seed = await _seed(db_session, fake_storage, workspace_id)
    with pytest.raises(cad_ops.CadOpsError, match="не найдено"):
        await cad_ops.build_bundle(
            db_session,
            fake_storage,
            job_id=uuid.uuid4(),
            attempt=None,
            include_pdf=False,
            target=tmp_path,
        )
    with pytest.raises(cad_ops.CadOpsError, match="попытки 5"):
        await cad_ops.build_bundle(
            db_session,
            fake_storage,
            job_id=seed["child"].id,
            attempt=5,
            include_pdf=False,
            target=tmp_path,
        )


class _SessionScope:
    """Фабрика сессий CLI, отдающая сессию теста (без закрытия: её закроет фикстура)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *exc: object) -> None:
        return None


async def test_cli_bundle_packs_archive(
    db_session: AsyncSession,
    fake_storage: FakeObjectStorage,
    workspace_id: uuid.UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await _seed(db_session, fake_storage, workspace_id)

    async def _no_dispose() -> None:
        return None

    monkeypatch.setattr(cli, "get_session_factory", lambda: lambda: _SessionScope(db_session))
    monkeypatch.setattr(cli, "dispose_engine", _no_dispose)
    monkeypatch.setattr(cli, "S3ObjectStorage", lambda _settings: fake_storage)
    archive = tmp_path / "bundle.tar.gz"

    await cli._cad_bundle(seed["child"].id, None, False, str(archive))

    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
        job = tar.extractfile("job.json")
        assert job is not None
        manifest = json.loads(job.read())
    assert {"job.json", "remarks.json", "in/risers.json", f"out/{FOLDER}/mep_routes.dxf"} <= names
    assert manifest["job"]["id"] == str(seed["child"].id)


def test_cli_rejects_bad_arguments() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["cad-remark-status", "not-a-uuid", "resolved"])
    assert exit_info.value.code == 2
    with pytest.raises(SystemExit):
        cli.main(["cad-remark-status", str(uuid.uuid4()), "closed"])
    with pytest.raises(SystemExit):
        cli.main(["cad-bundle", "not-a-uuid"])
