"""Рабочий калькулятор ВК через базу и HTTP (ADR-0030, PROMPT 06).

Настоящий путь: факты — через API реестра фактов или сбором из синтетического распознанного
документа; правила — шаблоны заявок, утверждённые вторым пользователем; комплект ВК — через
API; паспорт, объёмы, объяснение — через API. Проверяются автоматические исходные данные,
конфликты, независимость от ВОР, объяснение до свидетельства, воспроизводимость, назначение
систем, идемпотентность, изоляция и неизменяемость.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import DocumentKind, GeometryStatus, OverrideScope, ProcessingStatus, Role
from app.models import (
    CalcExpectedQuantity,
    CalcPassport,
    CalcRun,
    Document,
    FeatureFlagOverride,
    UserIdentity,
    Workspace,
)
from app.services import documents as documents_service
from app.services import projects as projects_service
from tests.calc_vk_fixtures import API, APPROVE, Building, VkProject, _as, content_for
from tests.test_calc_inspections_api import _collect, _recognized

NOTE = """Этажность здания — 24 этажа.
Высота 1 этажа — 4,2 м.
Высота этажей со 2 по 24 — 3000 мм.
В1 — водопровод хозяйственно-питьевой
Т3 — водопровод горячей воды подающий
Т4 — трубопровод горячей воды циркуляционный
К1 — канализация бытовая
"""


@pytest.fixture
async def calc_enabled(db_session: AsyncSession) -> None:
    db_session.add(
        FeatureFlagOverride(
            flag_key="calc.portal",
            scope=OverrideScope.SYSTEM,
            workspace_id=None,
            enabled=True,
            reason="тесты калькулятора ВК",
        )
    )
    await db_session.commit()


@pytest.fixture
async def vk(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    other_user: UserIdentity,
    calc_enabled: None,
) -> VkProject:
    project = await projects_service.create_project(
        db_session, workspace_id=workspace_id, name="ЖК синтетический"
    )
    await db_session.commit()
    return VkProject(build_api, workspace_id, other_user.id, project)


def _volume(volumes: dict[str, dict[str, Any]], key: str) -> dict[str, Any]:
    return volumes[key]


async def _vor(session: AsyncSession, vk: VkProject) -> str:
    """Источник ВОР Заказчика с ревизией документа — как его заводит сбор фактов."""
    document = Document(
        project_id=vk.project.id, display_name="ВОР.pdf", document_kind=DocumentKind.PDF
    )
    session.add(document)
    await session.flush()
    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=uuid.uuid4(),
        source_filename="ВОР.pdf",
        source_mime="application/pdf",
        source_size=1024,
        source_sha256="f" * 64,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        processing_status=ProcessingStatus.READY,
        geometry_status=GeometryStatus.READY,
    )
    await session.commit()
    async with vk.engineer() as client:
        source = await client.post(
            f"{API}/projects/{vk.project.id}/sources",
            json={
                "source_class": "CUSTOMER_VOR",
                "title": "ВОР Заказчика",
                "document_revision_id": str(revision.id),
            },
        )
    assert source.status_code == 201, source.text
    return str(revision.id) + "|" + str(source.json()["id"])


async def _vor_fact(vk: VkProject, handle: str, fact_type: str, value: dict[str, object]) -> int:
    revision_id, source_id = handle.split("|")
    async with vk.engineer() as client:
        response = await client.post(
            f"{API}/projects/{vk.project.id}/facts",
            json={
                "source_id": source_id,
                "fact_type": fact_type,
                "subject": {"building": "1", "discipline": "VK", "system_code": "В1"},
                "value": value,
                "method": "TABLE_EXPLICIT",
                "evidence": [{"kind": "DOCUMENT_FRAGMENT", "document_revision_id": revision_id}],
            },
        )
    return response.status_code


def _hashes(batch: dict[str, Any]) -> dict[str, str]:
    return {item["system_code"]: item["passport_sha256"] for item in batch["passports"]}


class TestInputs:
    async def test_t01_t02_document_facts_are_used_and_not_asked_again(
        self, db_session: AsyncSession, vk: VkProject
    ) -> None:
        revision = await _recognized(db_session, vk.project, [[NOTE]], title="ПЗ.pdf")
        async with vk.engineer() as client:
            collected = await _collect(
                client, vk.project, revision, source_class="EXPLANATORY_NOTE"
            )
        assert collected.status_code == 201, collected.text
        await vk.count("floor.apartments_count", {"building": "1", "floor": "1"}, 0)
        await vk.count("floor.apartments_count", {"building": "1", "floor": "2..24"}, 6)
        readiness = await vk.get(f"/projects/{vk.project.id}/vk/readiness", building="1")
        b1 = next(item for item in readiness["systems"] if item["system_code"] == "В1")
        assert b1["semantics"] == "CONFIRMED"
        assert b1["inputs"]["found_auto"] >= 3
        assert b1["inputs"]["required_satisfied"] == b1["inputs"]["required_total"]
        missing = {item["requirement_id"] for item in b1["missing"]}
        assert not missing & {"vk.building.floors_above", "vk.floor.height", "vk.system.function"}
        batch = await vk.calculate()
        passport = await vk.passport(batch, "В1")
        used = {item["fact_key"]: item for item in passport["body"]["used_facts"]}
        documented = [item for item in used.values() if item["source"] == "EXPLANATORY_NOTE"]
        assert {item["method"] for item in documented} == {"DOCUMENT_EXPLICIT"}
        assert any(key.startswith("floor.height@") for key in used)
        calculation = {item["key"]: item for item in passport["body"]["calculation"]}
        assert calculation["structure.interfloor_length"]["amount"]["value"] == "70.2"

    async def test_t03_t04_conflict_blocks_dependent_part_only(self, vk: VkProject) -> None:
        await vk.building(Building())
        await vk.rules("В1")
        source = await vk.source("MANUAL", "Второй инженер")
        async with vk.engineer() as client:
            response = await client.post(
                f"{API}/projects/{vk.project.id}/facts",
                json={
                    "source_id": source,
                    "fact_type": "floor.height",
                    "subject": {"building": "1", "floor": "2..24"},
                    "value": {"kind": "NUMBER", "value": "3.3", "unit": "m"},
                    "method": "MANUAL",
                    "note": "по листу проекта",
                },
            )
        assert response.status_code == 201, response.text
        batch = await vk.calculate(systems=["В1"])
        passport = await vk.passport(batch, "В1")
        assert passport["status"] == "PARTIAL"
        conflicts = [item["fact_key"] for item in passport["body"]["conflicts"]]
        assert any(key.startswith("floor.height@") for key in conflicts)
        volumes = await vk.volumes(passport, "EXPECTED")
        assert _volume(volumes, "vk.b1.pipe.riser")["completeness"] == "BLOCKED"
        assert _volume(volumes, "vk.b1.connection.floor")["completeness"] == "RANGE"
        issue = next(
            item
            for item in passport["body"]["unresolved"]
            if item["key"] == "step:structure_vertical"
        )
        assert "Трубы стояков" in issue["blocks"]
        assert "Этажные подключения" in issue["not_blocks"]

    async def test_t05_blocked_quantity_has_no_number_in_storage(
        self, db_session: AsyncSession, vk: VkProject
    ) -> None:
        await vk.building(Building())
        await vk.calculate(systems=["В1"])
        rows = (await db_session.scalars(select(CalcExpectedQuantity))).all()
        blocked = [row for row in rows if row.completeness.value == "BLOCKED"]
        assert blocked
        assert all(row.value is None and row.low is None for row in blocked)


class TestVorIndependence:
    async def test_t06_t30_t31_t32_customer_vor_changes_nothing(
        self, db_session: AsyncSession, vk: VkProject
    ) -> None:
        await vk.building(Building())
        await vk.rules("В1")
        before = await vk.calculate(systems=["В1"])
        handle = await _vor(db_session, vk)
        assert (
            await _vor_fact(vk, handle, "system.risers_count", {"kind": "COUNT", "value": 9}) == 422
        )
        assert (
            await _vor_fact(
                vk, handle, "system.riser_diameter", {"kind": "NUMBER", "value": "50", "unit": "mm"}
            )
            == 422
        )
        assert (
            await _vor_fact(vk, handle, "system.pipe_material", {"kind": "TEXT", "value": "PP-R"})
            == 201
        )
        after = await vk.calculate(systems=["В1"])
        assert _hashes(after) == _hashes(before)
        passport = await vk.passport(after, "В1")
        assert all(item["source"] != "CUSTOMER_VOR" for item in passport["body"]["used_facts"])
        volumes = await vk.volumes(passport, "EXPECTED")
        assert all(row["material"] is None for row in volumes.values())
        runs = (await db_session.scalars(select(CalcRun))).all()
        for run in runs:
            assert all(item["source_class"] != "CUSTOMER_VOR" for item in run.snapshot["items"])


class TestTrace:
    async def test_t25_t29_quantity_leads_to_evidence_and_assumption(self, vk: VkProject) -> None:
        await vk.building(Building())
        await vk.rules("В1", tender=True)
        passport = await vk.passport(await vk.calculate(systems=["В1"]), "В1")
        riser = _volume(await vk.volumes(passport, "TENDER_SAFE"), "vk.b1.pipe.riser")
        trace = await vk.get(f"/vk/volumes/{riser['id']}/trace")
        root = trace["root"]
        kinds = [child["kind"] for child in root["children"]]
        assert "ASSUMPTION" in kinds
        element = next(child for child in root["children"] if child["kind"] == "ELEMENT")
        result = next(
            child for child in element["children"] if child["kind"] == "CALCULATION_RESULT"
        )
        chain = result["calculation"]["root"]
        assert chain["kind"] == "RESULT"

        def walk(node: dict[str, Any]) -> list[str]:
            return [node["kind"], *(kind for child in node["children"] for kind in walk(child))]

        found = walk(chain)
        assert {"STEP", "RULE", "FACT", "EVIDENCE", "PRIMITIVE"} <= set(found)
        assumptions = await vk.get(f"/vk/passports/{passport['id']}/assumptions")
        applied = [item for item in assumptions if item["applied"]]
        assert [item["rule_key"] for item in applied] == ["vk.tender.riser_length_reserve"]
        assert all(not item["applied"] for item in assumptions if item not in applied)


class TestReproducibility:
    async def test_t33_t34_t35_same_snapshot_same_result_change_new_run(
        self, db_session: AsyncSession, vk: VkProject
    ) -> None:
        await vk.building(Building())
        await vk.rules("В1")
        first = await vk.calculate(systems=["В1"])
        second = await vk.calculate(systems=["В1"])
        assert _hashes(first) == _hashes(second)
        assert first["batch_id"] != second["batch_id"]
        passport = await vk.passport(first, "В1")
        await vk.count(
            "system.risers_count", {"building": "1", "discipline": "VK", "system_code": "В1"}, 4
        )
        third = await vk.calculate(systems=["В1"])
        assert _hashes(third) != _hashes(first)
        again = await vk.get(f"/vk/passports/{passport['id']}")
        assert again["passport_sha256"] == passport["passport_sha256"]
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(
                text("update calc_passports set status = 'READY' where id = :id"),
                {"id": passport["id"]},
            )
        await db_session.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.execute(text("delete from calc_expected_quantities"))
        await db_session.rollback()

    async def test_t36_t37_rule_change_keeps_old_run_and_replay_holds(self, vk: VkProject) -> None:
        await vk.building(Building())
        await vk.rules("В1")
        first = await vk.passport(await vk.calculate(systems=["В1"]), "В1")
        before = await vk.volumes(first, "EXPECTED")
        content = content_for("vk.b1.risers.count_range", per_riser_min="1", per_riser_max="2")
        await vk.post(
            "/rules/vk.b1.risers.count_range/versions",
            {"change_reason": "Синтетика: другие параметры для проверки T36.", "content": content},
        )
        async with vk.reviewer() as client:
            approved = await client.post(
                f"{API}/rules/vk.b1.risers.count_range/versions/2/approve", json=APPROVE
            )
        assert approved.status_code == 200, approved.text
        changed = await vk.passport(await vk.calculate(systems=["В1"]), "В1")
        assert changed["passport_sha256"] != first["passport_sha256"]
        riser = _volume(await vk.volumes(changed, "EXPECTED"), "vk.b1.pipe.riser")
        assert (riser["amount"]["low"], riser["amount"]["high"]) == ("216.6", "433.2")
        assert await vk.volumes(first, "EXPECTED") == before
        for run in first["runs"]:
            replay = await vk.post(f"/runs/{run['calculation_run_id']}/replay")
            assert replay["reproducible"] is True, replay
            if run["synthesis_run_id"]:
                synthesis = await vk.post(f"/synthesis-runs/{run['synthesis_run_id']}/replay")
                assert synthesis["reproducible"] is True, synthesis


class TestSemantics:
    async def test_missing_function_blocks_system_with_question(self, vk: VkProject) -> None:
        await vk.building(Building(systems={"В1": "COLD_WATER"}))
        batch = await vk.calculate(systems=["В1", "Т3"])
        statuses = {item["system_code"]: item["status"] for item in batch["passports"]}
        assert statuses == {"В1": "PARTIAL", "Т3": "BLOCKED"}
        passport = await vk.passport(batch, "Т3")
        assert passport["body"]["semantics"] == "MISSING"
        assert passport["runs"] == []
        assert passport["body"]["unresolved"][0]["key"] == "semantics"

    async def test_mismatched_function_is_not_silently_assigned(self, vk: VkProject) -> None:
        await vk.building(Building(systems={"Т3": "HOT_WATER_CIRCULATION"}))
        passport = await vk.passport(await vk.calculate(systems=["Т3"]), "Т3")
        assert passport["status"] == "BLOCKED"
        assert passport["body"]["semantics"] == "MISMATCH"


class TestSections:
    async def test_g03_sections_are_separate_scopes(self, vk: VkProject) -> None:
        await vk.building(Building(section="1", apartments={"1": 0, "2..24": 4}))
        await vk.building(Building(section="2", apartments={"1": 0, "2..24": 6}))
        await vk.rules("В1")
        one = await vk.passport(await vk.calculate(systems=["В1"], section="1"), "В1")
        two = await vk.passport(await vk.calculate(systems=["В1"], section="2"), "В1")
        assert one["scope"]["section"] == "1" and two["scope"]["section"] == "2"
        first = _volume(await vk.volumes(one, "EXPECTED"), "vk.b1.connection.floor")
        second = _volume(await vk.volumes(two, "EXPECTED"), "vk.b1.connection.floor")
        assert first["amount"]["value"] == "46"
        assert (second["amount"]["low"], second["amount"]["high"]) == ("46", "69")


class TestAccess:
    async def test_idempotency_isolation_permissions(
        self,
        db_session: AsyncSession,
        vk: VkProject,
        build_api: Callable[..., AsyncClient],
        second_workspace: Workspace,
    ) -> None:
        await vk.building(Building())
        first = await vk.calculate(systems=["В1"], idempotency_key="vk-batch-0001")
        again = await vk.calculate(systems=["В1"], idempotency_key="vk-batch-0001")
        assert again["batch_id"] == first["batch_id"] and again["created"] is False
        assert await db_session.scalar(select(func.count()).select_from(CalcPassport)) == 1
        async with vk.engineer() as client:
            conflict = await client.post(
                f"{API}/projects/{vk.project.id}/vk/passports",
                json={"building": "2", "systems": ["В1"], "idempotency_key": "vk-batch-0001"},
            )
        assert conflict.status_code == 409
        passport_id = first["passports"][0]["id"]
        async with build_api(_as(Role.ENGINEER, second_workspace.id)) as client:
            assert (await client.get(f"{API}/vk/passports/{passport_id}")).status_code == 404
        async with build_api(_as(Role.VIEWER, vk.workspace_id)) as client:
            assert (await client.get(f"{API}/vk/passports/{passport_id}")).status_code == 200
            denied = await client.post(
                f"{API}/projects/{vk.project.id}/vk/passports", json={"building": "1"}
            )
        assert denied.status_code == 403
        async with vk.engineer() as client:
            unknown = await client.post(
                f"{API}/projects/{vk.project.id}/vk/passports",
                json={"building": "1", "systems": ["П1"]},
            )
        assert unknown.status_code == 422

    async def test_catalog_lists_needs_without_numbers(self, vk: VkProject) -> None:
        catalog = await vk.get("/vk/calculators")
        assert [item["system_code"] for item in catalog] == ["В1", "Т3", "Т4", "К1"]
        for item in catalog:
            assert item["calculator"]["kind"] == "PRODUCTION"
            for rule in item["rules"]:
                assert all("value" not in term for term in rule["parameters"])
        readiness = await vk.get(f"/projects/{vk.project.id}/vk/readiness", building="1")
        statuses = {rule["status"] for item in readiness["systems"] for rule in item["rules"]}
        assert statuses <= {"SOURCE_REQUIRED", "IMPLEMENTATION_REQUIRED"}
