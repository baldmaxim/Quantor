"""Реестр поставщиков моделей: только просмотр и явная проверка связи.

Ни одного обращения к модели. Страница описывает, что настроено, и не трогает сами
модели — в том числе при открытии. Проверка связи выполняется по нажатию и щупает
доступность адреса, а не выполняет запрос к модели (промт 07).

Секретов здесь нет физически: в описании поставщика есть имя переменной окружения и
признак «задана», а поля под значение не существует.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter

from app.api.v1.deps import SettingsDep, require
from app.auth.permissions import Permission
from app.contracts.models import ProviderSpec
from app.core import model_registry
from app.core.logging import get_logger
from app.errors import DomainError, ErrorCode, not_found
from app.schemas import ModelProviderProbeRead, ModelProviderRead, ModelSpecRead

router = APIRouter(prefix="/model-providers")
log = get_logger(__name__)

# Проверка по кнопке должна отвечать быстро: администратор смотрит на неё и ждёт.
# Рабочий таймаут поставщика рассчитан на длинный запрос к модели и здесь велик.
PROBE_TIMEOUT_SECONDS = 5.0


def _to_read(spec: ProviderSpec) -> ModelProviderRead:
    return ModelProviderRead(
        id=spec.id,
        name=spec.name,
        kind=spec.kind,
        policy=spec.policy,
        endpoint_label=spec.endpoint.label,
        base_url=spec.endpoint.base_url,
        timeout_seconds=spec.endpoint.timeout_seconds,
        max_concurrency=spec.endpoint.max_concurrency,
        enabled=spec.enabled,
        is_usable=spec.is_usable,
        runs_locally=spec.runs_locally,
        credential_env=spec.credential.env_var if spec.credential else None,
        credential_configured=spec.credential.configured if spec.credential else None,
        models=[
            ModelSpecRead(
                model_id=model.model_id,
                capabilities=sorted(capability.value for capability in model.capabilities),
                context_tokens=model.context_tokens,
                max_output_tokens=model.max_output_tokens,
            )
            for model in spec.models
        ],
    )


@router.get(
    "",
    response_model=list[ModelProviderRead],
    summary="Поставщики моделей",
    dependencies=[require(Permission.MODELS_READ)],
)
async def list_model_providers(settings: SettingsDep) -> list[ModelProviderRead]:
    """Что настроено развёртыванием.

    Ни одного сетевого обращения: открытие страницы не должно зависеть от доступности
    моделей — на неё приходят как раз тогда, когда они недоступны.
    """
    return [_to_read(spec) for spec in model_registry.parse(settings.model_providers)]


@router.post(
    "/{provider_id}/health-check",
    response_model=ModelProviderProbeRead,
    summary="Проверить связь с поставщиком",
    dependencies=[require(Permission.MODELS_MANAGE)],
)
async def check_model_provider(provider_id: str, settings: SettingsDep) -> ModelProviderProbeRead:
    """Явная проверка доступности адреса.

    Проверяется связь, а не модель: запрос к модели стоит денег и времени, а на этом
    этапе портал к моделям не обращается вовсе (ADR-0006).

    Отказ одного поставщика ничего не ломает: он превращается в состояние в ответе,
    а не в исключение.
    """
    specs = {spec.id: spec for spec in model_registry.parse(settings.model_providers)}
    spec = specs.get(provider_id)
    if spec is None:
        raise not_found("Поставщик моделей")

    if spec.credential is not None and not spec.credential.configured:
        raise DomainError(
            ErrorCode.MODEL_PROVIDER_NOT_CONFIGURED,
            f"Не задана переменная окружения {spec.credential.env_var}",
        )

    loop = asyncio.get_running_loop()
    started = loop.time()
    status = "healthy"
    detail: str | None = None

    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
                response = await client.get(spec.endpoint.base_url)
        # Любой ответ означает, что адрес отвечает. Код разбирать бессмысленно:
        # у корня OpenAI-совместимого сервера он бывает любым.
        detail = f"адрес отвечает, код {response.status_code}"
    except TimeoutError:
        status = "unavailable"
        detail = "адрес не ответил за отведённое время"
    except httpx.HTTPError as error:
        status = "unavailable"
        # Класс ошибки, но не её текст: в нём бывает адрес с учётными данными.
        detail = f"соединение не установлено ({type(error).__name__})"
        log.warning(
            "model_provider_probe_failed",
            provider_id=provider_id,
            error_type=type(error).__name__,
        )

    return ModelProviderProbeRead(
        provider_id=provider_id,
        status=status,
        checked_at=datetime.now(UTC),
        latency_ms=round((loop.time() - started) * 1000, 2),
        detail=detail,
    )
