"""Метаданные API и границы Stage 1."""

from __future__ import annotations

from httpx import AsyncClient

from app import API_VERSION, SCHEMA_VERSION

# Возможности, которые на Stage 1 обязаны быть выключены: портал не должен делать вид,
# что умеет считать объёмы или обращаться к моделям.
STAGE2_FEATURES = (
    "takeoff.manual",
    "takeoff.ai",
    "models.gateway",
    "reports",
    "bim.import",
    "drawing.compare",
)


async def test_meta_reports_contract_versions(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta")
    payload = response.json()

    assert response.status_code == 200
    assert payload["api_version"] == API_VERSION
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["stage"] == "stage-1.5"


async def test_meta_keeps_stage2_features_disabled(client: AsyncClient) -> None:
    response = await client.get("/api/v1/meta")
    features = response.json()["features"]

    assert [features[name] for name in STAGE2_FEATURES] == [False] * len(STAGE2_FEATURES)


async def test_unknown_route_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/takeoff/measurements")

    assert response.status_code == 404
