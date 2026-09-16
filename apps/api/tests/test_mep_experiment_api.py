"""PROMPT 11: сценарии страницы MEP-эксперимента за флагом — только синтетика и настоящий движок."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import FeatureCheck
from app.domain import OverrideScope, Role
from app.errors import ErrorCode
from app.main import create_app
from app.models import FeatureFlagOverride
from app.services.mep import scenarios as scenarios_service
from tests.conftest import clean_settings, make_context
from tests.mep_fixtures import load

FLAG = "mep_rd_hypothesis_v1"
BASE = "/api/v1/mep/experiment/scenarios"


@pytest.fixture
async def mep_enabled(db_session: AsyncSession) -> None:
    db_session.add(
        FeatureFlagOverride(
            flag_key=FLAG,
            scope=OverrideScope.SYSTEM,
            workspace_id=None,
            enabled=True,
            reason="тесты страницы MEP-эксперимента",
        )
    )
    await db_session.commit()


async def _get(build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID, path: str) -> Any:
    engineer = make_context(Role.ENGINEER, workspace_id=workspace_id)
    async with build_api(engineer, settings=clean_settings()) as client:
        return await client.get(path)


def _walk(routes: list[Any]) -> list[APIRoute]:
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found.extend(_walk(inner.routes))
    return found


def test_every_mep_route_checks_the_flag() -> None:
    routes = [r for r in _walk(create_app().routes) if "/mep/" in r.path]
    unguarded = [
        r.path
        for r in routes
        if not any(
            isinstance(d.call, FeatureCheck) and d.call.key == FLAG
            for d in r.dependant.dependencies
        )
    ]

    assert len(routes) == 2
    assert not unguarded


class TestFlagClosesThePage:
    async def test_disabled_flag_closes_the_experiment(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        for path in (BASE, f"{BASE}/complete"):
            response = await _get(build_api, workspace_id, path)
            assert response.status_code == 403
            assert response.json()["detail"]["code"] == ErrorCode.FEATURE_DISABLED.value

    async def test_anonymous_gets_401(
        self, db_session: AsyncSession, build_api: Callable[..., AsyncClient]
    ) -> None:
        async with build_api() as client:
            assert (await client.get(BASE)).status_code == 401


@pytest.mark.usefixtures("mep_enabled")
class TestScenarios:
    async def test_three_scenarios(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        response = await _get(build_api, workspace_id, BASE)

        assert [s["scenario_id"] for s in response.json()] == [
            "complete",
            "partial",
            "refused",
            "hybrid",
        ]

    @pytest.mark.parametrize(
        ("scenario_id", "status", "golden"),
        [
            ("complete", "complete", "boq_resolved.v0.3.json"),
            ("partial", "partial", "boq_blocked.v0.3.json"),
        ],
    )
    async def test_boq_comes_from_the_quantity_engine(
        self,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        scenario_id: str,
        status: str,
        golden: str,
    ) -> None:
        payload = (await _get(build_api, workspace_id, f"{BASE}/{scenario_id}")).json()

        assert payload["mode"] == "MOCK"
        assert payload["boq"]["status"] == status
        assert payload["boq"] == load(golden)

    async def test_corrupted_calibration_is_refused_by_validation(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        payload = (await _get(build_api, workspace_id, f"{BASE}/refused")).json()
        codes = {i["code"] for i in payload["network_issues"] if i["severity"] == "error"}

        assert "CALIBRATION_FINGERPRINT_MISMATCH" in codes
        assert payload["boq"]["status"] == "refused"
        assert payload["boq"]["lines"] == []
        assert [b["code"] for b in payload["boq"]["blockers"]] == ["NETWORK_INVALID"]

    async def test_unknown_scenario(
        self, build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID
    ) -> None:
        response = await _get(build_api, workspace_id, f"{BASE}/invented")

        assert response.status_code == 404


WEB_FIXTURES = (
    Path(__file__).resolve().parents[2] / "web" / "src" / "components" / "mep" / "__fixtures__"
)


@pytest.mark.usefixtures("mep_enabled")
@pytest.mark.parametrize("scenario_id", ["complete", "partial", "refused", "hybrid"])
async def test_web_fixtures_match_the_endpoint(
    build_api: Callable[..., AsyncClient], workspace_id: uuid.UUID, scenario_id: str
) -> None:
    """Тесты интерфейса читают ответ этого эндпоинта; расхождение значит устаревшую фикстуру."""
    payload = (await _get(build_api, workspace_id, f"{BASE}/{scenario_id}")).json()
    fixture = json.loads(
        (WEB_FIXTURES / f"scenario-{scenario_id}.json").read_text(encoding="utf-8")
    )

    assert payload == fixture


class TestTraceability:
    @pytest.mark.parametrize("scenario", scenarios_service.SCENARIOS, ids=lambda s: s.scenario_id)
    def test_links_resolve_inside_the_contracts(self, scenario: scenarios_service.Scenario) -> None:
        result = scenarios_service.run(scenario)
        network, evidence = result.network, result.evidence
        network_ids = {n.id for n in network.nodes} | {s.id for s in network.segments}
        evidence_ids = {e.id for e in evidence.elements}
        steps = {step.id: step for step in network.inference_steps}

        for line in result.boq.lines:
            assert set(line.source_ids) <= network_ids
        for item in (*network.nodes, *network.segments):
            assert set(item.derivation.evidence_ids) <= evidence_ids
            assert set(item.derivation.step_ids) <= set(steps)
        for step in steps.values():
            assert set(step.evidence_ids) <= evidence_ids
        assert network.evidence_graph.sha256 == result.evidence_sha256

    def test_evidence_graph_holds_no_generated_origin(self) -> None:
        result = scenarios_service.run(scenarios_service.SCENARIOS[0])
        generated = {"rd_prior_inferred", "retrieved_pattern", "deterministic_rule"}

        assert not {e.provenance.value for e in result.evidence.elements} & generated
