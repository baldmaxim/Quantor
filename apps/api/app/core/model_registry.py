"""Реестр поставщиков моделей.

Поставщики описываются развёртыванием — переменной `MODEL_PROVIDERS`, — а не заводятся
из админки. Причина та же, по которой ключ TenderHUB живёт в окружении: адрес модели и
ключ к ней относятся к устройству установки, а не к продуктовым настройкам, и класть
их в общую таблицу настроек прямо запрещено (промт 07, ADR-0013).

Отсюда следует, чего здесь **нет**: ни таблицы, ни операции создания, ни переключателя
«включить» в интерфейсе. Заводить их ради нуля настроенных поставщиков значило бы
построить тот самый пустой каркас, от которого отказывается ADR-0001. Управление
появится вместе с шлюзом моделей на Stage 2, когда будет чем управлять.

Секрет сюда не попадает физически: в описании поставщика есть имя переменной окружения
и признак «задана», а поля под значение не существует.
"""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.contracts.models import (
    Capability,
    CredentialRef,
    DataPolicy,
    EndpointSpec,
    ModelSpec,
    ProviderKind,
    ProviderSpec,
)
from app.core.logging import get_logger

log = get_logger(__name__)


class _ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=200)
    capabilities: list[Capability] = Field(min_length=1)
    context_tokens: int = Field(default=0, ge=0)
    max_output_tokens: int = Field(default=0, ge=0)


class _ProviderConfig(BaseModel):
    """Разбор одного поставщика из конфигурации.

    `extra="forbid"`: опечатка в имени поля должна быть видна сразу, а не превращаться
    в молча пропущенную настройку.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    kind: ProviderKind
    policy: DataPolicy
    base_url: str = Field(min_length=1, max_length=500)
    label: str = Field(default="", max_length=200)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_concurrency: int = Field(default=1, gt=0)
    credential_env: str | None = Field(default=None, max_length=100)
    enabled: bool = False
    models: list[_ModelConfig] = Field(default_factory=list)


def _to_spec(config: _ProviderConfig) -> ProviderSpec:
    credential = (
        CredentialRef(
            env_var=config.credential_env,
            # Читается только факт наличия. Значение не покидает окружение процесса.
            configured=bool(os.environ.get(config.credential_env, "").strip()),
        )
        if config.credential_env
        else None
    )
    return ProviderSpec(
        id=config.id,
        name=config.name,
        kind=config.kind,
        endpoint=EndpointSpec(
            label=config.label or config.base_url,
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
            max_concurrency=config.max_concurrency,
        ),
        policy=config.policy,
        models=tuple(
            ModelSpec(
                model_id=model.model_id,
                capabilities=frozenset(model.capabilities),
                context_tokens=model.context_tokens,
                max_output_tokens=model.max_output_tokens,
            )
            for model in config.models
        ),
        credential=credential,
        enabled=config.enabled,
    )


def parse(raw: str) -> list[ProviderSpec]:
    """Разбирает описание поставщиков из строки конфигурации.

    Негодная конфигурация не роняет портал: она пишется в журнал и игнорируется.
    Уронить запуск API из-за опечатки в описании модели, к которой на этом этапе никто
    не обращается, было бы несоразмерно.
    """
    text = raw.strip()
    if not text:
        return []

    try:
        payload: Any = json.loads(text)
    except ValueError as error:
        log.error("model_providers_unparsable", error_type=type(error).__name__)
        return []

    if not isinstance(payload, list):
        log.error("model_providers_not_a_list")
        return []

    specs: list[ProviderSpec] = []
    seen: set[str] = set()
    for item in payload:
        try:
            config = _ProviderConfig.model_validate(item)
        except ValidationError as error:
            # В журнал — какое поле не подошло, но не содержимое: в конфигурации может
            # оказаться то, чего в логе видеть не следует.
            log.error(
                "model_provider_invalid",
                errors=[{"field": ".".join(str(p) for p in e["loc"])} for e in error.errors()],
            )
            continue
        if config.id in seen:
            log.error("model_provider_duplicate_id", provider_id=config.id)
            continue
        seen.add(config.id)
        specs.append(_to_spec(config))

    return specs
