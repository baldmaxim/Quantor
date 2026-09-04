"""Метаданные API: версии контракта и схемы, набор включённых возможностей.

Фронтенд по этому эндпоинту понимает, что показывать, а что держать выключенным,
и не хранит собственную копию списка фич.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import API_VERSION, SCHEMA_VERSION
from app.core.config import get_settings
from app.core.features import resolve

router = APIRouter(tags=["meta"])


class MetaResponse(BaseModel):
    api_version: str
    schema_version: int
    environment: str
    stage: str
    features: dict[str, bool]


@router.get("/meta", response_model=MetaResponse, summary="Версии и возможности API")
async def read_meta() -> MetaResponse:
    settings = get_settings()
    return MetaResponse(
        api_version=API_VERSION,
        schema_version=SCHEMA_VERSION,
        environment=settings.environment,
        stage="stage-1",
        features=resolve(settings.feature_flags),
    )
