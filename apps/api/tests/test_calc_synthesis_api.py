"""Синтез структуры через базу и HTTP (ADR-0030, PROMPT 05).

Настоящий путь: факты — через API реестра фактов, правила `test.*` — утверждение вторым
человеком, расчёт `test.riser_demand@1` — через API ядра, синтез `test.riser_structure@1` —
через API синтеза. Проверяются неизменяемость, повтор, объяснение до факта и свидетельства,
изоляция реестров, ВОР Заказчика, решения инженера и блокировки.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.domain import (
    DocumentKind,
    GeometryStatus,
    OverrideScope,
    ProcessingStatus,
    Role,
)
from app.models import (
    CalcFact,
    CalcRuleReview,
    CalcRuleVersion,
    CalcRun,
    CalcSynthesisDecision,
    CalcSynthesisRun,
    Document,
    FeatureFlagOverride,
    Project,
    UserIdentity,
)
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services.calc.synthesis import demo_rules
from app.services.calc.synthesis import runs as synthesis_runs
from app.services.calc.synthesis.catalog import SYNTHESIZERS
from tests.conftest import make_context

API = "/api/v1/calc"
SCOPE = {"building": "1", "floor": "1..24", "discipline": "VK", "system_code": "В1"}
SYSTEM = {"building": "1", "discipline": "VK", "system_code": "В1"}
APPROVE = {"comment": "Проверено по тестовой фикстуре синтеза.", "legacy_review": []}
CONTENTS = {
    "riser_range": demo_rules.riser_range,
    "topology": demo_rules.riser_topology,
    "selection": demo_rules.riser_choice,
    "reserve": demo_rules.riser_reserve,
}


@pytest.fixture
async def calc_enabled(db_session: AsyncSession) -> None:
    db_session.add(
        FeatureFlagOverride(
            flag_key="calc.portal",
            scope=OverrideScope.SYSTEM,
            workspace_id=None,
            enabled=True,
            reason="тесты синтеза",
        )
    )
    await db_session.commit()


def _as(role: Role, workspace_id: uuid.UUID, user_id: uuid.UUID | None = None) -> AuthContext:
    if user_id is None:
        return make_context(role, workspace_id=workspace_id)
    return make_context(role, workspace_id=workspace_id, user_id=user_id)


class Demo:
    """Проект демо-синтеза: факты, правила, запуски — через API."""

    def __init__(
        self,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        project: Project,
    ) -> None:
        self.build_api = build_api
        self.workspace_id = workspace_id
        self.reviewer_id = reviewer_id
        self.project = project
        self.source_id = ""

    def engineer(self) -> AsyncClient:
        return self.build_api(_as(Role.ENGINEER, self.workspace_id))

    def reviewer(self) -> AsyncClient:
        return self.build_api(_as(Role.REVIEWER, self.workspace_id, self.reviewer_id))

    async def fact(self, fact_type: str, subject: dict[str, str], count: int) -> dict[str, Any]:
        async with self.engineer() as client:
            if not self.source_id:
                source = await client.post(
                    f"{API}/projects/{self.project.id}/sources",
                    json={"source_class": "MANUAL", "title": "Инженер"},
                )
                self.source_id = source.json()["id"]
            response = await client.post(
                f"{API}/projects/{self.project.id}/facts",
                json={
                    "source_id": self.source_id,
                    "fact_type": fact_type,
                    "subject": subject,
                    "value": {"kind": "COUNT", "value": count},
                    "method": "MANUAL",
                    "note": "по листу проекта",
                },
            )
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    async def facts(self, *, apartments: int = 96, shafts: bool = True) -> None:
        await self.fact("building.apartments_total", {"building": "1"}, apartments)
        await self.fact("system.inlets_count", SYSTEM, 1)
        await self.fact("building.floors_above_ground", {"building": "1"}, 24)
        if shafts:
            await self.fact("floor.shafts_count", {"building": "1", "floor": "1..24"}, 2)

    async def rule(self, name: str, *, approve: bool = True, **content: Any) -> None:
        key = demo_rules.RULE_KEYS[name]
        async with self.engineer() as client:
            response = await client.post(
                f"{API}/rules", json={"rule_key": key, "content": CONTENTS[name](**content)}
            )
        assert response.status_code == 201, response.text
        if approve:
            async with self.reviewer() as client:
                approved = await client.post(f"{API}/rules/{key}/versions/1/approve", json=APPROVE)
            assert approved.status_code == 200, approved.text

    async def calculate(self, scenario: str = "EXPECTED", **extra: Any) -> dict[str, Any]:
        async with self.engineer() as client:
            response = await client.post(
                f"{API}/projects/{self.project.id}/runs",
                json={
                    "calculator_id": "test.riser_demand",
                    "calculator_version": 1,
                    "scenario": scenario,
                    "scope": SCOPE,
                    **extra,
                },
            )
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    async def synthesize(self, calculation_id: str, **extra: Any) -> dict[str, Any]:
        async with self.engineer() as client:
            response = await client.post(
                f"{API}/projects/{self.project.id}/synthesis-runs",
                json={
                    "calculation_run_id": calculation_id,
                    "synthesizer_id": "test.riser_structure",
                    "synthesizer_version": 1,
                    **extra,
                },
            )
        assert response.status_code in {200, 201}, response.text
        result: dict[str, Any] = response.json()
        return result

    async def post(self, path: str) -> Any:
        async with self.engineer() as client:
            response = await client.post(f"{API}{path}")
        assert response.status_code == 200, response.text
        return response.json()

    async def get(self, path: str, **params: Any) -> Any:
        async with self.engineer() as client:
            response = await client.get(f"{API}{path}", params=params)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
async def demo(
    db_session: AsyncSession,
    build_api: Callable[..., AsyncClient],
    workspace_id: uuid.UUID,
    other_user: UserIdentity,
    calc_enabled: None,
) -> Demo:
    project = await projects_service.create_project(
        db_session, workspace_id=workspace_id, name="ЖК"
    )
    await db_session.commit()
    result = Demo(build_api, workspace_id, other_user.id, project)
    await result.facts()
    await result.rule("riser_range")
    await result.rule("topology")
    return result


def _node(graph: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(node for node in graph["nodes"] if node["id"] == node_id)


# --------------------------------------------------------------------------- доступ


class TestAccess:
    async def test_t32_closed_by_default(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.ENGINEER, workspace_id)) as client:
            response = await client.get(f"{API}/synthesizers")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "FEATURE_DISABLED"

    @pytest.mark.usefixtures("calc_enabled")
    async def test_t28_demo_hidden_from_user_lists(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        async with build_api(_as(Role.VIEWER, workspace_id)) as client:
            hidden = (await client.get(f"{API}/synthesizers")).json()
            debug = (await client.get(f"{API}/synthesizers", params={"include_demo": True})).json()
            calculators = (await client.get(f"{API}/calculators")).json()
        assert all(item["kind"] == "PRODUCTION" for item in (*hidden, *calculators))
        [synthesizer] = [item for item in debug if item["kind"] == "DEMO"]
        assert synthesizer["kind"] == "DEMO"
        assert "не синтез ВК" in synthesizer["title"]
        assert synthesizer["calculator_id"] == "test.riser_demand"

    async def test_roles(self, demo: Demo) -> None:
        calculation = await demo.calculate()
        async with demo.build_api(_as(Role.VIEWER, demo.workspace_id)) as client:
            response = await client.post(
                f"{API}/projects/{demo.project.id}/synthesis-runs",
                json={
                    "calculation_run_id": calculation["id"],
                    "synthesizer_id": "test.riser_structure",
                    "synthesizer_version": 1,
                },
            )
        assert response.status_code == 403


# -------------------------------------------------------------------------- синтез


class TestSynthesis:
    async def test_end_to_end_partial_structure(self, demo: Demo) -> None:
        calculation = await demo.calculate()
        [step] = calculation["steps"]
        assert [item["target"] for item in step["roundings"]] == ["risers_min", "risers_max"]
        assert step["roundings"][1]["before"] == "4.8"
        run = await demo.synthesize(calculation["id"])
        graph = await demo.get(f"/synthesis-runs/{run['id']}/graph")
        variants = await demo.get(f"/synthesis-runs/{run['id']}/variants")
        unresolved = await demo.get(f"/synthesis-runs/{run['id']}/unresolved")
        listed = await demo.get(f"/projects/{demo.project.id}/synthesis-runs")
        assert run["status"] == "PARTIAL"
        assert run["scenario"] == "EXPECTED"
        assert run["calculation_run_id"] == calculation["id"]
        risers = _node(graph, "risers")
        assert (risers["cardinality"]["min"], risers["cardinality"]["max"]) == (4, 5)
        assert risers["cardinality"]["selected"] is None
        assert _node(graph, "typical_floors")["multiplicity"] == 24
        assert [item["key"] for item in variants] == ["risers_4", "risers_5"]
        assert {item["key"] for item in unresolved} == {
            "risers.count",
            "risers.placement",
            "supply_main.route",
        }
        assert listed[0]["nodes_count"] == 5
        assert run["rule_bindings"][0]["rule_key"] == demo_rules.RULE_KEYS["topology"]

    async def test_t24_trace_reaches_calculation_fact_and_evidence(self, demo: Demo) -> None:
        run = await demo.synthesize((await demo.calculate())["id"])
        risers = await demo.get(f"/synthesis-runs/{run['id']}/trace", element_id="risers")
        inlet = await demo.get(f"/synthesis-runs/{run['id']}/trace", element_id="inlet")
        branch = await demo.get(f"/synthesis-runs/{run['id']}/trace", element_id="floor_branch")
        edge = await demo.get(f"/synthesis-runs/{run['id']}/trace", element_id="supply_main")
        async with demo.engineer() as client:
            missing = await client.get(
                f"{API}/synthesis-runs/{run['id']}/trace", params={"element_id": "nope"}
            )
        assert missing.status_code == 404
        assert risers["provenance"] == "CALCULATED"
        result = next(
            child for child in risers["root"]["children"] if child["kind"] == "CALCULATION_RESULT"
        )
        calculation = result["calculation"]
        assert calculation is not None
        assert "96 кв. / 24 кв. на стояк" in calculation["text"]

        def kinds(node: dict[str, Any]) -> set[str]:
            found = {node["kind"]}
            for child in node["children"]:
                found |= kinds(child)
            return found

        assert {"STEP", "RULE", "FACT", "EVIDENCE"} <= kinds(calculation["root"])
        assert inlet["provenance"] == "OBSERVED"
        fact = next(child for child in inlet["root"]["children"] if child["kind"] == "FACT")
        assert [child["kind"] for child in fact["children"]] == ["EVIDENCE"]
        assert branch["provenance"] == "SYNTHESIZED"
        assert any(child["kind"] == "RULE" for child in branch["root"]["children"])
        assert edge["provenance"] == "SYNTHESIZED"

    async def test_d_approved_selection_rule(self, demo: Demo) -> None:
        await demo.rule("selection")
        run = await demo.synthesize((await demo.calculate())["id"])
        graph = await demo.get(f"/synthesis-runs/{run['id']}/graph")
        risers = _node(graph, "risers")
        assert risers["cardinality"]["selected"] == 5
        assert risers["cardinality"]["selection"]["rule"]["version"] == 1
        trace = await demo.get(f"/synthesis-runs/{run['id']}/trace", element_id="risers")
        decision = next(c for c in trace["root"]["children"] if c["kind"] == "DECISION")
        assert decision["children"][0]["key"] == f"{demo_rules.RULE_KEYS['selection']}@1"

    async def test_e_t21_tender_safe_marks_assumed(self, demo: Demo) -> None:
        await demo.rule("reserve")
        tender = await demo.synthesize((await demo.calculate("TENDER_SAFE"))["id"])
        expected = await demo.synthesize((await demo.calculate("EXPECTED"))["id"])
        tender_graph = await demo.get(f"/synthesis-runs/{tender['id']}/graph")
        expected_graph = await demo.get(f"/synthesis-runs/{expected['id']}/graph")
        assumed = {
            item["id"]
            for item in (*tender_graph["nodes"], *tender_graph["edges"])
            if item["provenance"] == "ASSUMED"
        }
        assert assumed == {"reserve_risers", "reserve_supply"}
        assert tender["assumptions"][0]["rule"]["rule_type"] == "TENDER_ASSUMPTION"
        assert all(
            item["provenance"] != "ASSUMED"
            for item in (*expected_graph["nodes"], *expected_graph["edges"])
        )
        trace = await demo.get(f"/synthesis-runs/{tender['id']}/trace", element_id="reserve_risers")
        assumption = next(c for c in trace["root"]["children"] if c["kind"] == "ASSUMPTION")
        assert "решение: Тестовый владелец" in assumption["children"][0]["text"]

    async def test_t20_tender_safe_without_assumption_warns(self, demo: Demo) -> None:
        run = await demo.synthesize((await demo.calculate("TENDER_SAFE"))["id"])
        assert any("TENDER_SAFE = EXPECTED" in item for item in run["warnings"])
        assert run["assumptions"] == []


# ------------------------------------------------------- история и повтор (T03–T05, T26)


class TestHistory:
    async def test_t03_t26_fact_change_keeps_old_run(self, demo: Demo) -> None:
        calculation = await demo.calculate()
        first = await demo.synthesize(calculation["id"])
        before = await demo.get(f"/synthesis-runs/{first['id']}/graph")
        await demo.fact("building.floors_above_ground", {"building": "1"}, 25)
        second = await demo.synthesize(calculation["id"])
        after = await demo.get(f"/synthesis-runs/{first['id']}/graph")
        replay = await demo.post(f"/synthesis-runs/{first['id']}/replay")
        diff = await demo.get("/synthesis-runs/compare", base=first["id"], other=second["id"])
        assert after == before
        assert _node(before, "typical_floors")["multiplicity"] == 24
        new_graph = await demo.get(f"/synthesis-runs/{second['id']}/graph")
        assert _node(new_graph, "typical_floors")["multiplicity"] == 25
        assert replay["reproducible"] is True
        assert replay["replay_graph_sha256"] == first["graph_sha256"]
        changed = next(item for item in diff["nodes"] if item["element_id"] == "typical_floors")
        assert "multiplicity" in changed["fields"]
        assert diff["same_calculation"] is True

    async def test_t04_new_rule_version_keeps_old_run(self, demo: Demo) -> None:
        calculation = await demo.calculate()
        first = await demo.synthesize(calculation["id"])
        key = demo_rules.RULE_KEYS["topology"]
        changed = demo_rules.riser_topology()
        changed["parameters"][0]["value"] = "2"
        async with demo.engineer() as client:
            await client.post(
                f"{API}/rules/{key}/versions",
                json={"change_reason": "Тест: две ветви на этаже.", "content": changed},
            )
        async with demo.reviewer() as client:
            approved = await client.post(f"{API}/rules/{key}/versions/2/approve", json=APPROVE)
        assert approved.status_code == 200, approved.text
        second = await demo.synthesize(calculation["id"])
        old = await demo.get(f"/synthesis-runs/{first['id']}/graph")
        new = await demo.get(f"/synthesis-runs/{second['id']}/graph")
        replay = await demo.post(f"/synthesis-runs/{first['id']}/replay")
        assert _node(old, "floor_branch")["cardinality"]["min"] == 1
        assert _node(new, "floor_branch")["cardinality"]["min"] == 2
        assert first["rule_bindings"][0]["version"] == 1
        assert second["rule_bindings"][0]["version"] == 2
        assert replay["reproducible"] is True

    async def test_t05_new_calculation_needs_new_synthesis(self, demo: Demo) -> None:
        first_calc = await demo.calculate()
        first = await demo.synthesize(first_calc["id"])
        await demo.fact("building.apartments_total", {"building": "1"}, 100)
        second_calc = await demo.calculate()
        second = await demo.synthesize(second_calc["id"])
        old = await demo.get(f"/synthesis-runs/{first['id']}/graph")
        new = await demo.get(f"/synthesis-runs/{second['id']}/graph")
        # Новый расчёт: 100 кв. → 5 стояков ровно; старый синтез по-прежнему 4–5.
        assert (
            _node(old, "risers")["cardinality"]["min"],
            _node(old, "risers")["cardinality"]["max"],
        ) == (4, 5)
        assert _node(new, "risers")["cardinality"]["min"] == 5
        assert _node(new, "risers")["cardinality"]["max"] == 5
        assert first["calculation_run_id"] == first_calc["id"]

    async def test_t27_replay_refuses_changed_implementation(
        self, demo: Demo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = await demo.synthesize((await demo.calculate())["id"])
        key = ("test.riser_structure", 1)
        changed = replace(SYNTHESIZERS[key], golden=(("range_expected", "1" * 64),))
        monkeypatch.setattr(
            synthesis_runs, "SYNTHESIZERS", MappingProxyType({**SYNTHESIZERS, key: changed})
        )
        replay = await demo.post(f"/synthesis-runs/{run['id']}/replay")
        assert replay["reproducible"] is False
        assert any("реализация test.riser_structure@1 изменилась" in p for p in replay["problems"])


# ------------------------------------------------------- решения инженера (§45–47, T29)


class TestDecisions:
    async def test_decision_feeds_new_run_and_never_becomes_a_fact(
        self, db_session: AsyncSession, demo: Demo
    ) -> None:
        calculation = await demo.calculate()
        first = await demo.synthesize(calculation["id"])
        facts_before = await db_session.scalar(select(func.count()).select_from(CalcFact))
        async with demo.reviewer() as client:
            decided = await client.post(
                f"{API}/synthesis-runs/{first['id']}/decisions",
                json={
                    "node_id": "risers",
                    "selected_count": 5,
                    "variant_key": "risers_5",
                    "comment": "Пять стояков — по компоновке секций.",
                },
            )
            outside = await client.post(
                f"{API}/synthesis-runs/{first['id']}/decisions",
                json={"node_id": "risers", "selected_count": 7, "comment": "Семь стояков сразу."},
            )
            exact = await client.post(
                f"{API}/synthesis-runs/{first['id']}/decisions",
                json={"node_id": "inlet", "selected_count": 1, "comment": "Ввод один, как есть."},
            )
        async with demo.build_api(_as(Role.VIEWER, demo.workspace_id)) as client:
            viewer = await client.post(
                f"{API}/synthesis-runs/{first['id']}/decisions",
                json={"node_id": "risers", "selected_count": 4, "comment": "Четыре стояка."},
            )
        assert decided.status_code == 201, decided.text
        decision = decided.json()
        assert decision["alternatives"] == [4, 5]
        assert outside.status_code == exact.status_code == 422
        assert viewer.status_code == 403

        second = await demo.synthesize(calculation["id"], decision_ids=[decision["id"]])
        graph = await demo.get(f"/synthesis-runs/{second['id']}/graph")
        risers = _node(graph, "risers")
        assert risers["cardinality"]["selected"] == 5
        assert risers["cardinality"]["selection"]["source"] == "HUMAN_DECISION"
        assert risers["provenance"] == "CALCULATED"
        assert [item["id"] for item in second["applied_decisions"]] == [decision["id"]]
        old = await demo.get(f"/synthesis-runs/{first['id']}")
        assert [item["id"] for item in old["decisions"]] == [decision["id"]]
        assert old["unresolved_count"] == first["unresolved_count"]
        # Гипотеза и решение не стали фактами объекта (T29).
        assert await db_session.scalar(select(func.count()).select_from(CalcFact)) == facts_before

        async with demo.engineer() as client:
            foreign = await client.post(
                f"{API}/projects/{demo.project.id}/synthesis-runs",
                json={
                    "calculation_run_id": calculation["id"],
                    "synthesizer_id": "test.riser_structure",
                    "synthesizer_version": 1,
                    "decision_ids": [str(uuid.uuid4())],
                },
            )
        assert foreign.status_code == 404


# ------------------------------------------------------------- блокировки и изоляция


class TestBlocked:
    async def test_calculation_must_fit_synthesizer(self, demo: Demo) -> None:
        async with demo.engineer() as client:
            other = await client.post(
                f"{API}/projects/{demo.project.id}/runs",
                json={
                    "calculator_id": "test.vertical_length",
                    "calculator_version": 1,
                    "scenario": "EXPECTED",
                    "scope": SCOPE,
                },
            )
            unknown = await client.post(
                f"{API}/projects/{demo.project.id}/synthesis-runs",
                json={
                    "calculation_run_id": str(uuid.uuid4()),
                    "synthesizer_id": "test.riser_structure",
                    "synthesizer_version": 1,
                },
            )
        assert unknown.status_code == 404
        blocked_calc = other.json()
        assert blocked_calc["status"] == "BLOCKED"
        run = await demo.synthesize(blocked_calc["id"])
        assert run["status"] == "BLOCKED"
        assert run["blocking_reasons"][0]["code"] == "CALCULATION_NOT_USABLE"
        assert run["graph_sha256"] is None and run["nodes_count"] == 0

    async def test_t09_missing_structure_fact_blocks(
        self, demo: Demo, db_session: AsyncSession
    ) -> None:
        calculation = await demo.calculate()
        inlet = await db_session.scalar(
            select(CalcFact).where(CalcFact.fact_type == "system.inlets_count")
        )
        assert inlet is not None
        async with demo.reviewer() as client:
            await client.post(
                f"{API}/facts/{inlet.id}/review",
                json={"status": "REJECTED", "comment": "ввод не подтверждён"},
            )
        run = await demo.synthesize(calculation["id"])
        assert run["status"] == "BLOCKED"
        assert [item["code"] for item in run["blocking_reasons"]] == ["FACT_MISSING"]

    async def test_b_t06_customer_vor_does_not_change_structure(
        self, db_session: AsyncSession, demo: Demo
    ) -> None:
        """Сценарий B: «5 стояков» из ВОР — в реестр не принимается, структура та же."""
        calculation = await demo.calculate()
        first = await demo.synthesize(calculation["id"])
        document = Document(
            project_id=demo.project.id, display_name="ВОР.pdf", document_kind=DocumentKind.PDF
        )
        db_session.add(document)
        await db_session.flush()
        revision = await documents_service.create_revision(
            db_session,
            document=document,
            revision_id=uuid.uuid4(),
            source_filename="ВОР.pdf",
            source_mime="application/pdf",
            source_size=1024,
            source_sha256="e" * 64,
            storage_key=f"revisions/{uuid.uuid4()}/source.pdf",
            processing_status=ProcessingStatus.READY,
            geometry_status=GeometryStatus.READY,
        )
        await db_session.commit()
        evidence = [{"kind": "DOCUMENT_FRAGMENT", "document_revision_id": str(revision.id)}]
        async with demo.engineer() as client:
            vor = await client.post(
                f"{API}/projects/{demo.project.id}/sources",
                json={
                    "source_class": "CUSTOMER_VOR",
                    "title": "ВОР Заказчика",
                    "document_revision_id": str(revision.id),
                },
            )
            risers = await client.post(
                f"{API}/projects/{demo.project.id}/facts",
                json={
                    "source_id": vor.json()["id"],
                    "fact_type": "system.risers_count",
                    "subject": SYSTEM,
                    "value": {"kind": "COUNT", "value": 5},
                    "method": "TABLE_EXPLICIT",
                    "evidence": evidence,
                },
            )
        second = await demo.synthesize(calculation["id"])
        assert risers.status_code == 422
        assert second["graph_sha256"] == first["graph_sha256"]

    async def test_t07_t08_draft_or_legacy_rule_is_not_used(self, demo: Demo) -> None:
        """Черновик правила выбора (в т. ч. по мотивам старого портала) выбор не делает."""
        content = demo_rules.riser_choice()
        async with demo.engineer() as client:
            draft = await client.post(
                f"{API}/legacy-rules/LEG-VK-036/drafts",
                json={
                    "rule_key": demo_rules.RULE_KEYS["selection"],
                    "rule_type": "ENGINEERING",
                    "discipline": "VK",
                    "applicability": content["applicability"],
                    "outputs": content["outputs"],
                },
            )
        assert draft.status_code == 201, draft.text
        run = await demo.synthesize((await demo.calculate())["id"])
        graph = await demo.get(f"/synthesis-runs/{run['id']}/graph")
        assert _node(graph, "risers")["cardinality"]["selected"] is None
        assert all(
            item["rule_key"] != demo_rules.RULE_KEYS["selection"] for item in run["rule_bindings"]
        )

    async def test_idempotency(self, demo: Demo, db_session: AsyncSession) -> None:
        calculation = await demo.calculate()
        first = await demo.synthesize(calculation["id"], idempotency_key="synth-0001")
        again = await demo.synthesize(calculation["id"], idempotency_key="synth-0001")
        assert again["id"] == first["id"]
        assert await db_session.scalar(select(func.count()).select_from(CalcSynthesisRun)) == 1


class TestImmutability:
    async def test_t25_finished_run_and_decisions_cannot_change(
        self, db_session: AsyncSession, demo: Demo
    ) -> None:
        run = await demo.synthesize((await demo.calculate())["id"])
        async with demo.reviewer() as client:
            await client.post(
                f"{API}/synthesis-runs/{run['id']}/decisions",
                json={"node_id": "risers", "selected_count": 4, "comment": "Четыре стояка — тест."},
            )
        run_id = uuid.UUID(run["id"])
        for statement in (
            update(CalcSynthesisRun).where(CalcSynthesisRun.id == run_id).values(graph={}),
            update(CalcSynthesisRun).where(CalcSynthesisRun.id == run_id).values(variants=[]),
            update(CalcSynthesisRun).where(CalcSynthesisRun.id == run_id).values(rule_bindings=[]),
            delete(CalcSynthesisRun).where(CalcSynthesisRun.id == run_id),
            update(CalcSynthesisDecision).values(selected_count=5),
            delete(CalcSynthesisDecision),
        ):
            with pytest.raises(DBAPIError, match="append-only"):
                await db_session.execute(statement.execution_options(synchronize_session=False))
            await db_session.rollback()

    async def test_t29_t30_t31_registries_and_calculation_untouched(
        self, db_session: AsyncSession, demo: Demo
    ) -> None:
        await demo.rule("selection")
        await demo.rule("reserve")
        calculation = await demo.calculate("TENDER_SAFE")

        async def state() -> tuple[Any, ...]:
            facts = (
                await db_session.execute(
                    select(CalcFact.id, CalcFact.status, CalcFact.value).order_by(CalcFact.id)
                )
            ).all()
            rules = (
                await db_session.execute(
                    select(CalcRuleVersion.id, CalcRuleVersion.status).order_by(CalcRuleVersion.id)
                )
            ).all()
            reviews = await db_session.scalar(select(func.count()).select_from(CalcRuleReview))
            runs = await db_session.scalar(select(func.count()).select_from(CalcRun))
            return tuple(facts), tuple(rules), reviews, runs

        before = await state()
        calculation_before = await demo.get(f"/runs/{calculation['id']}")
        run = await demo.synthesize(calculation["id"])
        await demo.post(f"/synthesis-runs/{run['id']}/replay")
        async with demo.engineer() as client:
            await client.post(
                f"{API}/projects/{demo.project.id}/synthesis-runs/validate",
                json={
                    "calculation_run_id": calculation["id"],
                    "synthesizer_id": "test.riser_structure",
                    "synthesizer_version": 1,
                },
            )
        assert await state() == before
        assert await demo.get(f"/runs/{calculation['id']}") == calculation_before
