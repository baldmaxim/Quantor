"""Запуски расчётного ядра через базу и HTTP (ADR-0030, PROMPT 04).

Настоящий путь: факты — через API реестра фактов, правила `test.*` — через API реестра правил с
утверждением вторым человеком, запуск — через API ядра. Проверяются блокировки, снимок,
выбор версий, неизменяемость, идемпотентность, конкурентность, повтор и объяснение.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.context import AuthContext
from app.contracts.calc.engine import CalcRunCreate
from app.contracts.calc.enums import CalcRunStatus
from app.domain import (
    AuditAction,
    DocumentKind,
    GeometryStatus,
    OverrideScope,
    ProcessingStatus,
    Role,
)
from app.models import (
    AuditEvent,
    CalcFact,
    CalcRuleReview,
    CalcRuleVersion,
    CalcRun,
    CalcRunResult,
    CalcRunStep,
    Document,
    FeatureFlagOverride,
    Project,
    UserIdentity,
    Workspace,
)
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services.calc.engine import runs
from app.services.calc.engine.catalog import HANDLERS
from app.services.calc.engine.handlers import GoldenCase, HandlerContext, HandlerResult
from tests.calc_engine_fixtures import (
    reserve_rule,
    total_length_rule,
    vertical_length_rule,
)
from tests.conftest import make_context

API = "/api/v1/calc"
SCOPE = {"building": "1", "floor": "2..24", "discipline": "VK", "system_code": "В1"}
APPROVE = {"comment": "Проверено по тестовой фикстуре ядра.", "legacy_review": []}
RULES = {
    "test.geometry.vertical_length": vertical_length_rule,
    "test.geometry.total_length": total_length_rule,
    "test.tender.length_reserve": reserve_rule,
}


def _body(scenario: str = "EXPECTED", **extra: Any) -> dict[str, Any]:
    return {
        "calculator_id": "test.vertical_length",
        "calculator_version": 1,
        "scenario": scenario,
        "scope": SCOPE,
        **extra,
    }


@pytest.fixture
async def calc_enabled(db_session: AsyncSession) -> None:
    db_session.add(
        FeatureFlagOverride(
            flag_key="calc.portal",
            scope=OverrideScope.SYSTEM,
            workspace_id=None,
            enabled=True,
            reason="тесты расчётного ядра",
        )
    )
    await db_session.commit()


def _as(role: Role, workspace_id: uuid.UUID, user_id: uuid.UUID | None = None) -> AuthContext:
    if user_id is None:
        return make_context(role, workspace_id=workspace_id)
    return make_context(role, workspace_id=workspace_id, user_id=user_id)


async def _project(session: AsyncSession, workspace_id: uuid.UUID) -> Project:
    project = await projects_service.create_project(session, workspace_id=workspace_id, name="ЖК")
    await session.commit()
    return project


async def _revision(session: AsyncSession, project: Project) -> uuid.UUID:
    """Документ проекта для источника-документа (ВОР Заказчика)."""
    document = Document(
        project_id=project.id, display_name="ВОР.pdf", document_kind=DocumentKind.PDF
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
        source_sha256="d" * 64,
        storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
        processing_status=ProcessingStatus.READY,
        geometry_status=GeometryStatus.READY,
    )
    await session.commit()
    return revision.id


async def _source(client: AsyncClient, project: Project, **body: Any) -> str:
    response = await client.post(
        f"{API}/projects/{project.id}/sources",
        json={"source_class": "MANUAL", "title": "Инженер", **body},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _fact(
    client: AsyncClient,
    project: Project,
    source_id: str,
    fact_type: str,
    subject: dict[str, str],
    value: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/projects/{project.id}/facts",
        json={
            "source_id": source_id,
            "fact_type": fact_type,
            "subject": subject,
            "value": value,
            **{"method": "MANUAL", "note": "по листу проекта", **extra},
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def _demo_facts(
    client: AsyncClient, project: Project, *, floors: int = 24, risers: int = 2
) -> dict[str, dict[str, Any]]:
    """Высота этажа заявлена в миллиметрах: реестр хранит её в метрах, заявление — тоже."""
    source = await _source(client, project)
    return {
        "height": await _fact(
            client,
            project,
            source,
            "floor.height",
            {"building": "1", "floor": "2..24"},
            {"kind": "NUMBER", "value": "3300", "unit": "mm"},
        ),
        "floors": await _fact(
            client,
            project,
            source,
            "building.floors_above_ground",
            {"building": "1"},
            {"kind": "COUNT", "value": floors},
        ),
        "risers": await _fact(
            client,
            project,
            source,
            "system.risers_count",
            {"building": "1", "discipline": "VK", "system_code": "В1"},
            {"kind": "COUNT", "value": risers},
        ),
    }


async def _rules(
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    *,
    approve: bool = True,
    only: tuple[str, ...] = tuple(RULES),
) -> None:
    async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
        for key in only:
            response = await client.post(
                f"{API}/rules", json={"rule_key": key, "content": RULES[key]()}
            )
            assert response.status_code == 201, response.text
    if not approve:
        return
    async with build_api(_as(Role.REVIEWER, workspace_id, reviewer_id)) as client:
        for key in only:
            response = await client.post(f"{API}/rules/{key}/versions/1/approve", json=APPROVE)
            assert response.status_code == 200, response.text


async def _start(client: AsyncClient, project: Project, **body: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/projects/{project.id}/runs", json=_body(**body))
    assert response.status_code in {200, 201}, response.text
    result: dict[str, Any] = response.json()
    return result


def _codes(run: dict[str, Any]) -> list[str]:
    return [item["code"] for item in run["blocking_reasons"]]


def _results(run: dict[str, Any]) -> dict[str, str]:
    return {item["result_key"]: item["value"] for item in run["results"]}


@pytest.fixture
async def ready(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    other_user: UserIdentity,
    calc_enabled: None,
) -> Project:
    """Проект с фактами демо-калькулятора и утверждёнными правилами `test.*`."""
    project = await _project(db_session, workspace_id)
    async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
        await _demo_facts(client, project)
    await _rules(build_api, workspace_id, other_user.id)
    return project


# ----------------------------------------------------------------------- флаг, каталог, права


class TestAccess:
    async def test_t31_closed_by_default(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.get(f"{API}/calculators")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"

    @pytest.mark.usefixtures("calc_enabled")
    async def test_catalog(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            hidden = (await client.get(f"{API}/calculators")).json()
            listed = (
                await client.get(f"{API}/calculators", params={"include_demo": "true"})
            ).json()
        # Демонстрационные калькуляторы в пользовательском списке скрыты (решение владельца);
        # видны только рабочие калькуляторы ВК стадии П (PROMPT 06).
        assert {item["calculator_id"] for item in hidden} == {
            "vk.b1.stage_p",
            "vk.t3.stage_p",
            "vk.t4.stage_p",
            "vk.k1.stage_p",
        }
        assert all(item["kind"] == "PRODUCTION" for item in hidden)
        demo = next(item for item in listed if item["calculator_id"] == "test.vertical_length")
        assert (demo["calculator_id"], demo["version"], demo["kind"]) == (
            "test.vertical_length",
            1,
            "DEMO",
        )
        assert demo["scenarios"] == ["EXPECTED", "MINIMUM", "TENDER_SAFE"]
        assert demo["rules"] == list(RULES)
        assert {item["fact_type"] for item in demo["facts"]} == {
            "floor.height",
            "building.floors_above_ground",
            "system.risers_count",
        }

    async def test_roles_and_workspace(
        self,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            validated = await client.post(f"{API}/projects/{ready.id}/runs/validate", json=_body())
            forbidden = await client.post(f"{API}/projects/{ready.id}/runs", json=_body())
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            run = await _start(client, ready)
        async with build_api(_as(Role.ENGINEER, second_workspace.id)) as client:
            foreign = await client.get(f"{API}/runs/{run['id']}")
            foreign_project = await client.get(f"{API}/projects/{ready.id}/runs")
        assert validated.status_code == 200 and validated.json()["valid"] is True
        assert forbidden.status_code == 403
        assert foreign.status_code == 404
        assert foreign_project.status_code == 404

    @pytest.mark.usefixtures("calc_enabled")
    async def test_unknown_calculator(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await _project(db_session, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.post(
                f"{API}/projects/{project.id}/runs", json=_body(calculator_version=9)
            )
        assert response.status_code == 404


# ----------------------------------------------------------------------- успешный запуск


class TestRun:
    async def test_demo_run_end_to_end(
        self,
        db_session: AsyncSession,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            run = await _start(client, ready, scenario="TENDER_SAFE")
            listed = (await client.get(f"{API}/projects/{ready.id}/runs")).json()
            result = (await client.get(f"{API}/runs/{run['id']}/results/demo.total_length")).json()
        assert run["status"] == "SUCCEEDED"
        assert _results(run) == {"demo.vertical_length": "79.2", "demo.total_length": "169.5"}
        assert [step["status"] for step in run["steps"]] == ["EXECUTED"] * 3
        assert [item["step_key"] for item in run["rule_bindings"]] == [
            "vertical_length",
            "total_length",
            "total_with_reserve",
        ]
        assert run["versions"]["engine"] == "calc.engine.v1"
        assert run["assumptions"][0]["applied"] is True
        assert result["rounding"]["before"] == "169.488"
        assert listed[0]["results_count"] == 2
        actions = set((await db_session.scalars(select(AuditEvent.action))).all())
        assert AuditAction.CALC_RUN_CREATED.value in actions

    async def test_t15_stated_millimetres_reach_the_trace(
        self, ready: Project, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            run = await _start(client, ready)
            trace = (
                await client.get(f"{API}/runs/{run['id']}/results/demo.vertical_length/trace")
            ).json()
        height = next(
            item for item in run["snapshot"]["items"] if item["fact_type"] == "floor.height"
        )
        assert height["value"] == {"kind": "NUMBER", "value": "3.3", "unit": "m"}
        assert height["stated_value"] == {"kind": "NUMBER", "value": "3300", "unit": "mm"}
        step = trace["root"]["children"][0]
        fact = next(child for child in step["children"] if child["kind"] == "FACT")
        assert "заявлено: 3300 мм" in fact["text"]

    async def test_t23_trace_from_result_to_evidence(
        self, ready: Project, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            run = await _start(client, ready)
            trace = (
                await client.get(f"{API}/runs/{run['id']}/results/demo.total_length/trace")
            ).json()
            missing = await client.get(f"{API}/runs/{run['id']}/results/nope/trace")
        assert missing.status_code == 404
        assert trace["text"].startswith("Длина по всем стоякам (демо) = 158,4 м.")
        assert "Высота этажа 3,3 м × 24 эт. = 79,2 м" in trace["text"]

        def find(node: dict[str, Any], kind: str) -> list[dict[str, Any]]:
            found = [node] if node["kind"] == kind else []
            for child in node["children"]:
                found += find(child, kind)
            return found

        rules = {node["key"] for node in find(trace["root"], "RULE")}
        assert {"test.geometry.vertical_length@1", "test.geometry.total_length@1"} <= rules
        facts = find(trace["root"], "FACT")
        assert {node["ref"] for node in facts} == {
            item["fact_id"] for item in run["snapshot"]["items"]
        }
        assert find(trace["root"], "EVIDENCE"), "у ручного ввода есть свидетельство автора"


# --------------------------------------------------------------- блокировки (T02–T10, A–D)


class TestBlocked:
    async def test_t02_missing_fact_blocks_without_http_error(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
        calc_enabled: None,
    ) -> None:
        project = await _project(db_session, workspace_id)
        await _rules(build_api, workspace_id, other_user.id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            validated = (
                await client.post(f"{API}/projects/{project.id}/runs/validate", json=_body())
            ).json()
            nothing_written = (await client.get(f"{API}/projects/{project.id}/runs")).json()
            response = await client.post(f"{API}/projects/{project.id}/runs", json=_body())
        assert validated["valid"] is False
        assert nothing_written == []
        assert response.status_code == 201
        run = response.json()
        assert run["status"] == "BLOCKED"
        assert set(_codes(run)) == {"FACT_MISSING"}
        assert {item["fact_key"] for item in run["blocking_reasons"]} == {
            "floor.height@building=1|floor=2..24",
            "building.floors_above_ground@building=1",
            "system.risers_count@building=1|discipline=VK|system_code=В1",
        }
        assert run["results"] == [] and run["steps"] == [] and run["result_sha256"] is None

    async def test_a_rejected_value_is_not_zero(
        self,
        db_session: AsyncSession,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        """Сценарий A: высота «не определена» — единственное значение отклонено проверкой."""
        height = await db_session.scalar(
            select(CalcFact).where(CalcFact.fact_type == "floor.height")
        )
        assert height is not None
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            reviewed = await client.post(
                f"{API}/facts/{height.id}/review",
                json={"status": "REJECTED", "comment": "высота не подтверждена"},
            )
        assert reviewed.status_code == 200, reviewed.text
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            run = await _start(client, ready)
        assert run["status"] == "BLOCKED"
        assert _codes(run) == ["FACT_MISSING"]
        assert run["results"] == []

    async def test_b_conflict_is_not_resolved_by_confidence(
        self,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        """Сценарий B: 3,0 м с низкой уверенностью против 3,3 м с высокой — расчёт ждёт человека."""
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            second = await _source(client, ready, title="Второй инженер")
            low = await _fact(
                client,
                ready,
                second,
                "floor.height",
                {"building": "1", "floor": "2..24"},
                {"kind": "NUMBER", "value": "3.0", "unit": "m"},
                confidence="LOW",
            )
            blocked = await _start(client, ready)
            [conflict] = (await client.get(f"{API}/projects/{ready.id}/conflicts")).json()
        assert blocked["status"] == "BLOCKED"
        assert _codes(blocked) == ["FACT_CONFLICT"]

        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            decided = await client.post(
                f"{API}/conflicts/{conflict['id']}/decision",
                json={"chosen_fact_id": low["id"], "reason": "по разрезу 1-1 высота 3,0 м"},
            )
        assert decided.status_code == 201, decided.text
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            run = await _start(client, ready)
        assert run["status"] == "SUCCEEDED"
        assert _results(run)["demo.vertical_length"] == "72"
        height = next(
            item for item in run["snapshot"]["items"] if item["fact_type"] == "floor.height"
        )
        assert height["resolution_state"] == "DECIDED"
        assert height["fact_id"] == low["id"]

    async def test_c_t06_t29_customer_vor_is_invisible(
        self,
        db_session: AsyncSession,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Сценарий C: «труба Ø50 — 1280 м» из ВОР не попадает ни в реестр, ни в расчёт."""
        revision = await _revision(db_session, ready)
        evidence = [{"kind": "DOCUMENT_FRAGMENT", "document_revision_id": str(revision)}]
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            before = await _start(client, ready)
            vor = await _source(
                client,
                ready,
                source_class="CUSTOMER_VOR",
                title="ВОР Заказчика",
                document_revision_id=str(revision),
            )
            quantity = await client.post(
                f"{API}/projects/{ready.id}/facts",
                json={
                    "source_id": vor,
                    "fact_type": "system.main_diameter",
                    "subject": {"building": "1", "discipline": "VK", "system_code": "В1"},
                    "value": {"kind": "NUMBER", "value": "50", "unit": "mm"},
                    "method": "TABLE_EXPLICIT",
                    "evidence": evidence,
                },
            )
            material = await _fact(
                client,
                ready,
                vor,
                "system.pipe_material",
                {"building": "1", "discipline": "VK", "system_code": "В1"},
                {"kind": "TEXT", "value": "полипропилен"},
                method="TABLE_EXPLICIT",
                evidence=evidence,
            )
            after = await _start(client, ready)
        assert quantity.status_code == 422
        assert material["calculation_eligible"] is False
        assert {item["source_class"] for item in after["snapshot"]["items"]} == {"MANUAL"}
        vor_ids = {material["id"]}
        assert not vor_ids & {item["fact_id"] for item in after["snapshot"]["items"]}
        assert after["result_sha256"] == before["result_sha256"]

    @pytest.mark.usefixtures("calc_enabled")
    async def test_t07_t09_t10_draft_rejected_deprecated_rules_are_not_used(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        project = await _project(db_session, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _demo_facts(client, project)
        await _rules(build_api, workspace_id, other_user.id, approve=False)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            drafts = await _start(client, project)
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            await client.post(
                f"{API}/rules/test.geometry.vertical_length/versions/1/reject",
                json={"comment": "Тест: отклонено."},
            )
            await client.post(
                f"{API}/rules/test.geometry.total_length/versions/1/approve", json=APPROVE
            )
            await client.post(
                f"{API}/rules/test.geometry.total_length/versions/1/deprecate",
                json={"comment": "Тест: выведено."},
            )
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            decided = await _start(client, project)
        assert drafts["status"] == "BLOCKED"
        # Шаг допущения в EXPECTED не применяется — его черновик причиной не становится.
        assert {item["rule_key"]: item["code"] for item in drafts["blocking_reasons"]} == {
            "test.geometry.vertical_length": "RULE_NOT_APPROVED",
            "test.geometry.total_length": "RULE_NOT_APPROVED",
        }
        assert all("v1 DRAFT" in item["message"] for item in drafts["blocking_reasons"])
        messages = {item["rule_key"]: item["message"] for item in decided["blocking_reasons"]}
        assert "v1 REJECTED" in messages["test.geometry.vertical_length"]
        assert "v1 DEPRECATED" in messages["test.geometry.total_length"]

        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await client.post(
                f"{API}/rules/test.geometry.vertical_length/versions",
                json={"change_reason": "Тест: новая редакция после отклонения."},
            )
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            await client.post(
                f"{API}/rules/test.geometry.vertical_length/versions/2/approve", json=APPROVE
            )
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            deprecated = await _start(client, project)
        # Отклонённая v1 заменена утверждённой v2; устаревшая total_length@1 — по-прежнему нет.
        assert [item["rule_key"] for item in deprecated["blocking_reasons"]] == [
            "test.geometry.total_length"
        ]
        assert "v1 DEPRECATED" in deprecated["blocking_reasons"][0]["message"]

    @pytest.mark.usefixtures("calc_enabled")
    async def test_t08_d_legacy_is_never_a_fallback(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Сценарий D: правил нет — запуск блокирован, коэффициенты старого портала не берутся.

        Даже черновик по мотивам старого правила под нужным ключом не идёт в расчёт.
        """
        project = await _project(db_session, workspace_id)
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _demo_facts(client, project)
            none = await _start(client, project)
            content = vertical_length_rule()
            draft = await client.post(
                f"{API}/legacy-rules/LEG-VK-001/drafts",
                json={
                    "rule_key": "test.geometry.vertical_length",
                    "rule_type": "GEOMETRY",
                    "discipline": "VK",
                    "applicability": content["applicability"],
                    "outputs": content["outputs"],
                },
            )
            from_legacy = await _start(client, project)
        assert set(_codes(none)) == {"RULE_NOT_FOUND"}
        assert draft.status_code == 201
        reasons = {item["rule_key"]: item["code"] for item in from_legacy["blocking_reasons"]}
        assert reasons["test.geometry.vertical_length"] == "RULE_NOT_APPROVED"
        assert from_legacy["rule_bindings"] == []


# ----------------------------------------------------- версии, факты, повтор (T11–T13, T28)


class TestHistory:
    async def test_e_t11_t12_t28_new_rule_version_keeps_old_run(
        self,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        other_user: UserIdentity,
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            first = await _start(client, ready, scenario="TENDER_SAFE")
            await client.post(
                f"{API}/rules/test.tender.length_reserve/versions",
                json={"change_reason": "Тест: запас 10 %.", "content": reserve_rule("1.1")},
            )
        async with build_api(_as(Role.REVIEWER, workspace_id, other_user.id)) as client:
            approved = await client.post(
                f"{API}/rules/test.tender.length_reserve/versions/2/approve", json=APPROVE
            )
        assert approved.status_code == 200, approved.text
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            second = await _start(client, ready, scenario="TENDER_SAFE")
            old = (await client.get(f"{API}/runs/{first['id']}")).json()
            replay = (await client.post(f"{API}/runs/{first['id']}/replay")).json()
            diff = (
                await client.get(
                    f"{API}/runs/compare", params={"base": first["id"], "other": second["id"]}
                )
            ).json()

        def reserve(run: dict[str, Any]) -> dict[str, Any]:
            return next(
                item for item in run["rule_bindings"] if item["step_key"] == "total_with_reserve"
            )

        assert reserve(first)["version"] == 1
        assert reserve(second)["version"] == 2
        assert _results(second)["demo.total_length"] == "174.3"
        assert old == first
        assert _results(old)["demo.total_length"] == "169.5"
        assert replay == {
            "run_id": first["id"],
            "reproducible": True,
            "original_result_sha256": first["result_sha256"],
            "replay_result_sha256": first["result_sha256"],
            "problems": [],
        }
        assert [item["step_key"] for item in diff["rules"]] == ["total_with_reserve"]
        [changed] = diff["invalidated_steps"]
        assert changed["step_key"] == "total_with_reserve"
        assert "другая версия правила" in changed["causes"]

    async def test_f_t13_fact_change_keeps_old_snapshot(
        self,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        """Сценарий F: этажность исправлена 24 → 25; старый запуск остаётся 79,2 м."""
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            first = await _start(client, ready)
            floors = next(
                item
                for item in first["snapshot"]["items"]
                if item["fact_type"] == "building.floors_above_ground"
            )
            fact = (await client.get(f"{API}/facts/{floors['fact_id']}")).json()
            await _fact(
                client,
                ready,
                fact["source_id"],
                "building.floors_above_ground",
                {"building": "1"},
                {"kind": "COUNT", "value": 25},
            )
            second = await _start(client, ready)
            old = (await client.get(f"{API}/runs/{first['id']}")).json()
            replay = (await client.post(f"{API}/runs/{first['id']}/replay")).json()
            diff = (
                await client.get(
                    f"{API}/runs/compare", params={"base": first["id"], "other": second["id"]}
                )
            ).json()
        assert _results(old)["demo.vertical_length"] == "79.2"
        assert _results(second)["demo.vertical_length"] == "82.5"
        assert old["snapshot"] == first["snapshot"]
        assert replay["reproducible"] is True
        [fact_diff] = diff["facts"]
        assert fact_diff["base_value"]["value"] == 24 and fact_diff["other_value"]["value"] == 25

    async def test_reuse_is_visible_and_scoped_to_project(
        self,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            first = await _start(client, ready)
            second = await _start(client, ready)
        assert [step["status"] for step in second["steps"]] == ["REUSED", "REUSED", "NOT_APPLIED"]
        assert {step["reused_from_run_id"] for step in second["steps"][:2]} == {first["id"]}
        assert second["result_sha256"] == first["result_sha256"]

    async def test_t28_replay_refuses_changed_semantics(
        self,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Под тем же ключом другой алгоритм — повтор честно отказывает, а не пересчитывает."""
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            run = await _start(client, ready)
        spec = HANDLERS["test.vertical_length.v1"]
        changed = replace(
            spec,
            golden=(GoldenCase({"floor_height": "1", "floors": "2"}, {}, {"length": "2"}),),
        )
        monkeypatch.setattr(
            runs, "HANDLERS", MappingProxyType({**HANDLERS, spec.implementation_key: changed})
        )
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            refused = (await client.post(f"{API}/runs/{run['id']}/replay")).json()
        monkeypatch.setattr(
            runs,
            "HANDLERS",
            MappingProxyType(
                {k: v for k, v in HANDLERS.items() if k != "test.multiply_by_count.v1"}
            ),
        )
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            missing = (await client.post(f"{API}/runs/{run['id']}/replay")).json()
        assert refused["reproducible"] is False
        assert any("семантика реализации test.vertical_length.v1" in p for p in refused["problems"])
        assert any("test.multiply_by_count.v1 больше нет" in p for p in missing["problems"])

    async def test_failed_run_is_recorded_not_500(
        self,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(context: HandlerContext) -> HandlerResult:
            raise RuntimeError("ошибка программы в обработчике")

        spec = replace(HANDLERS["test.vertical_length.v1"], compute=broken)
        monkeypatch.setattr(
            runs, "HANDLERS", MappingProxyType({**HANDLERS, spec.implementation_key: spec})
        )
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.post(f"{API}/projects/{ready.id}/runs", json=_body())
        assert response.status_code == 201
        run = response.json()
        assert run["status"] == "FAILED"
        assert run["failure"] == {
            "step_key": "vertical_length",
            "error": "RuntimeError",
            "message": "ошибка программы в обработчике",
        }
        assert run["results"] == []


# -------------------------------------------------------- неизменяемость и изоляция (T25, T19)


class TestImmutability:
    async def test_t25_finished_run_cannot_change(
        self,
        db_session: AsyncSession,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            run = await _start(client, ready)
        run_id = uuid.UUID(run["id"])
        attempts = (
            update(CalcRun).where(CalcRun.id == run_id).values(snapshot={}),
            update(CalcRun).where(CalcRun.id == run_id).values(rule_bindings=[]),
            update(CalcRunStep).where(CalcRunStep.run_id == run_id).values(outputs=[]),
            update(CalcRunStep).where(CalcRunStep.run_id == run_id).values(inputs=[]),
            update(CalcRunResult).where(CalcRunResult.run_id == run_id).values(value="1"),
            delete(CalcRunResult).where(CalcRunResult.run_id == run_id),
            delete(CalcRun).where(CalcRun.id == run_id),
        )
        for statement in attempts:
            with pytest.raises(DBAPIError, match="append-only"):
                await db_session.execute(statement.execution_options(synchronize_session=False))
            await db_session.rollback()

        stored = await db_session.get(CalcRun, run_id)
        assert stored is not None
        stored.status = CalcRunStatus.FAILED
        with pytest.raises(DBAPIError, match="append-only"):
            await db_session.flush()
        await db_session.rollback()

        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            again = (await client.get(f"{API}/runs/{run['id']}")).json()
            put = await client.put(f"{API}/runs/{run['id']}", json={})
            removed = await client.delete(f"{API}/runs/{run['id']}")
        assert again == run
        assert put.status_code == removed.status_code == 405

    async def test_project_deletion_cascades(
        self,
        db_session: AsyncSession,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            await _start(client, ready)
        await db_session.execute(text("delete from projects where id = :id"), {"id": ready.id})
        await db_session.commit()
        assert await db_session.scalar(select(func.count()).select_from(CalcRun)) == 0
        assert await db_session.scalar(select(func.count()).select_from(CalcRunStep)) == 0

    async def test_t18_t19_runs_do_not_touch_registries(
        self,
        db_session: AsyncSession,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        async def state() -> tuple[Any, ...]:
            facts = (
                await db_session.execute(
                    select(CalcFact.id, CalcFact.status, CalcFact.value, CalcFact.version).order_by(
                        CalcFact.id
                    )
                )
            ).all()
            rules = (
                await db_session.execute(
                    select(
                        CalcRuleVersion.id, CalcRuleVersion.status, CalcRuleVersion.content_sha256
                    ).order_by(CalcRuleVersion.id)
                )
            ).all()
            reviews = await db_session.scalar(select(func.count()).select_from(CalcRuleReview))
            return tuple(facts), tuple(rules), reviews

        project_id = ready.id
        before = await state()
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            for scenario in ("MINIMUM", "EXPECTED", "TENDER_SAFE"):
                await _start(client, ready, scenario=scenario)
                await client.post(
                    f"{API}/projects/{project_id}/runs/validate", json=_body(scenario)
                )
        assert await state() == before


# ----------------------------------------------------- идемпотентность и конкурентность


class TestConcurrency:
    async def test_t27_idempotency_key(
        self,
        db_session: AsyncSession,
        ready: Project,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        body = _body(idempotency_key="retry-0001")
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            first = await client.post(f"{API}/projects/{ready.id}/runs", json=body)
            again = await client.post(f"{API}/projects/{ready.id}/runs", json=body)
            other = await client.post(
                f"{API}/projects/{ready.id}/runs",
                json=_body("MINIMUM", idempotency_key="retry-0001"),
            )
        assert (first.status_code, again.status_code) == (201, 200)
        assert again.json()["id"] == first.json()["id"]
        assert other.status_code == 409
        assert other.json()["detail"]["code"] == "CALC_RUN_IDEMPOTENCY_CONFLICT"
        assert await db_session.scalar(select(func.count()).select_from(CalcRun)) == 1

    async def test_t26_t27_parallel_runs_are_isolated(
        self,
        db_engine: AsyncEngine,
        db_session: AsyncSession,
        ready: Project,
        workspace_id: uuid.UUID,
    ) -> None:
        """Два разных запуска одновременно — оба свои; два одинаковых по ключу — один."""
        factory = async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)

        async def start(payload: CalcRunCreate) -> tuple[uuid.UUID, str]:
            async with factory() as session:
                run, _ = await runs.start_run(
                    session,
                    workspace_id=workspace_id,
                    project_id=ready.id,
                    payload=payload,
                    author=None,
                )
                await session.commit()
                return run.id, run.status.value

        payloads = [
            CalcRunCreate.model_validate(_body(item)) for item in ("EXPECTED", "TENDER_SAFE")
        ]
        results = await asyncio.gather(*(start(item) for item in payloads))
        assert [status for _, status in results] == ["SUCCEEDED", "SUCCEEDED"]
        values = (
            await db_session.execute(
                select(CalcRunResult.run_id, CalcRunResult.value).where(
                    CalcRunResult.result_key == "demo.total_length"
                )
            )
        ).all()
        by_run = dict(values)
        assert by_run[results[0][0]] == "158.4"
        assert by_run[results[1][0]] == "169.5"

        same = CalcRunCreate.model_validate(_body(idempotency_key="parallel-0001"))
        twins = await asyncio.gather(start(same), start(same))
        assert twins[0][0] == twins[1][0]
        count = await db_session.scalar(
            select(func.count())
            .select_from(CalcRun)
            .where(CalcRun.idempotency_key == "parallel-0001")
        )
        assert count == 1
