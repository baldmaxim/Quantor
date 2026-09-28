"""Синтетика рабочего калькулятора ВК (PROMPT 06): здания, правила, проект через API.

Все числа — синтетические. Версии правил создаются из шаблонов заявок калькулятора с
источником «синтетическая методика теста — не инженерное основание» и утверждаются вторым
пользователем по штатному процессу реестра. Нормативов здесь нет.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from httpx import AsyncClient

from app.auth.context import AuthContext
from app.contracts.calc.enums import CalcRuleType
from app.domain import Role
from app.models import Project
from app.services.calc.systems.vk.rule_needs import NEEDS_BY_KEY, needs_for
from app.services.calc.systems.vk.rule_templates import rule_content
from tests.conftest import make_context

API = "/api/v1/calc"
APPROVE: Final = {
    "comment": "Проверено по синтетической фикстуре калькулятора ВК.",
    "legacy_review": [],
}
ENGINEERING_SOURCE: Final = {
    "kind": "ENGINEERING_METHOD",
    "title": "Синтетическая методика тестов калькулятора ВК",
    "author": "Тестовый инженер",
    "reference": "tests/calc_vk_fixtures.py",
    "summary": "Синтетические параметры для проверки механики — не инженерное основание.",
}
OWNER_SOURCE: Final = {
    "kind": "OWNER_DECISION",
    "decided_by": "Тестовый владелец",
    "decided_at": "2026-09-28",
    "reference": "тестовый протокол",
    "basis": "Синтетика тестов тендерного допущения.",
}
FUNCTIONS: Final = {
    "В1": "COLD_WATER",
    "Т3": "HOT_WATER_SUPPLY",
    "Т4": "HOT_WATER_CIRCULATION",
    "К1": "DOMESTIC_SEWER",
}
_RISERS = {"per_riser_min": "2", "per_riser_max": "3"}
_FLAGS = {"risers_flag": "1", "connections_flag": "0", "mains_flag": "1"}
TEST_PARAMETERS: Final[Mapping[str, Mapping[str, str]]] = {
    "vk.b1.risers.count_range": _RISERS,
    "vk.t3.risers.count_range": _RISERS,
    "vk.t4.risers.count_range": _RISERS,
    "vk.k1.risers.count_range": _RISERS,
    "vk.water.riser.end_segments": {"bottom_length": "1.5", "top_length": "0.5"},
    "vk.k1.riser.end_segments": {"bottom_length": "1", "top_length": "3.5"},
    "vk.water.connection.length_range": {"per_connection_min": "2", "per_connection_max": "3.5"},
    "vk.k1.connection.length_range": {"per_connection_min": "1.5", "per_connection_max": "3"},
    "vk.water.zones.by_height": {"zone_height_max": "40"},
    "vk.k1.fixtures.by_rooms": {"per_bathroom": "3", "per_kitchen": "1"},
    "vk.supports.spacing": {"vertical_spacing": "3", "horizontal_spacing": "2"},
    "vk.fittings.per_meter": {"rate": "0.5"},
    "vk.cold.insulation.scope": _FLAGS,
    "vk.hot.insulation.scope": _FLAGS,
    "vk.k1.insulation.scope": {"risers_flag": "0", "connections_flag": "0", "mains_flag": "0"},
    "vk.penetrations.treatment": {"sleeve_flag": "1", "firestop_flag": "1"},
    "vk.tender.riser_length_reserve": {"reserve_length": "1"},
    "vk.water.topology.scheme": {"per_floor": "1"},
    "vk.t4.topology.scheme": {"per_floor": "0"},
    "vk.k1.topology.scheme": {"per_floor": "1"},
    "vk.water.valves.riser_shutoff": {"per_riser": "1"},
    "vk.t4.valves.balancing": {"per_riser": "1"},
}


def content_for(rule_key: str, **parameters: str) -> dict[str, Any]:
    need = NEEDS_BY_KEY[rule_key]
    tender = need.rule_types[0] is CalcRuleType.TENDER_ASSUMPTION
    rule_type = (
        CalcRuleType.TENDER_ASSUMPTION
        if tender
        else CalcRuleType.ENGINEERING
        if CalcRuleType.ENGINEERING in need.rule_types
        else need.rule_types[0]
    )
    values = {**TEST_PARAMETERS[rule_key], **parameters}
    content = rule_content(
        need,
        values,
        sources=[OWNER_SOURCE if tender else ENGINEERING_SOURCE],
        rule_type=rule_type,
        impact="Длина стояков больше на резерв × число стояков." if tender else None,
    )
    return content.model_dump(mode="json")


def rule_keys(system: str, *, tender: bool = False) -> list[str]:
    return [
        need.rule_key
        for need in needs_for(system)
        if need.implementation_key is not None
        and (tender or need.rule_key != "vk.tender.riser_length_reserve")
    ]


@dataclass
class Building:
    """Синтетический корпус: только то, что попадёт в реестр фактов."""

    floors: int = 24
    apartments: Mapping[str, int] = field(default_factory=lambda: {"1": 0, "2..24": 6})
    heights: Mapping[str, str] = field(default_factory=lambda: {"1": "4.2", "2..24": "3"})
    elevations: Mapping[str, str] = field(default_factory=dict)
    apartments_total: int | None = 138
    section: str | None = None
    systems: Mapping[str, str] = field(default_factory=lambda: dict(FUNCTIONS))


def _as(role: Role, workspace_id: uuid.UUID, user_id: uuid.UUID | None = None) -> AuthContext:
    if user_id is None:
        return make_context(role, workspace_id=workspace_id)
    return make_context(role, workspace_id=workspace_id, user_id=user_id)


class VkProject:
    """Проект калькулятора ВК: факты, правила, комплекты — через HTTP, как у пользователя."""

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
        self.sources: dict[str, str] = {}

    def engineer(self) -> AsyncClient:
        return self.build_api(_as(Role.ENGINEER, self.workspace_id))

    def reviewer(self) -> AsyncClient:
        return self.build_api(_as(Role.REVIEWER, self.workspace_id, self.reviewer_id))

    async def source(self, source_class: str = "MANUAL", title: str = "Инженер") -> str:
        key = f"{source_class}|{title}"
        if key not in self.sources:
            async with self.engineer() as client:
                response = await client.post(
                    f"{API}/projects/{self.project.id}/sources",
                    json={"source_class": source_class, "title": title},
                )
            assert response.status_code == 201, response.text
            self.sources[key] = response.json()["id"]
        return self.sources[key]

    async def fact(
        self,
        fact_type: str,
        subject: Mapping[str, str],
        value: Mapping[str, object],
        *,
        source_class: str = "MANUAL",
        title: str = "Инженер",
    ) -> dict[str, Any]:
        source_id = await self.source(source_class, title)
        async with self.engineer() as client:
            response = await client.post(
                f"{API}/projects/{self.project.id}/facts",
                json={
                    "source_id": source_id,
                    "fact_type": fact_type,
                    "subject": dict(subject),
                    "value": dict(value),
                    "method": "MANUAL",
                },
            )
        assert response.status_code == 201, response.text
        result: dict[str, Any] = response.json()
        return result

    async def count(self, fact_type: str, subject: Mapping[str, str], value: int) -> None:
        await self.fact(fact_type, subject, {"kind": "COUNT", "value": value})

    async def number(
        self, fact_type: str, subject: Mapping[str, str], value: str, unit: str
    ) -> None:
        await self.fact(fact_type, subject, {"kind": "NUMBER", "value": value, "unit": unit})

    async def enum(self, fact_type: str, subject: Mapping[str, str], value: str) -> None:
        await self.fact(fact_type, subject, {"kind": "ENUM", "value": value})

    async def building(self, spec: Building, building: str = "1") -> None:
        place = {"building": building} | ({"section": spec.section} if spec.section else {})
        await self.count("building.floors_above_ground", {"building": building}, spec.floors)
        if spec.apartments_total is not None:
            await self.count(
                "building.apartments_total", {"building": building}, spec.apartments_total
            )
        for floor, count in spec.apartments.items():
            await self.count("floor.apartments_count", place | {"floor": floor}, count)
        for floor, height in spec.heights.items():
            await self.number("floor.height", place | {"floor": floor}, height, "m")
        for floor, level in spec.elevations.items():
            await self.number("floor.elevation", place | {"floor": floor}, level, "m")
        for code, function in spec.systems.items():
            await self.enum(
                "system.function",
                {"building": building, "discipline": "VK", "system_code": code},
                function,
            )

    async def rule(self, rule_key: str, *, approve: bool = True, **parameters: str) -> None:
        async with self.engineer() as client:
            response = await client.post(
                f"{API}/rules",
                json={"rule_key": rule_key, "content": content_for(rule_key, **parameters)},
            )
        assert response.status_code == 201, response.text
        if approve:
            async with self.reviewer() as client:
                approved = await client.post(
                    f"{API}/rules/{rule_key}/versions/1/approve", json=APPROVE
                )
            assert approved.status_code == 200, approved.text

    async def rules(self, *systems: str, tender: bool = False) -> None:
        done: set[str] = set()
        for system in systems:
            for key in rule_keys(system, tender=tender):
                if key not in done:
                    done.add(key)
                    await self.rule(key)

    async def calculate(self, **payload: object) -> dict[str, Any]:
        body = {"building": "1", **payload}
        async with self.engineer() as client:
            response = await client.post(
                f"{API}/projects/{self.project.id}/vk/passports", json=body
            )
        assert response.status_code in (200, 201), response.text
        result: dict[str, Any] = response.json()
        return result

    async def get(self, path: str, **params: str) -> Any:
        async with self.engineer() as client:
            response = await client.get(f"{API}{path}", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    async def post(self, path: str, body: Mapping[str, object] | None = None) -> Any:
        async with self.engineer() as client:
            response = await client.post(f"{API}{path}", json=dict(body or {}))
        assert response.status_code in (200, 201), response.text
        return response.json()

    async def passport(self, batch: dict[str, Any], system: str) -> dict[str, Any]:
        summary = next(item for item in batch["passports"] if item["system_code"] == system)
        result: dict[str, Any] = await self.get(f"/vk/passports/{summary['id']}")
        return result

    async def volumes(self, passport: dict[str, Any], scenario: str) -> dict[str, dict[str, Any]]:
        rows = await self.get(f"/vk/passports/{passport['id']}/volumes", scenario=scenario)
        return {row["quantity_key"]: row for row in rows}
