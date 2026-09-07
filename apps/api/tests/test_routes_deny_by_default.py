"""Запрет по умолчанию: ни одной операции без объявленного доступа.

Проверка поведенческая, а не по исходникам, и это принципиально. В FastAPI 0.141
включённые маршрутизаторы не расплющиваются в `app.routes`: там лежат служебные маршруты
документации и объекты `_IncludedRouter`, а зависимости родительского маршрутизатора
приклеиваются к запросу во время сопоставления. Тест, перебирающий `app.routes` и
разбирающий списки зависимостей, увидел бы ноль маршрутов, ничего не нашёл и был бы
зелёным — то есть дал бы ровно то ложное чувство защиты, ради борьбы с которым пишется.

Поэтому каждая операция вызывается по-настоящему, без учётных данных, и обязана ответить
401. База данных для этого не нужна: отказ наступает до обращения к ней.
"""

from __future__ import annotations

import uuid
from typing import Final

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from app.auth.resolver import PermissionCheck
from app.core.config import get_settings
from app.main import create_app
from tests.conftest import oidc_settings

# Публичные операции и причина, по которой каждая из них публична.
PUBLIC: Final[dict[tuple[str, str], str]] = {
    ("GET", "/health/live"): "проба живости для рестарт-политики",
    ("GET", "/health/ready"): "проба готовности для балансировщика",
    ("GET", "/api/v1/meta"): "версии и возможности нужны странице входа до сеанса",
    ("GET", "/api/v1/auth/login"): "начало входа",
    ("GET", "/api/v1/auth/callback"): "возврат от провайдера",
    ("POST", "/api/v1/auth/logout"): "выход не должен требовать действующего сеанса",
    ("GET", "/api/v1/auth/session"): "«не вошёл» — это ответ, а не ошибка",
}

_METHODS = ("get", "post", "patch", "put", "delete")


def _app_with_provider() -> FastAPI:
    """Приложение с включённым провайдером: в dev-режиме контекст выдаётся всем."""
    settings = oidc_settings()
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return app


def _operations() -> list[tuple[str, str]]:
    app = _app_with_provider()
    paths = app.openapi()["paths"]
    return [
        (method.upper(), path)
        for path in sorted(paths)
        for method in sorted(paths[path])
        if method in _METHODS
    ]


def _fill(path: str) -> str:
    """Подставляет правдоподобные значения в параметры пути."""
    result = path
    while "{" in result:
        start = result.index("{")
        end = result.index("}", start)
        result = result[:start] + str(uuid.uuid4()) + result[end + 1 :]
    return result


@pytest.mark.parametrize(("method", "path"), _operations())
async def test_operation_denies_anonymous_request(method: str, path: str) -> None:
    app = _app_with_provider()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.request(method, _fill(path))

    if (method, path) in PUBLIC:
        assert response.status_code != 401, f"{method} {path} — {PUBLIC[(method, path)]}"
        return

    assert response.status_code == 401, (
        f"{method} {path} отвечает {response.status_code} без учётных данных. "
        "Новая операция должна попасть либо под запрет по умолчанию, либо в список PUBLIC "
        "с объяснением, почему она публична."
    )
    assert response.headers.get("WWW-Authenticate") == "Bearer"


def test_every_protected_operation_declares_a_permission() -> None:
    """Аутентификация отвечает «кто это», право — «что ему можно».

    Операция, прошедшая опознание и не спросившая права, доступна любому вошедшему,
    включая читателя. Здесь это ловится статически, по объявленным зависимостям.
    """
    app = _app_with_provider()

    def walk(routes: list[object]) -> list[APIRoute]:
        found: list[APIRoute] = []
        for route in routes:
            if isinstance(route, APIRoute):
                found.append(route)
            inner = getattr(route, "original_router", None)
            if inner is not None:
                found.extend(walk(inner.routes))
        return found

    public_names = {
        "liveness",
        "readiness",
        "read_meta",
        "begin_login",
        "complete_login",
        "logout",
        "read_session",
    }
    missing: list[str] = []
    for route in walk(app.routes):
        if route.name in public_names:
            continue
        permissions = [
            dependency.call.permission
            for dependency in route.dependant.dependencies
            if isinstance(dependency.call, PermissionCheck)
        ]
        if not permissions:
            missing.append(f"{sorted(route.methods)} {route.path} ({route.name})")

    assert not missing, "операции без объявленного права: " + "; ".join(sorted(set(missing)))
