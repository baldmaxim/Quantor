"""API реестра фактов (ADR-0030, PROMPT 01).

Через HTTP проверяются: источники, утверждения с версиями и свидетельствами, конфликт
источников и решение человека, проверка человеком, исключение ВОР Заказчика из расчёта,
права ролей, граница арендатора и закрытый флаг.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.context import AuthContext
from app.contracts.calc.facts import CalcFactCreate
from app.domain import (
    AuditAction,
    DocumentKind,
    GeometryStatus,
    OverrideScope,
    ProcessingStatus,
    Role,
)
from app.errors import DomainError, ErrorCode
from app.models import (
    AuditEvent,
    CalcFact,
    Document,
    FeatureFlagOverride,
    Project,
    Sheet,
    Workspace,
)
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services.calc.facts import registry
from tests.conftest import make_context

API = "/api/v1/calc"


@pytest.fixture
async def calc_enabled(db_session: AsyncSession) -> None:
    """Контур закрыт флагом до инженерного гейта; тесты включают его системным переопределением."""
    db_session.add(
        FeatureFlagOverride(
            flag_key="calc.portal",
            scope=OverrideScope.SYSTEM,
            workspace_id=None,
            enabled=True,
            reason="тесты реестра фактов",
        )
    )
    await db_session.commit()


def _as(role: Role, workspace_id: uuid.UUID) -> AuthContext:
    return make_context(role, workspace_id=workspace_id)


async def _project(session: AsyncSession, workspace_id: uuid.UUID, name: str = "ЖК") -> Project:
    project = await projects_service.create_project(session, workspace_id=workspace_id, name=name)
    await session.commit()
    return project


async def _revision(
    session: AsyncSession, project: Project, sha: str = "c" * 64
) -> tuple[uuid.UUID, uuid.UUID]:
    document = Document(
        project_id=project.id, display_name="Квартирография.pdf", document_kind=DocumentKind.PDF
    )
    session.add(document)
    await session.flush()
    revision = await documents_service.create_revision(
        session,
        document=document,
        revision_id=uuid.uuid4(),
        source_filename="Квартирография.pdf",
        source_mime="application/pdf",
        source_size=1024,
        source_sha256=sha,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        processing_status=ProcessingStatus.READY,
        geometry_status=GeometryStatus.READY,
    )
    sheet = Sheet(revision_id=revision.id, page_index=0, page_label="1", rotation=0)
    session.add(sheet)
    await session.commit()
    return revision.id, sheet.id


async def _source(client: AsyncClient, project: Project, **body: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/projects/{project.id}/sources", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _doc_evidence(revision_id: uuid.UUID, **extra: Any) -> dict[str, Any]:
    return {"kind": "DOCUMENT_FRAGMENT", "document_revision_id": str(revision_id), **extra}


def _apartments(source_id: str, count: int, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "fact_type": "floor.apartments_count",
        "subject": {"building": "1", "floor": "12"},
        "value": {"kind": "COUNT", "value": count},
        "method": "TABLE_EXPLICIT",
        "evidence": evidence,
    }


class TestFlag:
    async def test_closed_by_default(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Флаг объявлен и закрыт: без решения владельца контура нет и в API."""
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.get(f"{API}/fact-types")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


@pytest.mark.usefixtures("calc_enabled")
class TestFacts:
    async def test_fact_types_describe_forms(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            response = await client.get(f"{API}/fact-types")
        assert response.status_code == 200
        types = {item["key"]: item for item in response.json()}
        assert types["floor.height"]["unit"] == "m"
        assert types["floor.apartments_count"]["required_subject"] == ["building", "floor"]
        assert types["system.pipe_material"]["customer_vor_admissible"] is True
        assert types["system.risers_count"]["customer_vor_admissible"] is False

    async def test_manual_fact_keeps_stated_and_canonical_value(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        engineer = _as(Role.ENGINEER, workspace_id)
        async with build_api(engineer) as client:
            source = await _source(client, project, source_class="MANUAL", title="Инженер")
            response = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    "source_id": source["id"],
                    "fact_type": "floor.height",
                    "subject": {"building": "1", "floor": "2..24"},
                    "value": {"kind": "NUMBER", "value": "3300", "unit": "mm"},
                    "method": "MANUAL",
                    "note": "по разрезу 1-1",
                },
            )
        assert response.status_code == 201, response.text
        fact = response.json()
        assert fact["value"] == {"kind": "NUMBER", "value": "3.3", "unit": "m"}
        assert fact["stated_value"] == {"kind": "NUMBER", "value": "3300", "unit": "mm"}
        assert fact["fact_key"] == "floor.height@building=1|floor=2..24"
        assert fact["version"] == 1
        assert fact["confidence"] == "MEDIUM"
        assert fact["review_status"] == "UNREVIEWED"
        assert fact["calculation_eligible"] is True
        [evidence] = fact["evidence"]
        assert evidence["kind"] == "MANUAL_ENTRY"
        assert evidence["author_id"] == str(engineer.principal.user_id)
        assert evidence["basis"] == "по разрезу 1-1"

    async def test_new_value_from_same_source_is_a_new_version(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        revision_id, _ = await _revision(db_session, project)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            source = await _source(
                client,
                project,
                source_class="APARTMENT_SCHEDULE",
                title="Квартирография",
                document_stage="P",
                document_revision_id=str(revision_id),
            )
            evidence = [_doc_evidence(revision_id, page_index=0, locator="строка 12")]
            first = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json=_apartments(source["id"], 9, evidence),
                )
            ).json()
            second = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json=_apartments(source["id"], 8, evidence),
                )
            ).json()
            listed = (await client.get(f"{API}/projects/{project.id}/facts")).json()
            conflicts = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()

        assert source["content_sha256"] == "c" * 64
        assert second["version"] == 2
        assert second["supersedes_id"] == first["id"]
        statuses = {item["id"]: item["status"] for item in listed}
        assert statuses == {first["id"]: "SUPERSEDED", second["id"]: "ACTIVE"}
        # Один источник не спорит сам с собой: новая версия — не конфликт.
        assert conflicts == []

    async def test_conflict_decision_and_reopening(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Два документа расходятся — конфликт; решение человека; новый источник его открывает."""
        project = await _project(db_session, workspace_id)
        schedule_rev, _ = await _revision(db_session, project, sha="1" * 64)
        plan_rev, sheet_id = await _revision(db_session, project, sha="2" * 64)
        note_rev, _ = await _revision(db_session, project, sha="3" * 64)

        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            schedule = await _source(
                client,
                project,
                source_class="APARTMENT_SCHEDULE",
                title="Квартирография",
                document_stage="P",
                document_revision_id=str(schedule_rev),
            )
            plan = await _source(
                client,
                project,
                source_class="ARCHITECTURE",
                title="АР, план 12 этажа",
                document_stage="P",
                section_code="АР",
                document_revision_id=str(plan_rev),
            )
            by_schedule = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json=_apartments(schedule["id"], 9, [_doc_evidence(schedule_rev)]),
                )
            ).json()
            by_plan = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json=_apartments(
                        plan["id"],
                        8,
                        [
                            _doc_evidence(
                                plan_rev, sheet_id=str(sheet_id), bbox=[0.1, 0.1, 0.4, 0.3]
                            )
                        ],
                    ),
                )
            ).json()
            [conflict] = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
            [value] = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()

        assert conflict["status"] == "OPEN"
        assert {claim["id"] for claim in conflict["claims"]} == {by_schedule["id"], by_plan["id"]}
        # Политика типа: квартирография сильнее плана, но конфликт остаётся видимым.
        assert value["state"] == "AUTO_PREFERRED"
        assert value["value"]["value"] == 9
        assert value["conflict_id"] == conflict["id"]

        async with build_api(_as(Role.REVIEWER, workspace_id)) as client:
            decided = await client.post(
                f"{API}/conflicts/{conflict['id']}/decision",
                json={"chosen_fact_id": by_plan["id"], "reason": "План РП-12 новее квартирографии"},
            )
            [value] = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()
        assert decided.status_code == 201, decided.text
        assert decided.json()["status"] == "RESOLVED"
        assert decided.json()["decision"]["chosen_fact_id"] == by_plan["id"]
        assert value["state"] == "DECIDED"
        assert value["value"]["value"] == 8

        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            note = await _source(
                client,
                project,
                source_class="EXPLANATORY_NOTE",
                title="ПЗ",
                document_stage="P",
                document_revision_id=str(note_rev),
            )
            newcomer = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json=_apartments(note["id"], 10, [_doc_evidence(note_rev, locator="п. 3.1")]),
                )
            ).json()
            [reopened] = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
            [stale] = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()
            await client.post(
                f"{API}/facts/{newcomer['id']}/withdraw", json={"reason": "опечатка в записке"}
            )
            [back] = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()

        assert reopened["status"] == "REOPENED"
        assert stale["state"] == "DECIDED_STALE"
        assert "DECISION_STALE" in stale["warnings"]
        # Отзыв возвращает набор утверждений к тому, по которому решали.
        assert back["status"] == "RESOLVED"

        async with build_api(_as(Role.REVIEWER, workspace_id)) as client:
            await client.post(
                f"{API}/facts/{by_schedule['id']}/review",
                json={"status": "REJECTED", "comment": "кладовая учтена как квартира"},
            )
            [closed] = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
            [final] = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()
        # Расхождения больше нет: конфликт закрыт, и значение не помечено «решение устарело».
        assert closed["status"] == "OBSOLETE"
        assert final["state"] == "SINGLE"
        assert final["value"]["value"] == 8
        assert final["warnings"] == []

    async def test_decision_with_own_value_creates_a_carrier_claim(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        rev_a, _ = await _revision(db_session, project, sha="4" * 64)
        rev_b, _ = await _revision(db_session, project, sha="5" * 64)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            a = await _source(
                client,
                project,
                source_class="MEP_DESIGN",
                title="ВК П",
                document_stage="P",
                document_revision_id=str(rev_a),
            )
            b = await _source(
                client,
                project,
                source_class="EXPLANATORY_NOTE",
                title="ПЗ ВК",
                document_stage="P",
                document_revision_id=str(rev_b),
            )
            for source, material, revision in ((a, "сталь", rev_a), (b, "PE-X", rev_b)):
                response = await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json={
                        "source_id": source["id"],
                        "fact_type": "system.pipe_material",
                        "subject": {"building": "1", "discipline": "VK", "system_code": "B1"},
                        "value": {"kind": "TEXT", "value": material},
                        "method": "DOCUMENT_EXPLICIT",
                        "evidence": [_doc_evidence(revision)],
                    },
                )
                assert response.status_code == 201, response.text
            [conflict] = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
            assert conflict["status"] == "OPEN"
            decided = await client.post(
                f"{API}/conflicts/{conflict['id']}/decision",
                json={
                    "value": {"kind": "TEXT", "value": "сталь оцинкованная"},
                    "reason": "Уточнено у ГИПа",
                },
            )
            [value] = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()
            sources = (await client.get(f"{API}/projects/{project.id}/sources")).json()
            [decisions] = [item for item in sources if item["series_key"] == "calc:decisions"]
            # Источник решений пополняется только решением: значение без решения не пройдёт.
            forged = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    "source_id": decisions["id"],
                    "fact_type": "system.pipe_material",
                    "subject": {"building": "1", "discipline": "VK", "system_code": "В1"},
                    "value": {"kind": "TEXT", "value": "медь"},
                    "method": "MANUAL",
                },
            )

        assert decided.status_code == 201, decided.text
        assert value["state"] == "DECIDED"
        assert value["value"] == {"kind": "TEXT", "value": "сталь оцинкованная"}
        # Латинская B в коде системы нормализована к кириллице.
        assert value["fact_key"].endswith("system_code=В1")
        assert forged.status_code == 422
        assert forged.json()["detail"]["code"] == "CALC_SOURCE_NOT_ALLOWED"

    async def test_same_file_under_two_sources_is_one_confirmation(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Альбом, заведённый как АР и как квартирография, — один файл, а не два подтверждения."""
        project = await _project(db_session, workspace_id)
        album, _ = await _revision(db_session, project, sha="a" * 64)
        other, _ = await _revision(db_session, project, sha="b" * 64)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            states = []
            for source_class, revision in (
                ("APARTMENT_SCHEDULE", album),
                ("ARCHITECTURE", album),
                ("ARCHITECTURE", other),
            ):
                source = await _source(
                    client,
                    project,
                    source_class=source_class,
                    title=source_class,
                    document_stage="P",
                    document_revision_id=str(revision),
                )
                response = await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json=_apartments(source["id"], 9, [_doc_evidence(revision)]),
                )
                assert response.status_code == 201, response.text
                [value] = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()
                states.append(value["state"])
        assert states == ["SINGLE", "SINGLE", "CORROBORATED"]

    async def test_manual_confirmation_and_rejection(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        rev_a, _ = await _revision(db_session, project, sha="6" * 64)
        rev_b, _ = await _revision(db_session, project, sha="7" * 64)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            a = await _source(
                client,
                project,
                source_class="APARTMENT_SCHEDULE",
                title="Кв.",
                document_stage="P",
                document_revision_id=str(rev_a),
            )
            b = await _source(
                client,
                project,
                source_class="APARTMENT_SCHEDULE",
                title="Кв. 2",
                document_stage="P",
                document_revision_id=str(rev_b),
            )
            good = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json=_apartments(a["id"], 9, [_doc_evidence(rev_a)]),
                )
            ).json()
            bad = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json=_apartments(b["id"], 99, [_doc_evidence(rev_b)]),
                )
            ).json()
            [conflict] = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
        assert conflict["status"] == "OPEN"

        async with build_api(_as(Role.REVIEWER, workspace_id)) as client:
            no_reason = await client.post(
                f"{API}/facts/{bad['id']}/review", json={"status": "REJECTED"}
            )
            confirmed = await client.post(
                f"{API}/facts/{good['id']}/review",
                json={"status": "CONFIRMED", "comment": "сверено с планом"},
            )
            rejected = await client.post(
                f"{API}/facts/{bad['id']}/review",
                json={"status": "REJECTED", "comment": "ошибка распознавания: 99 вместо 9"},
            )
            [after] = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
            [value] = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()

        assert no_reason.status_code == 422
        assert confirmed.json()["review_status"] == "CONFIRMED"
        assert confirmed.json()["reviewed_by"] is not None
        assert rejected.json()["review_status"] == "REJECTED"
        # Отклонённое не голосует: расхождения больше нет.
        assert after["status"] == "OBSOLETE"
        assert value["state"] == "SINGLE"
        assert value["chosen_fact_id"] == good["id"]


@pytest.mark.usefixtures("calc_enabled")
class TestCustomerVor:
    """ВОР Заказчика — объект сверки, а не эталон (решение владельца 2026-09-28)."""

    async def test_vor_facts_never_reach_calculation(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        vor_rev, _ = await _revision(db_session, project, sha="8" * 64)
        design_rev, _ = await _revision(db_session, project, sha="9" * 64)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            vor = await _source(
                client,
                project,
                source_class="CUSTOMER_VOR",
                title="ВОР Заказчика",
                document_revision_id=str(vor_rev),
            )
            design = await _source(
                client,
                project,
                source_class="MEP_DESIGN",
                title="ВК П",
                document_stage="P",
                document_revision_id=str(design_rev),
            )
            quantity = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    "source_id": vor["id"],
                    "fact_type": "system.risers_count",
                    "subject": {"building": "1", "discipline": "VK", "system_code": "К1"},
                    "value": {"kind": "COUNT", "value": 12},
                    "method": "TABLE_EXPLICIT",
                    "evidence": [_doc_evidence(vor_rev, locator="поз. 14")],
                },
            )
            material = {
                "fact_type": "system.pipe_material",
                "subject": {"building": "1", "discipline": "VK", "system_code": "К1"},
                "method": "TABLE_EXPLICIT",
            }
            from_vor = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    **material,
                    "source_id": vor["id"],
                    "value": {"kind": "TEXT", "value": "НПВХ"},
                    "evidence": [_doc_evidence(vor_rev)],
                },
            )
            from_design = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    **material,
                    "source_id": design["id"],
                    "value": {"kind": "TEXT", "value": "ПП бесшумный"},
                    "evidence": [_doc_evidence(design_rev)],
                },
            )
            [value] = (await client.get(f"{API}/projects/{project.id}/fact-values")).json()
            conflicts = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()

        assert vor["calculation_eligible"] is False
        assert quantity.status_code == 422
        assert quantity.json()["detail"]["code"] == "CALC_SOURCE_NOT_ALLOWED"
        assert from_vor.status_code == 201, from_vor.text
        assert from_vor.json()["calculation_eligible"] is False
        # ВОР не спорит с проектом и не подтверждает его: значение — только из документа П.
        assert conflicts == []
        assert value["state"] == "SINGLE"
        assert value["chosen_fact_id"] == from_design.json()["id"]
        assert value["excluded_claim_ids"] == [from_vor.json()["id"]]

        snapshot = await registry.calculation_snapshot(db_session, project_id=project.id)
        assert [item.chosen_fact_id for item in snapshot.items] == [
            uuid.UUID(from_design.json()["id"])
        ]

    async def test_database_refuses_eligible_vor_fact(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Ограничение базы: даже ручной SQL не допустит ВОР к расчёту."""
        project = await _project(db_session, workspace_id)
        rev, _ = await _revision(db_session, project, sha="e" * 64)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            vor = await _source(
                client,
                project,
                source_class="CUSTOMER_VOR",
                title="ВОР",
                document_revision_id=str(rev),
            )
            fact = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json={
                        "source_id": vor["id"],
                        "fact_type": "system.present",
                        "subject": {"discipline": "VK", "system_code": "Т4"},
                        "value": {"kind": "BOOLEAN", "value": True},
                        "method": "TABLE_EXPLICIT",
                        "evidence": [_doc_evidence(rev)],
                    },
                )
            ).json()
        with pytest.raises(IntegrityError):
            await db_session.execute(
                update(CalcFact)
                .where(CalcFact.id == uuid.UUID(fact["id"]))
                .values(calculation_eligible=True)
            )
            await db_session.flush()
        await db_session.rollback()


@pytest.mark.usefixtures("calc_enabled")
class TestRules:
    async def _setup(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> tuple[Project, dict[str, Any], dict[str, Any], uuid.UUID]:
        project = await _project(db_session, workspace_id)
        rev, _ = await _revision(db_session, project)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            manual = await _source(client, project, source_class="MANUAL", title="Инженер")
            document = await _source(
                client,
                project,
                source_class="ARCHITECTURE",
                title="АР",
                document_stage="P",
                document_revision_id=str(rev),
            )
        return project, manual, document, rev

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ({"method": "CALCULATED"}, "CALC_METHOD_NOT_AVAILABLE"),
            ({"method": "GEOMETRY_MEASURED"}, "CALC_METHOD_NOT_AVAILABLE"),
            ({"method": "ASSUMPTION"}, "CALC_EVIDENCE_REQUIRED"),
            ({"fact_type": "floor.secret"}, "CALC_FACT_TYPE_UNKNOWN"),
            ({"subject": {"building": "1"}}, "CALC_SUBJECT_INVALID"),
            ({"value": {"kind": "NUMBER", "value": "3.3", "unit": "m2"}}, "CALC_UNIT_MISMATCH"),
            ({"value": {"kind": "COUNT", "value": 3}}, "CALC_VALUE_INVALID"),
        ],
    )
    async def test_manual_input_rules(
        self,
        body: dict[str, Any],
        code: str,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project, manual, _, _ = await self._setup(db_session, build_api, workspace_id)
        payload = {
            "source_id": manual["id"],
            "fact_type": "floor.height",
            "subject": {"building": "1", "floor": "3"},
            "value": {"kind": "NUMBER", "value": "3.3", "unit": "m"},
            "method": "MANUAL",
            **body,
        }
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.post(f"{API}/projects/{project.id}/facts", json=payload)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == code

    async def test_document_method_needs_document_source_and_fragment(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project, manual, document, rev = await self._setup(db_session, build_api, workspace_id)
        base = {
            "fact_type": "floor.height",
            "subject": {"building": "1", "floor": "3"},
            "value": {"kind": "NUMBER", "value": "3.3", "unit": "m"},
            "method": "DOCUMENT_EXPLICIT",
        }
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            no_fragment = await client.post(
                f"{API}/projects/{project.id}/facts", json={**base, "source_id": document["id"]}
            )
            from_manual = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={**base, "source_id": manual["id"], "evidence": [_doc_evidence(rev)]},
            )
            foreign_rev = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    **base,
                    "source_id": document["id"],
                    "evidence": [_doc_evidence(uuid.uuid4())],
                },
            )
        assert no_fragment.json()["detail"]["code"] == "CALC_EVIDENCE_REQUIRED"
        assert from_manual.json()["detail"]["code"] == "CALC_SOURCE_NOT_ALLOWED"
        assert foreign_rev.json()["detail"]["code"] == "CALC_EVIDENCE_INVALID"

    async def test_fragment_must_come_from_source_document(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Источник «файл А» не подтверждается фрагментом файла Б, даже из того же проекта."""
        project, _, document, _ = await self._setup(db_session, build_api, workspace_id)
        other_rev, _ = await _revision(db_session, project, sha="f" * 64)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    "source_id": document["id"],
                    "fact_type": "floor.height",
                    "subject": {"building": "1", "floor": "3"},
                    "value": {"kind": "NUMBER", "value": "3.3", "unit": "m"},
                    "method": "DOCUMENT_EXPLICIT",
                    "evidence": [_doc_evidence(other_rev)],
                },
            )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "CALC_EVIDENCE_INVALID"

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            # Источник-документ — конкретный файл, без ревизии его отпечатка нет.
            ({"source_class": "ARCHITECTURE"}, "CALC_EVIDENCE_REQUIRED"),
            ({"source_class": "CUSTOMER_VOR"}, "CALC_EVIDENCE_REQUIRED"),
            ({"source_class": "MANUAL", "with_revision": True}, "CALC_EVIDENCE_INVALID"),
            ({"source_class": "MANUAL", "series_key": "calc:decisions"}, "CALC_SOURCE_NOT_ALLOWED"),
        ],
    )
    async def test_source_shape(
        self,
        body: dict[str, Any],
        code: str,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        payload = {"title": "Источник", **body}
        if payload.pop("with_revision", False):
            revision_id, _ = await _revision(db_session, project)
            payload["document_revision_id"] = str(revision_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.post(f"{API}/projects/{project.id}/sources", json=payload)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == code

    async def test_assumption_is_low_confidence_with_basis(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project, manual, _, _ = await self._setup(db_session, build_api, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    "source_id": manual["id"],
                    "fact_type": "floor.corridor_length",
                    "subject": {"building": "1", "floor": "2..24"},
                    "value": {"kind": "NUMBER", "value": "30", "unit": "m"},
                    "method": "ASSUMPTION",
                    "evidence": [
                        {
                            "kind": "ASSUMPTION_BASIS",
                            "basis": "Планы этажей стадии П без размеров коридора",
                            "alternatives": ["24 м", "36 м"],
                        }
                    ],
                },
            )
        assert response.status_code == 201, response.text
        fact = response.json()
        assert fact["confidence"] == "LOW"
        assert fact["evidence"][0]["alternatives"] == ["24 м", "36 м"]

    async def test_withdrawn_fact_cannot_be_withdrawn_again(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project, manual, _, _ = await self._setup(db_session, build_api, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            fact = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json={
                        "source_id": manual["id"],
                        "fact_type": "building.floors_above_ground",
                        "subject": {"building": "1"},
                        "value": {"kind": "COUNT", "value": 25},
                        "method": "MANUAL",
                    },
                )
            ).json()
            first = await client.post(
                f"{API}/facts/{fact['id']}/withdraw", json={"reason": "дубль"}
            )
            second = await client.post(f"{API}/facts/{fact['id']}/withdraw", json={"reason": "ещё"})
        assert first.json()["status"] == "WITHDRAWN"
        assert first.json()["withdrawn_reason"] == "дубль"
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "CALC_FACT_NOT_ACTIVE"

    async def test_actions_are_audited(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project, manual, _, _ = await self._setup(db_session, build_api, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await client.post(
                f"{API}/projects/{project.id}/facts",
                json={
                    "source_id": manual["id"],
                    "fact_type": "building.sections_count",
                    "subject": {"building": "1"},
                    "value": {"kind": "COUNT", "value": 2},
                    "method": "MANUAL",
                },
            )
        actions = set((await db_session.scalars(select(AuditEvent.action))).all())
        assert AuditAction.CALC_SOURCE_CREATED.value in actions
        assert AuditAction.CALC_FACT_CREATED.value in actions


@pytest.mark.usefixtures("calc_enabled")
class TestAccess:
    async def test_roles(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            manual = await _source(client, project, source_class="MANUAL", title="Инженер")
            fact = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json={
                        "source_id": manual["id"],
                        "fact_type": "building.floors_below_ground",
                        "subject": {"building": "1"},
                        "value": {"kind": "COUNT", "value": 2},
                        "method": "MANUAL",
                    },
                )
            ).json()

        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            viewer_list = await client.get(f"{API}/projects/{project.id}/facts")
            viewer_create = await client.post(
                f"{API}/projects/{project.id}/sources",
                json={"source_class": "MANUAL", "title": "x"},
            )
            viewer_review = await client.post(
                f"{API}/facts/{fact['id']}/review", json={"status": "CONFIRMED"}
            )
        async with build_api(_as(Role.REVIEWER, workspace_id)) as client:
            reviewer_create = await client.post(
                f"{API}/projects/{project.id}/sources",
                json={"source_class": "MANUAL", "title": "x"},
            )
            reviewer_review = await client.post(
                f"{API}/facts/{fact['id']}/review", json={"status": "CONFIRMED"}
            )

        assert viewer_list.status_code == 200
        assert viewer_create.status_code == 403
        assert viewer_review.status_code == 403
        # Проверяющий подтверждает, но не вносит: ответственность за число отделена от ввода.
        assert reviewer_create.status_code == 403
        assert reviewer_review.status_code == 200

    async def test_foreign_workspace_sees_nothing(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        project = await _project(db_session, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            manual = await _source(client, project, source_class="MANUAL", title="Инженер")
            fact = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json={
                        "source_id": manual["id"],
                        "fact_type": "building.floors_above_ground",
                        "subject": {"building": "1"},
                        "value": {"kind": "COUNT", "value": 25},
                        "method": "MANUAL",
                    },
                )
            ).json()

        async with build_api(_as(Role.WORKSPACE_ADMIN, second_workspace.id)) as client:
            listed = await client.get(f"{API}/projects/{project.id}/facts")
            single = await client.get(f"{API}/facts/{fact['id']}")
            created = await client.post(
                f"{API}/projects/{project.id}/sources",
                json={"source_class": "MANUAL", "title": "x"},
            )
        assert listed.status_code == 404
        assert single.status_code == 404
        assert created.status_code == 404


@pytest.mark.usefixtures("calc_enabled")
class TestConcurrency:
    """Два запроса к одному ключу одновременно — две независимые транзакции."""

    async def test_simultaneous_disagreement_is_not_lost(
        self,
        db_session: AsyncSession,
        db_engine: AsyncEngine,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Без блокировки ключа каждое утверждение не видело бы другое, и конфликт пропал бы."""
        project = await _project(db_session, workspace_id)
        rev_a, _ = await _revision(db_session, project, sha="a" * 64)
        rev_b, _ = await _revision(db_session, project, sha="b" * 64)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            a = await _source(
                client,
                project,
                source_class="APARTMENT_SCHEDULE",
                title="Кв.",
                document_stage="P",
                document_revision_id=str(rev_a),
            )
            b = await _source(
                client,
                project,
                source_class="APARTMENT_SCHEDULE",
                title="Кв. 2",
                document_stage="P",
                document_revision_id=str(rev_b),
            )

        factory = async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
        async with factory() as first, factory() as second:
            await registry.create_fact(
                first,
                project=project,
                payload=CalcFactCreate.model_validate(
                    _apartments(a["id"], 9, [_doc_evidence(rev_a)])
                ),
                author_id=None,
            )
            pending = asyncio.create_task(
                registry.create_fact(
                    second,
                    project=project,
                    payload=CalcFactCreate.model_validate(
                        _apartments(b["id"], 8, [_doc_evidence(rev_b)])
                    ),
                    author_id=None,
                )
            )
            await asyncio.sleep(0.3)
            # Второе утверждение ждёт первое, а не проходит мимо незафиксированного.
            assert not pending.done()
            await first.commit()
            await pending
            await second.commit()

        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            conflicts = (await client.get(f"{API}/projects/{project.id}/conflicts")).json()
        assert [conflict["status"] for conflict in conflicts] == ["OPEN"]

    async def test_stale_fact_is_not_withdrawn_twice(
        self,
        db_session: AsyncSession,
        db_engine: AsyncEngine,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Второй отзыв ждёт первый и видит свежий статус, а не прочитанный до ожидания."""
        project = await _project(db_session, workspace_id)
        engineer = _as(Role.ENGINEER, workspace_id)
        async with build_api(engineer) as client:
            manual = await _source(client, project, source_class="MANUAL", title="Инженер")
            fact = (
                await client.post(
                    f"{API}/projects/{project.id}/facts",
                    json={
                        "source_id": manual["id"],
                        "fact_type": "building.floors_above_ground",
                        "subject": {"building": "1"},
                        "value": {"kind": "COUNT", "value": 25},
                        "method": "MANUAL",
                    },
                )
            ).json()

        author = engineer.principal.user_id
        factory = async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
        async with factory() as first, factory() as second:
            mine = await registry.get_fact(
                first, workspace_id=workspace_id, fact_id=uuid.UUID(fact["id"])
            )
            theirs = await registry.get_fact(
                second, workspace_id=workspace_id, fact_id=uuid.UUID(fact["id"])
            )
            assert mine is not None and theirs is not None
            await registry.withdraw_fact(first, fact=mine, reason="дубль", author_id=author)
            pending = asyncio.create_task(
                registry.withdraw_fact(second, fact=theirs, reason="ещё", author_id=author)
            )
            await asyncio.sleep(0.3)
            assert not pending.done()
            await first.commit()
            with pytest.raises(DomainError) as refused:
                await pending
            await second.rollback()
        assert refused.value.code is ErrorCode.CALC_FACT_NOT_ACTIVE
