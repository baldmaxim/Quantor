"""Пилотный флаг ручного обмера (ADR-0023).

Пилотный флаг обязан значить то, что показывает админка: выключен для пространства —
возможности нет ни на экране, ни в API. Здесь проверяется сам флаг. Тесты предметной логики
обмера включают его фикстурой `takeoff_manual_enabled`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import FeatureCheck
from app.core.features import DEFAULTS, REGISTRY
from app.domain import OverrideScope, Role, ValueSource
from app.errors import DomainError, ErrorCode
from app.main import create_app
from app.models import Workspace
from app.services import feature_flags as flags_service
from app.services import projects as projects_service
from tests.conftest import clean_settings, make_context

PILOT = "takeoff.manual"

# Пути ручного обмера и калибровки. Список сверяется с приложением, а не ведётся руками:
# новый маршрут обмера без проверки флага должен ломать тест, а не проходить мимо.
TAKEOFF_PATH_MARKERS = ("takeoff-items", "measurements", "quantities", "scale-calibrations")


def _routes() -> list[APIRoute]:
    def walk(routes: list[object]) -> list[APIRoute]:
        found: list[APIRoute] = []
        for route in routes:
            if isinstance(route, APIRoute):
                found.append(route)
            inner = getattr(route, "original_router", None)
            if inner is not None:
                found.extend(walk(inner.routes))
        return found

    return walk(create_app().routes)


class TestPilotDefinition:
    def test_manual_takeoff_is_a_pilot(self) -> None:
        """Готов, выключен по умолчанию, включается на пространство."""
        definition = REGISTRY[PILOT]

        assert definition.default is False
        assert DEFAULTS[PILOT] is False
        assert definition.admin_editable is True
        assert definition.workspace_scoped is True
        assert "пилот" in definition.stage

    @pytest.mark.parametrize("key", ["takeoff.ai", "models.gateway"])
    def test_ai_flags_stay_locked(self, key: str) -> None:
        """AI не готов: флаг выключен и из админки не включается."""
        assert REGISTRY[key].default is False
        assert REGISTRY[key].admin_editable is False

    def test_every_takeoff_route_checks_the_flag(self) -> None:
        takeoff_routes = [
            route
            for route in _routes()
            if any(marker in route.path for marker in TAKEOFF_PATH_MARKERS)
        ]
        unguarded = [
            f"{sorted(route.methods)} {route.path}"
            for route in takeoff_routes
            if not any(
                isinstance(dependency.call, FeatureCheck) and dependency.call.key == PILOT
                for dependency in route.dependant.dependencies
            )
        ]

        # Десять маршрутов обмера и пять калибровки: пустой список означал бы, что тест
        # ничего не проверил.
        assert len(takeoff_routes) >= 15
        assert not unguarded, "маршруты обмера без флага: " + "; ".join(unguarded)

    def test_unknown_flag_key_fails_at_startup(self) -> None:
        """Опечатка в ключе закрыла бы маршрут навсегда — пусть лучше не стартует приложение."""
        with pytest.raises(ValueError, match="нет в реестре"):
            FeatureCheck("takeoff.manul")


class TestServerClosesTheFeature:
    async def test_disabled_flag_closes_takeoff_and_scale(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
    ) -> None:
        project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Без пилота"
        )
        await db_session.commit()

        engineer = make_context(Role.ENGINEER, workspace_id=workspace_id)
        async with build_api(engineer, settings=clean_settings()) as client:
            responses = [
                await client.get(f"/api/v1/projects/{project.id}/takeoff-items"),
                await client.post(
                    f"/api/v1/projects/{project.id}/takeoff-items",
                    json={"name": "Двери", "geometry_type": "count"},
                ),
                await client.get(f"/api/v1/sheets/{uuid.uuid4()}/measurements"),
                await client.get(f"/api/v1/sheets/{uuid.uuid4()}/quantities"),
                await client.get(f"/api/v1/sheets/{uuid.uuid4()}/scale-calibrations"),
            ]

        for response in responses:
            assert response.status_code == 403, response.request.url
            assert response.json()["detail"]["code"] == ErrorCode.FEATURE_DISABLED.value

    async def test_without_a_session_the_answer_is_still_401(
        self, db_session: AsyncSession, build_api: Callable[..., AsyncClient]
    ) -> None:
        """Проверка флага стоит после опознания: анониму нечего знать о флагах пространства."""
        async with build_api() as client:
            response = await client.get(f"/api/v1/projects/{uuid.uuid4()}/takeoff-items")

        assert response.status_code == 401

    async def test_pilot_does_not_open_the_neighbour(
        self,
        db_session: AsyncSession,
        build_api: Callable[..., AsyncClient],
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        await flags_service.set_override(
            db_session,
            make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id),
            key=PILOT,
            scope=OverrideScope.WORKSPACE,
            enabled=True,
            reason="пилот",
            settings=clean_settings(),
        )
        pilot_project = await projects_service.create_project(
            db_session, workspace_id=workspace_id, name="Пилот"
        )
        neighbour_project = await projects_service.create_project(
            db_session, workspace_id=second_workspace.id, name="Сосед"
        )
        await db_session.commit()

        pilot_engineer = make_context(Role.ENGINEER, workspace_id=workspace_id)
        async with build_api(pilot_engineer, settings=clean_settings()) as client:
            pilot = await client.get(f"/api/v1/projects/{pilot_project.id}/takeoff-items")

        neighbour_engineer = make_context(Role.ENGINEER, workspace_id=second_workspace.id)
        async with build_api(neighbour_engineer, settings=clean_settings()) as client:
            neighbour = await client.get(f"/api/v1/projects/{neighbour_project.id}/takeoff-items")

        assert pilot.status_code == 200
        assert neighbour.status_code == 403
        assert neighbour.json()["detail"]["code"] == ErrorCode.FEATURE_DISABLED.value


class TestPilotIsScopedToTheWorkspace:
    async def test_override_reaches_only_its_workspace(
        self,
        db_session: AsyncSession,
        workspace_id: uuid.UUID,
        second_workspace: Workspace,
    ) -> None:
        settings = clean_settings()
        evaluation = await flags_service.set_override(
            db_session,
            make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id),
            key=PILOT,
            scope=OverrideScope.WORKSPACE,
            enabled=True,
            reason="пилот",
            settings=settings,
        )

        def context(workspace: uuid.UUID | None) -> flags_service.EvaluationContext:
            return flags_service.EvaluationContext(workspace_id=workspace)

        pilot = await flags_service.evaluate_all(db_session, settings, context(workspace_id))
        neighbour = await flags_service.evaluate_all(
            db_session, settings, context(second_workspace.id)
        )
        anonymous = await flags_service.evaluate_all(db_session, settings, context(None))

        assert evaluation.source is ValueSource.WORKSPACE
        assert pilot[PILOT].value is True
        # Неизвестное пространство и запрос без сеанса пилот не получают.
        assert neighbour[PILOT].value is False
        assert anonymous[PILOT].value is False

    async def test_ai_flag_is_refused_even_for_one_workspace(
        self, db_session: AsyncSession, workspace_id: uuid.UUID
    ) -> None:
        with pytest.raises(DomainError) as error:
            await flags_service.set_override(
                db_session,
                make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id),
                key="takeoff.ai",
                scope=OverrideScope.WORKSPACE,
                enabled=True,
                reason="пилот AI до готовности",
                settings=clean_settings(),
            )

        assert error.value.code is ErrorCode.FLAG_NOT_EDITABLE
