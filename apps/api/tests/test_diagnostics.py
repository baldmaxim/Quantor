"""Диагностика и реестр поставщиков моделей.

База здесь не нужна: проверяется поведение проб, а не содержимое таблиц. Мёртвая
зависимость имитируется пробой, которая не отвечает, — без ожидания настоящих секунд.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import pytest
from httpx import AsyncClient

from app.contracts.models import CredentialRef, DataPolicy, ProviderKind
from app.core import model_registry
from app.domain import Role
from app.services import diagnostics
from app.services.diagnostics import Probe, ProbeSource, ProbeStatus
from tests.conftest import clean_settings, make_context


def _ok(name: str) -> Probe:
    async def run() -> diagnostics.ComponentDiagnostics:
        return diagnostics._component(name, name, ProbeStatus.HEALTHY, ProbeSource.LIVE)

    return Probe(name=name, title=name, run=run, timeout_seconds=0.2)


def _hangs(name: str, *, required: bool = False) -> Probe:
    async def run() -> diagnostics.ComponentDiagnostics:
        await asyncio.sleep(30)
        raise AssertionError("проба не должна была дождаться")

    return Probe(name=name, title=name, run=run, timeout_seconds=0.2, required=required)


def _explodes(name: str) -> Probe:
    async def run() -> diagnostics.ComponentDiagnostics:
        raise ConnectionRefusedError("postgresql://quantor:hunter2@db:5432/quantor")

    return Probe(name=name, title=name, run=run, timeout_seconds=0.2)


# ------------------------------------------------------------------ выполнение проб


async def test_one_dead_dependency_does_not_hang_the_page() -> None:
    """Мёртвая зависимость не мешает увидеть остальные.

    Ровно за этим страница и открывается: узнать, что именно сломалось. Если она
    висит, пока ждёт сломанное, она бесполезна именно тогда, когда нужна.
    """
    probes = [_ok("first"), _hangs("dead"), _ok("second")]

    results = await diagnostics.run_probes(probes, budget_seconds=5.0)
    by_name = {item.name: item for item in results}

    assert by_name["first"].status is ProbeStatus.HEALTHY
    assert by_name["second"].status is ProbeStatus.HEALTHY
    assert by_name["dead"].status is ProbeStatus.UNAVAILABLE


async def test_total_budget_bounds_the_page() -> None:
    """Предел на пробу без общего бюджета страницу не спасает.

    Восемь проб по три секунды за ограничителем дают двадцать четыре. Не успевшие
    возвращаются как «неизвестно» — честнее, чем заставлять ждать.
    """
    probes = [
        Probe(name=f"slow-{i}", title="", run=_hangs("x").run, timeout_seconds=30.0)
        for i in range(6)
    ]

    loop = asyncio.get_running_loop()
    started = loop.time()
    results = await diagnostics.run_probes(probes, concurrency=2, budget_seconds=0.5)
    elapsed = loop.time() - started

    assert elapsed < 3.0, "страница обязана ответить в пределах бюджета"
    assert all(item.status is ProbeStatus.UNKNOWN for item in results)
    assert all(item.source is ProbeSource.UNKNOWN for item in results)


async def test_probe_failure_never_leaks_connection_details() -> None:
    """Текст исключения наружу не уходит: в нём бывает строка подключения."""
    results = await diagnostics.run_probes([_explodes("database")])

    assert results[0].status is ProbeStatus.UNAVAILABLE
    assert results[0].detail is not None
    assert "hunter2" not in results[0].detail
    assert "postgresql://" not in results[0].detail


def test_optional_components_do_not_break_the_installation() -> None:
    """Отсутствующий воркер делает установку неполной, а не сломанной."""
    probes = [_ok("database"), _hangs("job_worker", required=False)]
    components = [
        diagnostics._component("database", "", ProbeStatus.HEALTHY, ProbeSource.LIVE),
        diagnostics._component("job_worker", "", ProbeStatus.UNAVAILABLE, ProbeSource.REPORTED),
    ]

    assert diagnostics.overall(components, probes) is ProbeStatus.HEALTHY


def test_required_component_failure_is_visible_in_the_summary() -> None:
    probes = [_ok("database")]
    components = [diagnostics._component("database", "", ProbeStatus.UNAVAILABLE, ProbeSource.LIVE)]

    assert diagnostics.overall(components, probes) is ProbeStatus.UNAVAILABLE


# ---------------------------------------------------------------- реестр моделей


def test_registry_is_empty_without_configuration() -> None:
    assert model_registry.parse("") == []


def test_invalid_provider_is_skipped_not_fatal() -> None:
    """Опечатка в описании модели не должна ронять портал.

    К моделям на этом этапе никто не обращается, и уронить из-за них запуск API
    было бы несоразмерно.
    """
    config = json.dumps(
        [
            {
                "id": "good",
                "name": "Хороший",
                "kind": "vllm",
                "policy": "local_only",
                "base_url": "http://gpu:8000",
            },
            {
                "id": "bad",
                "name": "Плохой",
                "kind": "нет такого",
                "policy": "local_only",
                "base_url": "http://x",
            },
        ]
    )

    specs = model_registry.parse(config)
    assert [spec.id for spec in specs] == ["good"]


def test_duplicate_provider_ids_are_rejected() -> None:
    config = json.dumps(
        [
            {
                "id": "same",
                "name": "Первый",
                "kind": "vllm",
                "policy": "local_only",
                "base_url": "http://a",
            },
            {
                "id": "same",
                "name": "Второй",
                "kind": "vllm",
                "policy": "local_only",
                "base_url": "http://b",
            },
        ]
    )

    specs = model_registry.parse(config)
    assert len(specs) == 1
    assert specs[0].name == "Первый"


def test_credential_reference_has_nowhere_to_put_a_secret() -> None:
    """Маскировать нечего там, где нечего показывать.

    У ссылки на секрет есть имя переменной и признак «задана» — и ни одного поля,
    в которое можно было бы положить значение.
    """
    fields = set(CredentialRef.__slots__)

    assert fields == {"env_var", "configured"}


def test_provider_without_its_key_is_not_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включённая возможность без ключа — обещание, которого сервер не выполнит."""
    monkeypatch.delenv("MODEL_KEY", raising=False)
    config = json.dumps(
        [
            {
                "id": "remote",
                "name": "Удалённый",
                "kind": "openai_compatible",
                "policy": "remote_allowed",
                "base_url": "https://api.example",
                "credential_env": "MODEL_KEY",
                "enabled": True,
            }
        ]
    )

    spec = model_registry.parse(config)[0]
    assert spec.credential is not None
    assert spec.credential.configured is False
    assert spec.is_usable is False

    monkeypatch.setenv("MODEL_KEY", "секрет")
    assert model_registry.parse(config)[0].is_usable is True


def test_local_policy_is_visible_in_the_spec() -> None:
    """Классификация «локально или наружу» — не украшение.

    Для проектной документации запрет на выход наружу бывает жёстким требованием
    заказчика, и видеть его нужно рядом с поставщиком.
    """
    config = json.dumps(
        [
            {
                "id": "local",
                "name": "Локальный",
                "kind": "vllm",
                "policy": "local_only",
                "base_url": "http://gpu:8000",
            }
        ]
    )

    spec = model_registry.parse(config)[0]
    assert spec.policy is DataPolicy.LOCAL_ONLY
    assert spec.runs_locally is True
    assert spec.kind is ProviderKind.VLLM


# ------------------------------------------------------------------ права и вызовы


async def test_ordinary_admin_page_load_makes_no_model_call(
    build_api: Callable[..., AsyncClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Открытие страницы поставщиков не обращается к моделям.

    Проверяется прямо: любой сетевой вызов через httpx во время запроса роняет тест.
    """
    calls: list[str] = []

    class Tripwire:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Tripwire:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> object:
            calls.append(url)
            raise AssertionError(f"страница обратилась к {url}")

    monkeypatch.setattr("httpx.AsyncClient", Tripwire)

    context = make_context(Role.PLATFORM_ADMIN)
    async with build_api(context) as client:
        response = await client.get("/api/v1/admin/model-providers")

    assert response.status_code == 200
    assert calls == [], "при открытии страницы к моделям не обращаются"


async def test_only_admin_sees_the_model_registry(
    build_api: Callable[..., AsyncClient],
) -> None:
    async with build_api(make_context(Role.ENGINEER)) as client:
        response = await client.get("/api/v1/admin/model-providers")

    assert response.status_code == 403


def test_settings_holds_no_model_secrets() -> None:
    """Ключи моделей не переезжают в настройки: там им не место (промт 07)."""
    settings = clean_settings()

    assert settings.model_providers == "" or "credential_env" in settings.model_providers
    # Само поле — описание, а не хранилище: значений ключей в нём быть не может.
    assert "model_key" not in settings.model_providers.lower()
