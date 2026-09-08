"""Вычисление флагов возможностей.

Интерфейс намеренно оформлен провайдер-нейтрально и по форме близок к OpenFeature:
бизнес-код спрашивает `is_enabled(key, context)` и не знает, откуда пришёл ответ.
Внешнего сервиса флагов не заводится — на текущих объёмах это была бы инфраструктура
без отдачи, — но замена провайдера потом не потребует править места использования.

Межпроцессного кэша нет намеренно. Флаги разрешаются один раз за запрос, источник правды
один — база, поэтому переопределение действует со следующего запроса в любом процессе.
Это и есть детерминированная инвалидация: нечего инвалидировать. Кэш появится, когда
измерения покажут, что он нужен, и тогда ключом станет счётчик изменений контура.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import AuthContext
from app.auth.permissions import Permission
from app.core.config import Settings
from app.core.features import REGISTRY, FlagDefinition, parse_overrides, resolve
from app.core.logging import get_logger
from app.domain import AuditAction, OverrideScope, ValueSource
from app.errors import DomainError, ErrorCode
from app.models import FeatureFlagOverride
from app.services import audit as audit_service

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EvaluationContext:
    """Кому вычисляем. Пусто — значит «вообще», без учёта арендатора."""

    workspace_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class FlagEvaluation:
    """Значение флага вместе с ответом на вопрос «почему именно такое»."""

    key: str
    value: bool
    source: ValueSource
    reason: str


class FlagProvider(Protocol):
    """Источник значений. Подмена провайдера не затрагивает места использования."""

    async def evaluate_all(self, context: EvaluationContext) -> dict[str, FlagEvaluation]: ...


class StaticFlagProvider:
    """Код плюс окружение, без базы.

    Запасной путь и он же обязательный: `/api/v1/meta` должен отвечать на установке,
    где таблиц переопределений ещё нет, — иначе первая же выкатка до миграции превращает
    страницу входа в пятисотку.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def evaluate_all(self, context: EvaluationContext) -> dict[str, FlagEvaluation]:
        resolved = resolve(
            self._settings.feature_flags,
            tenderhub_configured=self._settings.tenderhub_enabled,
        )
        overridden = set(self._settings.feature_flags.split(","))
        return {
            key: FlagEvaluation(
                key=key,
                value=value,
                source=ValueSource.DEPLOYMENT
                if any(chunk.strip().startswith(f"{key}=") for chunk in overridden)
                else ValueSource.DEFAULT,
                reason="значение из кода и окружения",
            )
            for key, value in resolved.items()
        }


class DatabaseFlagProvider:
    """Код, база, окружение — в порядке старшинства."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def evaluate_all(self, context: EvaluationContext) -> dict[str, FlagEvaluation]:
        overrides = await _load_overrides(self._session, context.workspace_id)
        environment = {
            key: value
            for key, value in _environment_overrides(self._settings).items()
            if key in REGISTRY
        }

        result: dict[str, FlagEvaluation] = {}
        for key, definition in REGISTRY.items():
            value = definition.default
            source = ValueSource.DEFAULT
            reason = "умолчание кода"

            system = overrides.get((key, OverrideScope.SYSTEM))
            if system is not None:
                value, source = system.enabled, ValueSource.SYSTEM
                reason = system.reason or "системное переопределение"

            workspace = overrides.get((key, OverrideScope.WORKSPACE))
            if workspace is not None and workspace.workspace_id == context.workspace_id:
                value, source = workspace.enabled, ValueSource.WORKSPACE
                reason = workspace.reason or "переопределение пространства"

            if key in environment:
                value, source = environment[key], ValueSource.DEPLOYMENT
                reason = "переменная окружения FEATURE_FLAGS"

            # Возможность, зависящая от внешней настройки, не может быть включена без неё.
            # Проверка стоит последней и перекрывает любое переопределение: обещание,
            # которого сервер не выполнит, не должно доезжать до интерфейса.
            if definition.follows_configuration:
                configured = _configuration_state(key, self._settings)
                if not configured:
                    value = False
                    reason = "не настроено: нет ключа доступа"

            result[key] = FlagEvaluation(key=key, value=value, source=source, reason=reason)
        return result


def _environment_overrides(settings: Settings) -> dict[str, bool]:
    return parse_overrides(settings.feature_flags)


def _configuration_state(key: str, settings: Settings) -> bool:
    """Настроена ли внешняя система, от которой зависит флаг."""
    if key == "integrations.tenderhub":
        return settings.tenderhub_enabled
    return True


async def _load_overrides(
    session: AsyncSession, workspace_id: uuid.UUID | None
) -> dict[tuple[str, OverrideScope], FeatureFlagOverride]:
    query = select(FeatureFlagOverride).where(
        (FeatureFlagOverride.workspace_id.is_(None))
        | (FeatureFlagOverride.workspace_id == workspace_id)
    )
    rows = (await session.execute(query)).scalars().all()
    return {(row.flag_key, row.scope): row for row in rows}


async def evaluate_all(
    session: AsyncSession | None, settings: Settings, context: EvaluationContext
) -> dict[str, FlagEvaluation]:
    """Все флаги для контекста. Отказ базы понижает до кодовых умолчаний, а не роняет запрос."""
    if session is None:
        return await StaticFlagProvider(settings).evaluate_all(context)
    try:
        return await DatabaseFlagProvider(session, settings).evaluate_all(context)
    except (SQLAlchemyError, ConnectionError, OSError, RuntimeError) as error:
        # Именно так и задумано: набор возможностей — не то, ради чего стоит отдавать
        # пятисотку. На неразмеченной базе портал обязан показать границу этапа из кода.
        # RuntimeError — в т.ч. «Event loop is closed» у кэшированного async-движка в тестах.
        log.warning("feature_flags_fallback", error_type=type(error).__name__)
        return await StaticFlagProvider(settings).evaluate_all(context)


async def as_mapping(
    session: AsyncSession | None, settings: Settings, context: EvaluationContext
) -> dict[str, bool]:
    """Плоский вид для `/api/v1/meta`: интерфейс читает именно его."""
    return {
        key: item.value for key, item in (await evaluate_all(session, settings, context)).items()
    }


def _definition_or_404(key: str) -> FlagDefinition:
    definition = REGISTRY.get(key)
    if definition is None:
        raise DomainError(ErrorCode.FLAG_UNKNOWN, f"Флага «{key}» нет в реестре")
    return definition


def _check(context: AuthContext, definition: FlagDefinition, scope: OverrideScope) -> None:
    context.require(Permission.FEATURE_FLAGS_MANAGE)
    if scope is OverrideScope.SYSTEM:
        context.require(Permission.SYSTEM_ADMIN)
    if scope is OverrideScope.WORKSPACE and not definition.workspace_scoped:
        raise DomainError(ErrorCode.FLAG_SCOPE_INVALID)
    if scope is OverrideScope.PROJECT:
        raise DomainError(ErrorCode.FLAG_SCOPE_INVALID, "Флаги не переопределяются на проекте")


async def set_override(
    session: AsyncSession,
    context: AuthContext,
    *,
    key: str,
    scope: OverrideScope,
    enabled: bool,
    reason: str | None,
    settings: Settings,
) -> FlagEvaluation:
    """Ставит переопределение флага."""
    definition = _definition_or_404(key)
    _check(context, definition, scope)

    # Незавершённую возможность включить нельзя — выключить можно всегда.
    if enabled and not definition.admin_editable:
        raise DomainError(
            ErrorCode.FLAG_NOT_EDITABLE,
            f"«{definition.title}» ещё не готова: флаг включается кодом, а не админкой",
        )
    if enabled and definition.follows_configuration and not _configuration_state(key, settings):
        raise DomainError(
            ErrorCode.FLAG_NOT_EDITABLE,
            f"«{definition.title}» не настроена: добавьте ключ доступа в окружение",
        )

    workspace_id = context.workspace_id if scope is OverrideScope.WORKSPACE else None
    existing = await _find(session, key=key, scope=scope, workspace_id=workspace_id)
    before = {"enabled": existing.enabled, "reason": existing.reason} if existing else None

    if existing is None:
        session.add(
            FeatureFlagOverride(
                flag_key=key,
                scope=scope,
                workspace_id=workspace_id,
                enabled=enabled,
                reason=reason,
                updated_by_user_id=context.principal.user_id,
            )
        )
    else:
        existing.enabled = enabled
        existing.reason = reason
        existing.updated_by_user_id = context.principal.user_id
    await session.flush()

    await audit_service.record(
        session,
        context,
        action=AuditAction.FEATURE_FLAG_OVERRIDE_SET,
        resource_type="feature_flag",
        resource_id=key,
        before=before,
        after={"enabled": enabled, "reason": reason, "scope": scope.value},
    )
    await session.commit()

    evaluated = await evaluate_all(
        session, settings, EvaluationContext(workspace_id=context.workspace_id)
    )
    return evaluated[key]


async def delete_override(
    session: AsyncSession,
    context: AuthContext,
    *,
    key: str,
    scope: OverrideScope,
    settings: Settings,
) -> FlagEvaluation:
    """Снимает переопределение: флаг возвращается к унаследованному значению."""
    definition = _definition_or_404(key)
    _check(context, definition, scope)

    workspace_id = context.workspace_id if scope is OverrideScope.WORKSPACE else None
    existing = await _find(session, key=key, scope=scope, workspace_id=workspace_id)
    if existing is not None:
        await session.delete(existing)
        await session.flush()
        await audit_service.record(
            session,
            context,
            action=AuditAction.FEATURE_FLAG_OVERRIDE_DELETED,
            resource_type="feature_flag",
            resource_id=key,
            before={"enabled": existing.enabled, "scope": scope.value},
        )
        await session.commit()

    evaluated = await evaluate_all(
        session, settings, EvaluationContext(workspace_id=context.workspace_id)
    )
    return evaluated[key]


async def _find(
    session: AsyncSession, *, key: str, scope: OverrideScope, workspace_id: uuid.UUID | None
) -> FeatureFlagOverride | None:
    query = select(FeatureFlagOverride).where(
        FeatureFlagOverride.flag_key == key, FeatureFlagOverride.scope == scope
    )
    query = (
        query.where(FeatureFlagOverride.workspace_id.is_(None))
        if workspace_id is None
        else query.where(FeatureFlagOverride.workspace_id == workspace_id)
    )
    return (await session.execute(query)).scalar_one_or_none()
