"""Сбор фактов из распознанного пакета через API (ADR-0030, PROMPT 02).

Ревизии и блоки создаются так же, как их оставляет импорт legacy-v1: производная PDF-ревизия
с `package_format` в метаданных, листы, текстовые блоки с `raw_content_md`. Распознавание не
запускается и не меняется — адаптеры читают готовый текст.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.domain import DocumentKind, GeometryStatus, OverrideScope, ProcessingStatus, Role
from app.models import (
    CalcFactEvidence,
    Document,
    DocumentRevision,
    FeatureFlagOverride,
    Project,
    Region,
    Sheet,
)
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services.calc.facts import registry
from tests.conftest import make_context
from tests.test_calc_adapters import APARTMENTS_A, APARTMENTS_B, COMMON_AREAS, NOTE, STAMP

API = "/api/v1/calc"
PACKAGE = {"package_format": "recognized-package/legacy-v1", "schema_version": 1}

VOR = """### Водопровод хозяйственно-питьевой В1
| № | Наименование | Ед. изм. | Количество |
| --- | --- | --- | --- |
| 1 | Трубопровод В1 из PP-R Ø50 | м | 1280 |
| 2 | Стояк К1 канализации Ø110 | м | 320 |
"""


@pytest.fixture
async def calc_enabled(db_session: AsyncSession) -> None:
    db_session.add(
        FeatureFlagOverride(
            flag_key="calc.portal",
            scope=OverrideScope.SYSTEM,
            workspace_id=None,
            enabled=True,
            reason="тесты сбора фактов",
        )
    )
    await db_session.commit()


def _as(role: Role, workspace_id: uuid.UUID) -> AuthContext:
    return make_context(role, workspace_id=workspace_id)


async def _project(session: AsyncSession, workspace_id: uuid.UUID) -> Project:
    project = await projects_service.create_project(session, workspace_id=workspace_id, name="ЖК")
    await session.commit()
    return project


async def _revision(
    session: AsyncSession,
    document: Document,
    *,
    sha: str,
    metadata: dict[str, object] | None = None,
) -> DocumentRevision:
    return await documents_service.create_revision(
        session,
        document=document,
        revision_id=uuid.uuid4(),
        source_filename=document.display_name,
        source_mime="application/pdf",
        source_size=1024,
        source_sha256=sha,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        processing_status=ProcessingStatus.READY,
        source_metadata=metadata,
        geometry_status=GeometryStatus.READY,
    )


async def _recognized(
    session: AsyncSession,
    project: Project,
    pages: list[list[str]],
    *,
    title: str = "АР.pdf",
    sha: str = "a" * 64,
    origin: uuid.UUID | None = None,
) -> DocumentRevision:
    """Производная ревизия распознанного пакета: листы и текстовые блоки."""
    document = Document(project_id=project.id, display_name=title, document_kind=DocumentKind.PDF)
    session.add(document)
    await session.flush()
    metadata: dict[str, object] = dict(PACKAGE)
    if origin is not None:
        metadata["imported_from_revision_id"] = str(origin)
    revision = await _revision(session, document, sha=sha, metadata=metadata)
    for page_index, blocks in enumerate(pages):
        sheet = Sheet(
            revision_id=revision.id, page_index=page_index, page_label=str(page_index + 1)
        )
        session.add(sheet)
        await session.flush()
        for ordinal, text in enumerate(blocks, start=1):
            session.add(
                Region(
                    sheet_id=sheet.id,
                    external_block_id=f"blk_{page_index}_{ordinal}",
                    ordinal=ordinal,
                    block_type="text",
                    shape_type="rectangle",
                    coords_norm=[0.1, 0.1, 0.6, 0.5],
                    recognition_status="recognized",
                    raw_content_md=text,
                )
            )
    await session.commit()
    return revision


async def _collect(
    client: AsyncClient, project: Project, revision: DocumentRevision, **body: Any
) -> Response:
    payload = {
        "document_revision_id": str(revision.id),
        "source_class": "ARCHITECTURE",
        "document_stage": "P",
        "building": "1",
        **body,
    }
    return await client.post(f"{API}/projects/{project.id}/inspections", json=payload)


def _row(readiness: dict[str, Any], system: str, requirement: str) -> dict[str, Any]:
    matrix = next(item for item in readiness["systems"] if item["system_code"] == system)
    row: dict[str, Any] = next(
        item for item in matrix["rows"] if item["requirement_id"] == requirement
    )
    return row


@pytest.mark.usefixtures("calc_enabled")
class TestCollection:
    async def test_candidates_become_claims_with_region_evidence(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        revision = await _recognized(
            db_session, project, [[APARTMENTS_A, APARTMENTS_B], [COMMON_AREAS]]
        )
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await _collect(client, project, revision)
            facts = (
                await client.get(
                    f"{API}/projects/{project.id}/facts",
                    params={"fact_type": "floor.apartments_count"},
                )
            ).json()
            sources = (await client.get(f"{API}/projects/{project.id}/sources")).json()

        assert response.status_code == 201, response.text
        inspection = response.json()
        summary = inspection["summary"]
        assert summary["accepted"] == summary["created"] > 0
        assert (summary["stamp_stage"], summary["stamp_section"]) == ("P", "АР")
        assert summary["stage_basis"] == "DECLARED"
        [fact] = facts
        assert fact["value"] == {"kind": "COUNT", "value": 4, "unit": "apartment"}
        assert fact["method"] == "TABLE_COUNTED"
        assert fact["source_class"] == "APARTMENT_SCHEDULE"
        assert fact["inspection_id"] == inspection["id"]
        assert fact["note"].startswith("Подсчитаны строки «Квартира №»")
        assert {item["kind"] for item in fact["evidence"]} == {"REGION_TABLE"}
        for item in fact["evidence"]:
            assert item["document_revision_id"] == str(revision.id)
            assert len(item["region_sha256"]) == 64
            assert item["region_locator"]["kind"] == "TABLE"
            assert item["region_locator"]["rows"]
        adapter = [s for s in sources if (s["series_key"] or "").startswith("calc:recognized:")]
        assert adapter
        assert {s["content_sha256"] for s in adapter} == {revision.source_sha256}

    async def test_second_collection_changes_nothing(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        revision = await _recognized(db_session, project, [[APARTMENTS_A, APARTMENTS_B]])
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            first = (await _collect(client, project, revision)).json()["summary"]
            second = (await _collect(client, project, revision)).json()["summary"]
            facts = (await client.get(f"{API}/projects/{project.id}/facts")).json()
        assert second["created"] == 0
        assert second["unchanged"] == first["created"]
        assert second["withdrawn"] == 0
        assert {fact["version"] for fact in facts} == {1}

    async def test_same_file_is_one_confirmation_another_file_corroborates(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        pages = [[APARTMENTS_A, APARTMENTS_B]]
        original = await _recognized(db_session, project, pages, title="АР.pdf", sha="5" * 64)
        same_file = await _recognized(
            db_session, project, pages, title="АР-копия.pdf", sha="5" * 64
        )
        other_file = await _recognized(db_session, project, pages, title="АР-изм.pdf", sha="6" * 64)
        key = "floor.apartments_count@building=1|floor=3"
        states = []
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            for revision in (original, same_file, other_file):
                assert (await _collect(client, project, revision)).status_code == 201
                values = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()
                states.append(next(item["state"] for item in values if item["fact_key"] == key))
        assert states == ["SINGLE", "SINGLE", "CORROBORATED"]

    async def test_documents_disagree_and_the_decision_survives_recollection(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        full = await _recognized(
            db_session, project, [[APARTMENTS_A, APARTMENTS_B]], title="АР-1.pdf", sha="1" * 64
        )
        partial = await _recognized(
            db_session, project, [[APARTMENTS_A]], title="АР-2.pdf", sha="2" * 64
        )
        key = "floor.apartments_count@building=1|floor=3"
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _collect(client, project, full)
            await _collect(client, project, partial)
            conflicts = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
        conflict = next(item for item in conflicts if item["fact_key"] == key)
        assert conflict["status"] == "OPEN"
        chosen = next(claim for claim in conflict["claims"] if claim["value"]["value"] == 4)

        async with build_api(_as(Role.REVIEWER, workspace_id)) as client:
            decided = await client.post(
                f"{API}/conflicts/{conflict['id']}/decision",
                json={"chosen_fact_id": chosen["id"], "reason": "Во втором альбоме не все листы"},
            )
        assert decided.status_code == 201, decided.text

        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            again = (await _collect(client, project, full)).json()["summary"]
            values = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()
            [after] = [
                item
                for item in (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
                if item["fact_key"] == key
            ]
        assert again["created"] == 0
        assert after["status"] == "RESOLVED"
        value = next(item for item in values if item["fact_key"] == key)
        assert (value["state"], value["value"]["value"]) == ("DECIDED", 4)


@pytest.mark.usefixtures("calc_enabled")
class TestReadiness:
    async def test_missing_only_after_every_document_is_inspected(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        plan = await _recognized(
            db_session, project, [[APARTMENTS_A, APARTMENTS_B]], title="АР.pdf", sha="3" * 64
        )
        note = await _recognized(
            db_session, project, [["Общие указания без чисел.\n"]], title="ПЗ.pdf", sha="4" * 64
        )
        readiness_url = f"{API}/projects/{project.id}/readiness"
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            before = (await client.get(readiness_url)).json()
            await _collect(client, project, plan)
            middle = (await client.get(readiness_url)).json()
            await _collect(client, project, note, source_class="EXPLANATORY_NOTE")
            after = (await client.get(readiness_url)).json()

        per_floor = "vk.apartments.per_floor"
        assert _row(before, "В1", per_floor)["status"] == "NOT_INSPECTED"
        assert _row(before, "В1", per_floor)["reason"] == "Не проверено документов: 2 из 2"
        assert _row(middle, "В1", per_floor)["status"] == "FOUND"
        # Этажность могла бы быть в записке, а её ещё не смотрели: это не «не найдено».
        assert _row(middle, "В1", "vk.building.floors_above")["status"] == "NOT_INSPECTED"
        floors = _row(after, "В1", "vk.building.floors_above")
        assert floors["status"] == "MISSING"
        assert floors["reason"] == "Проверено документов: 2 — не найдено"
        assert floors["values"] == []
        assert _row(after, "В1", "vk.b1.inlet_pressure")["status"] == "MANUAL_REQUIRED"
        assert _row(after, "Т3", "vk.t3.source")["status"] == "MANUAL_REQUIRED"
        assert after["documents"] == {
            "recognized": 2,
            "inspected": 2,
            "not_inspected": 0,
            "without_recognition": 0,
        }
        counts = next(item for item in after["systems"] if item["system_code"] == "В1")["counts"]
        required = next(item for item in counts if item["level"] == "REQUIRED")
        assert 0 < required["satisfied"] < required["total"]

        # Отсутствующее значение не становится нулём и в снимке для ядра.
        snapshot = await registry.calculation_snapshot(db_session, project_id=project.id)
        assert not [item for item in snapshot.items if item.fact_type.startswith("building.floors")]

    async def test_filters_narrow_rows_not_counts(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            full = (await client.get(f"{API}/projects/{project.id}/readiness")).json()
            narrow = (
                await client.get(
                    f"{API}/projects/{project.id}/readiness",
                    params={"system": "b1", "level": "REQUIRED"},
                )
            ).json()
        [matrix] = narrow["systems"]
        assert matrix["system_code"] == "В1"
        assert {row["level"] for row in matrix["rows"]} == {"REQUIRED"}
        full_b1 = next(item for item in full["systems"] if item["system_code"] == "В1")
        assert matrix["counts"] == full_b1["counts"]


@pytest.mark.usefixtures("calc_enabled")
class TestCustomerVor:
    async def test_vor_quantities_and_diameters_never_reach_the_calculation(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        vor = await _recognized(db_session, project, [[VOR]], title="ВОР.pdf", sha="7" * 64)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await _collect(client, project, vor, source_class="CUSTOMER_VOR")
            facts = (await client.get(f"{API}/projects/{project.id}/facts")).json()
            readiness = (await client.get(f"{API}/projects/{project.id}/readiness")).json()
            rows = (await client.get(f"{API}/projects/{project.id}/input-facts")).json()

        assert response.status_code == 201, response.text
        issues = {item["code"]: item["count"] for item in response.json()["summary"]["issues"]}
        assert issues["VOR_QUANTITY_IGNORED"] == 2
        assert issues["VOR_DIAMETER_IGNORED"] == 2
        assert {fact["fact_type"] for fact in facts} == {"system.present"}
        assert {fact["subject"]["system_code"] for fact in facts} == {"В1", "К1"}
        assert all(fact["calculation_eligible"] is False for fact in facts)
        stated = {str(fact["stated_value"].get("value")) for fact in facts}
        assert not stated & {"1280", "320", "50", "110"}

        # Диаметр ВОР не навязывает расчётный: требования диаметров не закрыты.
        diameter = _row(readiness, "В1", "vk.water.main_diameter")
        assert diameter["status"] != "FOUND" and diameter["values"] == []
        present = _row(readiness, "В1", "vk.water.present")
        assert present["status"] != "FOUND"
        assert present["excluded_count"] == 1
        assert {row["usage"] for row in rows["items"]} == {"EXCLUDED_VOR"}

        snapshot = await registry.calculation_snapshot(db_session, project_id=project.id)
        assert snapshot.items == ()


@pytest.mark.usefixtures("calc_enabled")
class TestRules:
    async def test_revision_without_recognition_is_refused(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        document = Document(
            project_id=project.id, display_name="Сырой.pdf", document_kind=DocumentKind.PDF
        )
        db_session.add(document)
        await db_session.flush()
        raw = await _revision(db_session, document, sha="8" * 64)
        await db_session.commit()
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await _collect(client, project, raw)
            listed = (await client.get(f"{API}/projects/{project.id}/documents")).json()
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "CALC_DOCUMENT_NOT_RECOGNIZED"
        [document_row] = listed
        assert document_row["recognized"] is False

    async def test_only_the_latest_revision_and_older_claims_retire(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        package = Document(
            project_id=project.id,
            display_name="Пакет АР.zip",
            document_kind=DocumentKind.RECOGNIZED_PACKAGE,
        )
        db_session.add(package)
        await db_session.flush()
        first_package = await _revision(db_session, package, sha="9" * 64)
        await db_session.commit()
        first = await _recognized(
            db_session, project, [[APARTMENTS_A]], sha="b" * 64, origin=first_package.id
        )
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            assert (await _collect(client, project, first)).status_code == 201

        second_package = await _revision(db_session, package, sha="d" * 64)
        await db_session.commit()
        second = await _recognized(
            db_session,
            project,
            [[APARTMENTS_A, APARTMENTS_B]],
            sha="e" * 64,
            origin=second_package.id,
        )
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            stale = await _collect(client, project, first)
            fresh = await _collect(client, project, second)
            facts = (await client.get(f"{API}/projects/{project.id}/facts")).json()
            documents = (await client.get(f"{API}/projects/{project.id}/documents")).json()
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "CALC_REVISION_NOT_LATEST"
        assert fresh.status_code == 201, fresh.text
        old = [fact for fact in facts if fact["inspection_id"] != fresh.json()["id"]]
        assert old and {fact["status"] for fact in old} == {"WITHDRAWN"}
        assert {fact["withdrawn_reason"] for fact in old} == {"Заменено новой ревизией документа"}
        latest = {item["document_revision_id"]: item["latest"] for item in documents}
        assert latest == {str(first.id): False, str(second.id): True}

    async def test_documents_list_suggests_the_declaration_from_the_stamp(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        revision = await _recognized(db_session, project, [[APARTMENTS_A]])
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            before = (await client.get(f"{API}/projects/{project.id}/documents")).json()
            await _collect(client, project, revision, document_stage="RD")
            after = (await client.get(f"{API}/projects/{project.id}/documents")).json()
        [row] = before
        assert (row["stamp_stage"], row["stamp_section"]) == ("P", "АР")
        assert row["suggested_class"] == "ARCHITECTURE"
        assert row["last_inspection"] is None
        [collected] = after
        assert collected["inspection_current"] is True
        # Заявлено вопреки штампу — это видно, а не исправлено молча.
        assert collected["last_inspection"]["summary"]["stage_basis"] == "DECLARED_OVER_STAMP"

    async def test_collected_sources_are_not_for_manual_input(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        revision = await _recognized(db_session, project, [[APARTMENTS_A]])
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _collect(client, project, revision)
            sources = (await client.get(f"{API}/projects/{project.id}/sources")).json()
            [adapter] = [
                s for s in sources if s["series_key"] == "calc:recognized:apartment_explication"
            ]
            manual = (
                await client.post(
                    f"{API}/projects/{project.id}/sources",
                    json={"source_class": "MANUAL", "title": "Инженер"},
                )
            ).json()
            body = {
                "fact_type": "floor.apartments_count",
                "subject": {"building": "1", "floor": "3"},
                "value": {"kind": "COUNT", "value": 7},
            }
            forged = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={**body, "source_id": adapter["id"], "method": "MANUAL", "note": "по листу"},
            )
            counted = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={**body, "source_id": manual["id"], "method": "TABLE_COUNTED"},
            )
        assert forged.json()["detail"]["code"] == "CALC_SOURCE_NOT_ALLOWED"
        assert counted.json()["detail"]["code"] == "CALC_METHOD_NOT_AVAILABLE"

    async def test_input_facts_say_what_goes_to_the_calculation(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        revision = await _recognized(db_session, project, [[STAMP + NOTE, APARTMENTS_A]])
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _collect(client, project, revision)
            manual = (
                await client.post(
                    f"{API}/projects/{project.id}/sources",
                    json={"source_class": "MANUAL", "title": "Инженер"},
                )
            ).json()
            await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    "source_id": manual["id"],
                    "fact_type": "floor.apartments_count",
                    "subject": {"building": "1", "floor": "3"},
                    "value": {"kind": "COUNT", "value": 3},
                    "method": "MANUAL",
                    "note": "по листу проекта",
                },
            )
            page = (
                await client.get(
                    f"{API}/projects/{project.id}/input-facts",
                    params={"fact_type": "floor.apartments_count"},
                )
            ).json()
        usage = {row["fact"]["source_class"]: row["usage"] for row in page["items"]}
        # Квартирография сильнее ручного ввода по политике — ручное значение не выбрано.
        assert usage == {"APARTMENT_SCHEDULE": "USED", "MANUAL": "NOT_CHOSEN"}
        assert page["total"] == 2
        assert all(row["fact_type_title"] == "Квартир на этаже" for row in page["items"])

    async def test_region_evidence_cannot_lose_its_region(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        revision = await _recognized(db_session, project, [[APARTMENTS_A]])
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _collect(client, project, revision)
        with pytest.raises(IntegrityError):
            await db_session.execute(
                update(CalcFactEvidence)
                .where(CalcFactEvidence.kind == "REGION_TABLE")
                .values(region_id=None)
            )
            await db_session.flush()
        await db_session.rollback()


class TestAccess:
    async def test_closed_flag_closes_the_new_routes(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.get(f"{API}/projects/{project.id}/readiness")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"

    @pytest.mark.usefixtures("calc_enabled")
    async def test_viewer_reads_but_does_not_collect(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        revision = await _recognized(db_session, project, [[APARTMENTS_A]])
        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            readiness = await client.get(f"{API}/projects/{project.id}/readiness")
            catalog = await client.get(f"{API}/requirements")
            collected = await _collect(client, project, revision)
        assert readiness.status_code == 200
        assert catalog.status_code == 200
        assert {item["code"] for item in catalog.json()["systems"]} == {"В1", "Т3", "Т4", "К1"}
        assert collected.status_code == 403
