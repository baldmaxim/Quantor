"""Охрана маршрутов расчётного контура (ADR-0030).

Без базы: проверяется собранное приложение и его OpenAPI.

- каждый маршрут `/api/v1/calc/` закрыт флагом `calc.portal` и правом `calc.*`;
- пути не содержат маркеров обмера и `/mep/` — иначе их поймали бы охранные тесты чужих
  контуров, а новый маршрут calc незаметно оказался бы за чужим флагом;
- все схемы, до которых дотягиваются операции calc, начинаются с `Calc`: одноимённая схема
  заставила бы FastAPI переименовать схемы MEP, а с ними — типы фронтенда.
"""

from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute

from app.api.v1.deps import FeatureCheck
from app.auth.permissions import Permission
from app.auth.resolver import PermissionCheck
from app.main import create_app

CALC_PREFIX = "/api/v1/calc/"
# Маршруты вложенного маршрутизатора хранят путь относительно `/api/v1` — префикс
# добавляется при сопоставлении запроса.
ROUTE_PREFIX = "/calc/"
CALC_FLAG = "calc.portal"
CALC_PERMISSIONS = {Permission.CALC_READ, Permission.CALC_EDIT, Permission.CALC_VERIFY}
FOREIGN_MARKERS = ("takeoff-items", "measurements", "quantities", "scale-calibrations", "/mep/")

# Операции PROMPT 01 (11), PROMPT 02 (6) и PROMPT 03 (12). Число сверяется точно: маршрут
# «на будущее» должен ломать тест, а не проходить мимо (решение владельца: API будущих сущностей
# до их промта не заводится).
EXPECTED_OPERATIONS = 29


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

    return [route for route in walk(create_app().routes) if route.path.startswith(ROUTE_PREFIX)]


def test_every_calc_route_is_closed_by_flag_and_permission() -> None:
    routes = _routes()
    operations = sum(len(route.methods) for route in routes)
    assert operations == EXPECTED_OPERATIONS

    for route in routes:
        flags = [
            dependency.call.key
            for dependency in route.dependant.dependencies
            if isinstance(dependency.call, FeatureCheck)
        ]
        permissions = [
            dependency.call.permission
            for dependency in route.dependant.dependencies
            if isinstance(dependency.call, PermissionCheck)
        ]
        assert flags == [CALC_FLAG], route.path
        assert permissions, route.path
        assert set(permissions) <= CALC_PERMISSIONS, route.path


def test_calc_paths_do_not_collide_with_foreign_guards() -> None:
    for route in _routes():
        assert not any(marker in route.path for marker in FOREIGN_MARKERS), route.path


def _refs(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _refs(value, found)


def test_calc_schemas_are_prefixed_and_do_not_rename_others() -> None:
    spec = create_app().openapi()
    schemas: dict[str, Any] = spec["components"]["schemas"]

    reached: set[str] = set()
    for path, operations in spec["paths"].items():
        if path.startswith(CALC_PREFIX):
            _refs(operations, reached)
    # Схемы, на которые ссылаются схемы calc, тоже считаются.
    frontier = set(reached)
    while frontier:
        nested: set[str] = set()
        for name in frontier:
            _refs(schemas[name], nested)
        frontier = nested - reached
        reached |= nested

    foreign = {"HTTPValidationError", "ValidationError"}
    assert reached, "операции calc не ссылаются ни на одну схему"
    assert all(name.startswith("Calc") for name in reached - foreign), sorted(reached)

    # FastAPI квалифицирует имена только при коллизии — квалифицированных имён быть не должно.
    assert not [name for name in schemas if "__" in name or name.endswith(("-Input", "-Output"))]
    # Неквалифицированные схемы MEP остались на месте.
    for mep_name in ("Parameter", "RuleRef", "SourceRef", "ReviewStatus", "Derivation"):
        assert mep_name in schemas
