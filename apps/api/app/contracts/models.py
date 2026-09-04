"""Граница шлюза моделей.

Здесь только контракт. Ни одного SDK, ни одного сетевого вызова, ни одного ключа — на этом
этапе портал к моделям не обращается (ADR-0006).

Смысл границы в том, что бизнес-модули формулируют требование в терминах **возможностей**,
а не имён: «нужна модель, которая видит изображения, отдаёт структурированный ответ и
работает локально». Ветвление вида `if provider == "..."` в бизнес-коде запрещено — оно
превращает смену поставщика в правку половины проекта.

Реализации появятся вместе с первым реальным потребителем. Ожидаемые адаптеры:
локальные OpenAI-совместимые сервера (vLLM, SGLang, llama.cpp), удалённые
OpenAI-совместимые сервисы, Anthropic, OpenAI, собственные VLM-сервисы.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Modality(StrEnum):
    """Что модель принимает на вход."""

    TEXT = "text"
    VISION = "vision"


class LatencyClass(StrEnum):
    """Грубая оценка задержки. Точные цифры зависят от нагрузки и здесь не обещаются."""

    INTERACTIVE = "interactive"
    BATCH = "batch"


class CostClass(StrEnum):
    """Относительная стоимость. Числа в валюте сюда не попадают — они устаревают быстрее кода."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ImageConstraints:
    """Ограничения на изображения — важны для чертежей: лист А1 в 300 dpi огромен."""

    max_pixels: int | None = None
    max_bytes: int | None = None
    accepted_formats: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """Паспорт модели.

    Именно по этим полям модуль выбирает модель. Имя поставщика в списке есть, но нужно
    для журналирования и происхождения результата, а не для ветвления логики.
    """

    provider_id: str
    model_id: str
    modalities: frozenset[Modality]
    structured_output: bool
    tool_calling: bool
    context_tokens: int
    max_output_tokens: int
    image_constraints: ImageConstraints = field(default_factory=ImageConstraints)
    max_concurrency: int = 1
    latency_class: LatencyClass = LatencyClass.BATCH
    cost_class: CostClass = CostClass.MEDIUM
    # Данные не покидают периметр заказчика. Для проектной документации это может быть
    # жёстким требованием, а не пожеланием.
    runs_locally: bool = False

    def satisfies(self, requirement: ModelRequirement) -> bool:
        """Подходит ли модель под требование модуля."""
        if not requirement.modalities <= self.modalities:
            return False
        if requirement.structured_output and not self.structured_output:
            return False
        if requirement.tool_calling and not self.tool_calling:
            return False
        if requirement.min_context_tokens > self.context_tokens:
            return False
        return not (requirement.must_run_locally and not self.runs_locally)


@dataclass(frozen=True, slots=True)
class ModelRequirement:
    """Что нужно вызывающему модулю. Формулируется без имён моделей."""

    modalities: frozenset[Modality] = frozenset({Modality.TEXT})
    structured_output: bool = False
    tool_calling: bool = False
    min_context_tokens: int = 0
    must_run_locally: bool = False


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """Доступность поставщика."""

    available: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    """Запрос к модели.

    Намеренно бедный: строится из данных портала, а не из формата конкретного поставщика.
    Приведение к формату API — задача адаптера.
    """

    prompt: str
    images: tuple[bytes, ...] = ()
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """Ответ модели вместе с происхождением.

    provider_id и model_id обязательны: без них невозможно объяснить, откуда взялся
    результат, а требование прослеживаемости распространяется и на данные от моделей.
    """

    text: str
    structured: dict[str, Any] | None
    provider_id: str
    model_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class ModelProvider(Protocol):
    """Контракт поставщика моделей. На Stage 1 реализаций нет."""

    def capabilities(self) -> ModelCapabilities:
        """Паспорт модели: по нему модуль решает, подходит ли она."""
        ...

    async def health(self) -> ProviderHealth:
        """Доступен ли поставщик прямо сейчас."""
        ...

    async def infer(self, request: InferenceRequest) -> InferenceResult:
        """Выполняет запрос. Реализуется в Stage 2 вместе с первым потребителем."""
        ...


def select(
    providers: list[ModelCapabilities], requirement: ModelRequirement
) -> ModelCapabilities | None:
    """Выбирает подходящую модель по возможностям.

    Из подходящих берётся самая дешёвая: качество на конкретной задаче сравнивают
    измерением, а не порядком в списке.
    """
    order = {CostClass.LOW: 0, CostClass.MEDIUM: 1, CostClass.HIGH: 2}
    suitable = [provider for provider in providers if provider.satisfies(requirement)]
    if not suitable:
        return None
    return min(suitable, key=lambda provider: order[provider.cost_class])
