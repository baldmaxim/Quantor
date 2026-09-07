"""Метаданные API: версии контракта и схемы, набор включённых возможностей.

Фронтенд по этому эндпоинту понимает, что показывать, а что держать выключенным,
и не хранит собственную копию списка фич.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app import API_VERSION, SCHEMA_VERSION
from app.api.v1.deps import SessionDep, SettingsDep
from app.auth.resolver import optional_context
from app.services import feature_flags as flags_service

router = APIRouter(tags=["meta"])


class MetaResponse(BaseModel):
    api_version: str
    schema_version: int
    environment: str
    stage: str
    features: dict[str, bool]
    auth_mode: Literal["dev", "oidc"]
    """Как устроен вход. Интерфейс по нему решает, показывать ли кнопку входа."""


@router.get("/meta", response_model=MetaResponse, summary="Версии и возможности API")
async def read_meta(request: Request, session: SessionDep, settings: SettingsDep) -> MetaResponse:
    """Версии контракта и набор возможностей для текущего контекста.

    Маршрут публичный: странице входа нужно узнать состояние API до того, как появится
    сеанс. Без сеанса отдаются код и системные переопределения, с сеансом добавляются
    переопределения пространства.

    Отказ базы понижает набор до кодовых умолчаний, а не роняет запрос: на неразмеченной
    установке портал обязан показать границу этапа, а не пятисотку.
    """
    context = await optional_context(request, settings, session)
    workspace_id = context.workspace_id if context is not None else None

    features = await flags_service.as_mapping(
        session,
        settings,
        flags_service.EvaluationContext(workspace_id=workspace_id),
    )
    return MetaResponse(
        api_version=API_VERSION,
        schema_version=SCHEMA_VERSION,
        environment=settings.environment,
        stage="stage-1.5",
        features=features,
        auth_mode=settings.auth_mode,
    )
