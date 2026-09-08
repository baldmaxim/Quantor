"""Настройки, флаги и журнал: порядок старшинства, права и следы.

Порядок старшинства проверяется по ступеням отдельно, а не одним «работает»: ошибка в
нём проявляется не отказом, а тихо неправильным значением, и обнаруживается по жалобе
пользователя через недели.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission
from app.core import settings_registry as registry
from app.core.config import Settings
from app.core.features import REGISTRY as FLAG_REGISTRY
from app.core.settings_registry import SettingValueError
from app.domain import AuditAction, OverrideScope, Role, ValueSource
from app.models import AuditEvent, Workspace
from app.services import audit as audit_service
from app.services import feature_flags as flags_service
from app.services import portal_settings
from tests.conftest import clean_settings, make_context

TTL_KEY = "documents.content_url_ttl_seconds"
SIZE_KEY = "uploads.max_upload_size_bytes"


# ------------------------------------------------------------------ реестр настроек


def test_registry_never_holds_infrastructure_config() -> None:
    """Ключ реестра не должен совпадать с полем окружения.

    DSN базы, ключи хранилища и секрет провайдера входа остаются в окружении: настройка,
    способная сломать подключение к базе, чинится уже не через портал.
    """
    infrastructure = set(Settings.model_fields)
    assert not (set(registry.DEFINITIONS) & infrastructure)


def test_registry_holds_no_secrets() -> None:
    """На Stage 1.5 секретов в настройках нет по построению — для них отдельный канал."""
    assert all(not definition.is_secret for definition in registry.DEFINITIONS.values())


def test_project_scope_is_declared_but_not_used() -> None:
    """Уровень проекта объявлен в контракте и никому не выдан.

    Выдать уровень, который никто не читает, — значит показать администратору
    переключатель, ничего не делающий.
    """
    assert OverrideScope.PROJECT not in {
        scope for definition in registry.DEFINITIONS.values() for scope in definition.allowed_scopes
    }


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("не число", "строка вместо целого"),
        (True, "булево вместо целого: bool — подкласс int, и это надо ловить"),
        (10, "меньше минимума"),
        (10**9, "больше максимума"),
    ],
)
def test_invalid_values_are_rejected_with_a_reason(value: object, reason: str) -> None:
    definition = registry.DEFINITIONS[TTL_KEY]
    with pytest.raises(SettingValueError) as error:
        registry.validate(definition, value)
    assert str(error.value), reason


def test_deployment_ceiling_caps_the_value() -> None:
    """Арендатор не может разрешить приём файлов больше, чем выдержит установка."""
    definition = registry.DEFINITIONS[SIZE_KEY]
    with pytest.raises(SettingValueError):
        registry.validate(definition, 10 * 1024**3, ceiling=1024**3)


# ------------------------------------------------------- порядок старшинства настроек


async def test_precedence_is_exactly_default_system_workspace_deployment(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    settings = clean_settings()
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)

    # 1. умолчание кода
    resolved = await portal_settings.effective(
        db_session, workspace_id=workspace_id, settings=settings
    )
    assert resolved[TTL_KEY].value == 3600
    assert resolved[TTL_KEY].source == ValueSource.DEFAULT.value

    # 2. системное переопределение старше умолчания
    await portal_settings.set_override(
        db_session, context, key=TTL_KEY, scope=OverrideScope.SYSTEM, value=1200, settings=settings
    )
    resolved = await portal_settings.effective(
        db_session, workspace_id=workspace_id, settings=settings
    )
    assert resolved[TTL_KEY].value == 1200
    assert resolved[TTL_KEY].source == ValueSource.SYSTEM.value

    # 3. переопределение пространства старше системного
    await portal_settings.set_override(
        db_session,
        context,
        key=TTL_KEY,
        scope=OverrideScope.WORKSPACE,
        value=900,
        settings=settings,
    )
    resolved = await portal_settings.effective(
        db_session, workspace_id=workspace_id, settings=settings
    )
    assert resolved[TTL_KEY].value == 900
    assert resolved[TTL_KEY].source == ValueSource.WORKSPACE.value

    # 4. окружение старше всего: это аварийный рычаг
    emergency = clean_settings(settings_overrides=f"{TTL_KEY}=300")
    resolved = await portal_settings.effective(
        db_session, workspace_id=workspace_id, settings=emergency
    )
    assert resolved[TTL_KEY].value == 300
    assert resolved[TTL_KEY].source == ValueSource.DEPLOYMENT.value


async def test_deleting_an_override_returns_the_inherited_value(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    settings = clean_settings()
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)

    await portal_settings.set_override(
        db_session, context, key=TTL_KEY, scope=OverrideScope.SYSTEM, value=1200, settings=settings
    )
    await portal_settings.set_override(
        db_session,
        context,
        key=TTL_KEY,
        scope=OverrideScope.WORKSPACE,
        value=900,
        settings=settings,
    )

    resolved = await portal_settings.delete_override(
        db_session, context, key=TTL_KEY, scope=OverrideScope.WORKSPACE, settings=settings
    )
    # Не к умолчанию кода, а к тому, что лежит уровнем ниже.
    assert resolved.value == 1200
    assert resolved.source == ValueSource.SYSTEM.value


async def test_workspace_override_does_not_leak_between_tenants(
    db_session: AsyncSession, workspace_id: uuid.UUID, second_workspace: Workspace
) -> None:
    settings = clean_settings()
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    await portal_settings.set_override(
        db_session,
        context,
        key=TTL_KEY,
        scope=OverrideScope.WORKSPACE,
        value=900,
        settings=settings,
    )

    neighbour = await portal_settings.effective(
        db_session, workspace_id=second_workspace.id, settings=settings
    )
    assert neighbour[TTL_KEY].value == 3600


async def test_workspace_admin_cannot_change_the_whole_installation(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Системный уровень — привилегия платформы, а не арендатора."""
    settings = clean_settings()
    context = make_context(Role.WORKSPACE_ADMIN, workspace_id=workspace_id)
    assert Permission.SETTINGS_MANAGE in context.permissions

    from app.errors import DomainError

    with pytest.raises(DomainError) as error:
        await portal_settings.set_override(
            db_session,
            context,
            key=TTL_KEY,
            scope=OverrideScope.SYSTEM,
            value=1200,
            settings=settings,
        )
    assert error.value.code.value == "PERMISSION_DENIED"


# ---------------------------------------------------------------------- флаги


def test_every_stage1_flag_key_survived() -> None:
    """Ключи флагов — часть контракта: по ним интерфейс решает, что показывать."""
    expected = {
        "projects",
        "documents",
        "uploads",
        "legacy_import",
        "viewer",
        "integrations.tenderhub",
        "takeoff.manual",
        "takeoff.ai",
        "models.gateway",
        "reports",
        "bim.import",
        "drawing.compare",
    }
    assert set(FLAG_REGISTRY) == expected


def test_unfinished_features_cannot_be_enabled_from_the_console() -> None:
    """Незавершённое остаётся закрытым: включение флага не создаёт функциональность."""
    for key in (
        "takeoff.manual",
        "takeoff.ai",
        "models.gateway",
        "reports",
        "bim.import",
        "drawing.compare",
    ):
        assert not FLAG_REGISTRY[key].admin_editable, key


async def test_enabling_an_unready_feature_is_refused(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    from app.errors import DomainError

    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    with pytest.raises(DomainError) as error:
        await flags_service.set_override(
            db_session,
            context,
            key="takeoff.ai",
            scope=OverrideScope.SYSTEM,
            enabled=True,
            reason="хочу показать заказчику",
            settings=clean_settings(),
        )
    assert error.value.code.value == "FLAG_NOT_EDITABLE"


async def test_integration_flag_cannot_be_enabled_without_a_key(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Включённая интеграция без ключа — обещание, которого сервер не выполнит."""
    from app.errors import DomainError

    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    with pytest.raises(DomainError) as error:
        await flags_service.set_override(
            db_session,
            context,
            key="integrations.tenderhub",
            scope=OverrideScope.SYSTEM,
            enabled=True,
            reason=None,
            settings=clean_settings(),
        )
    assert error.value.code.value == "FLAG_NOT_EDITABLE"


async def test_flag_override_is_scoped_to_its_workspace(
    db_session: AsyncSession, workspace_id: uuid.UUID, second_workspace: Workspace
) -> None:
    settings = clean_settings()
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    await flags_service.set_override(
        db_session,
        context,
        key="viewer",
        scope=OverrideScope.WORKSPACE,
        enabled=False,
        reason="чинится после жалобы",
        settings=settings,
    )

    mine = await flags_service.as_mapping(
        db_session, settings, flags_service.EvaluationContext(workspace_id=workspace_id)
    )
    neighbour = await flags_service.as_mapping(
        db_session, settings, flags_service.EvaluationContext(workspace_id=second_workspace.id)
    )
    assert mine["viewer"] is False
    assert neighbour["viewer"] is True


async def test_meta_reflects_the_current_context(
    api: AsyncClient, db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    await flags_service.set_override(
        db_session,
        context,
        key="viewer",
        scope=OverrideScope.SYSTEM,
        enabled=False,
        reason="временно",
        settings=clean_settings(),
    )

    response = await api.get("/api/v1/meta")
    assert response.status_code == 200
    assert response.json()["features"]["viewer"] is False


# ---------------------------------------------------------------------- журнал


async def test_changes_leave_a_trace(db_session: AsyncSession, workspace_id: uuid.UUID) -> None:
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    await portal_settings.set_override(
        db_session,
        context,
        key=TTL_KEY,
        scope=OverrideScope.SYSTEM,
        value=1200,
        settings=clean_settings(),
    )

    events = (await db_session.execute(select(AuditEvent))).scalars().all()
    assert len(events) == 1
    event = events[0]
    assert event.action == AuditAction.SETTING_OVERRIDE_SET.value
    assert event.resource_id == TTL_KEY
    assert event.after_summary == {"value": 1200, "scope": "system"}
    assert event.actor_user_id == context.principal.user_id


def test_redaction_removes_secret_looking_fields() -> None:
    """Вычищается на записи: вычищенное на чтении уже лежит в базе и в резервной копии."""
    cleaned = audit_service.redact(
        {
            "tenderhub_api_token": "thk_живой_ключ",
            "client_secret": "очень секретно",
            "nested": {"password": "hunter2", "port": 5432},
            "safe": "значение",
        }
    )
    assert cleaned is not None
    assert cleaned["tenderhub_api_token"] == "***"
    assert cleaned["client_secret"] == "***"
    assert cleaned["nested"]["password"] == "***"
    assert cleaned["nested"]["port"] == 5432
    assert cleaned["safe"] == "значение"


def test_every_action_is_declared() -> None:
    """Словарь действий один. Строка мимо перечисления — это действие, которое не найдут."""
    assert all(isinstance(action.value, str) and action.value for action in AuditAction)


async def test_audit_rows_cannot_be_rewritten(
    db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    """Защита в базе, а не только в отсутствии маршрутов: API можно обойти."""
    context = make_context(Role.PLATFORM_ADMIN, workspace_id=workspace_id)
    event = await audit_service.record(
        db_session,
        context,
        action=AuditAction.SETTING_OVERRIDE_SET,
        resource_type="setting",
        resource_id=TTL_KEY,
    )
    await db_session.commit()
    event_id = event.id

    with pytest.raises(DBAPIError):
        await db_session.execute(
            text("update audit_events set action = 'подделка' where id = :id"),
            {"id": event_id},
        )
    await db_session.rollback()

    with pytest.raises(DBAPIError):
        await db_session.execute(text("delete from audit_events where id = :id"), {"id": event_id})
    await db_session.rollback()


def test_audit_has_no_mutating_operations() -> None:
    """Ни одной операции изменения журнала в контракте."""
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    audit_paths = {path: spec for path, spec in paths.items() if "/admin/audit" in path}
    assert audit_paths, "маршрут журнала пропал из контракта"
    for path, spec in audit_paths.items():
        assert set(spec) <= {"get"}, f"{path}: журнал должен быть только на чтение"


async def test_ordinary_user_cannot_read_the_audit(
    build_api: Callable[..., AsyncClient], db_session: AsyncSession, workspace_id: uuid.UUID
) -> None:
    async with build_api(make_context(Role.ENGINEER, workspace_id=workspace_id)) as client:
        response = await client.get("/api/v1/admin/audit")
    assert response.status_code == 403
