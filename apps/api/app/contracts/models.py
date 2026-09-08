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


# --------------------------------------------------------- контур управления
#
# Всё ниже — про управление реестром, а не про вызовы. Ни одного обращения к модели
# здесь нет и на Stage 1.5 не появится: административная страница описывает, что
# настроено, и не трогает сами модели (промт 07).


class ProviderKind(StrEnum):
    """Как разговаривать с поставщиком.

    Различие протокольное, а не маркетинговое: vLLM, SGLang и LM Studio отвечают
    OpenAI-совместимым API, и адаптер у них будет общий.
    """

    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC_COMPATIBLE = "anthropic_compatible"
    LM_STUDIO = "lm_studio"
    VLLM = "vllm"
    SGLANG = "sglang"
    CUSTOM = "custom"


class DataPolicy(StrEnum):
    """Куда позволено уходить данным.

    Для проектной документации это бывает жёстким требованием заказчика, а не
    пожеланием: чертёж объекта нельзя отправлять наружу ни при каких условиях.
    """

    LOCAL_ONLY = "local_only"
    REMOTE_ALLOWED = "remote_allowed"
    RESTRICTED_DATA = "restricted_data"


class Capability(StrEnum):
    """Что модель умеет. Требование формулируется в этих терминах, а не именами моделей."""

    TEXT = "text"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    RERANK = "rerank"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_USE = "tool_use"


@dataclass(frozen=True, slots=True)
class CredentialRef:
    """Ссылка на секрет, а не сам секрет.

    Тип полей выбран так, что положить сюда значение ключа физически некуда: есть имя
    переменной окружения и признак «задана». Маскирование не нужно там, где нечего
    маскировать (ADR-0006).

    Ротация: поменять значение переменной окружения и перезапустить процесс. Хранилища
    секретов на Stage 1.5 нет, и делать вид, что есть, не следует.
    """

    env_var: str
    configured: bool

    def __post_init__(self) -> None:
        if not self.env_var:
            raise ValueError("ссылка на секрет обязана называть переменную окружения")


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    """Куда обращаться. Адрес не секрет — секрет лежит по ссылке в CredentialRef."""

    label: str
    base_url: str
    timeout_seconds: float = 60.0
    max_concurrency: int = 1


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Одна модель у поставщика."""

    model_id: str
    capabilities: frozenset[Capability]
    context_tokens: int = 0
    max_output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    """Поставщик целиком: как с ним говорить, что у него есть и куда уйдут данные."""

    id: str
    name: str
    kind: ProviderKind
    endpoint: EndpointSpec
    policy: DataPolicy
    models: tuple[ModelSpec, ...] = ()
    credential: CredentialRef | None = None
    enabled: bool = False

    @property
    def runs_locally(self) -> bool:
        return self.policy is DataPolicy.LOCAL_ONLY

    @property
    def is_usable(self) -> bool:
        """Включён и готов к работе.

        Поставщик, которому нужен ключ, без ключа не готов, что бы ни стояло в
        настройке: включённая возможность без ключа — обещание, которого не выполнят.
        """
        if not self.enabled:
            return False
        return self.credential is None or self.credential.configured


@dataclass(frozen=True, slots=True)
class ProviderHealthReport:
    """Результат явной проверки поставщика.

    Задержка появляется только здесь и только после нажатия: измерять её при открытии
    страницы значит ходить к модели тогда, когда об этом никто не просил.
    """

    provider_id: str
    status: str
    checked_at: str
    latency_ms: float | None = None
    detail: str | None = None
