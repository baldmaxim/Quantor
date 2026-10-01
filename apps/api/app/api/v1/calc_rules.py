"""API реестра правил расчётного контура (ADR-0030, PROMPT 03).

Правила Quantor — версии в рабочем пространстве: черновик, утверждение, отклонение, вывод из
действия. Утверждённая версия на месте не меняется — только новой версией; удаления нет ни у
одной версии. Правила старого портала — карантинный каталог только для чтения: их нельзя
изменить, утвердить или вывести из действия, из них можно только завести новый черновик.

Закрыто флагом `calc.portal`; пути — под `/calc/`, без маркеров обмера и `/mep/`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.context import AuthContext
from app.auth.permissions import Permission
from app.contracts.calc.enums import (
    CalcDiscipline,
    CalcLegacyAction,
    CalcLegacyCatalog,
    CalcLegacyClass,
    CalcLegacyHazard,
    CalcRuleStatus,
    CalcRuleType,
)
from app.contracts.calc.rules import (
    CalcLegacyCatalogRead,
    CalcLegacyRuleRead,
    CalcRuleApprove,
    CalcRuleCreate,
    CalcRuleDecision,
    CalcRuleDraftUpdate,
    CalcRuleFromLegacy,
    CalcRuleRead,
    CalcRuleSummaryRead,
    CalcRuleVersionCreate,
    CalcRuleVersionRead,
)
from app.contracts.calc.subjects import normalize_system_code
from app.domain import AuditAction
from app.errors import not_found
from app.models import CalcRuleDefinition, CalcRuleVersion
from app.services import audit as audit_service
from app.services.calc.rules import registry
from app.services.calc.rules.legacy import catalog_read, load_catalog

router = APIRouter(prefix="/calc", tags=["calc"], dependencies=[require_feature("calc.portal")])

_RULE = "Правило"


async def audit_rule_version(
    session: SessionDep,
    context: AuthContext,
    action: AuditAction,
    definition: CalcRuleDefinition,
    row: CalcRuleVersion,
) -> None:
    await audit_service.record(
        session,
        context,
        action=action,
        resource_type="calc_rule_version",
        resource_id=str(row.id),
        after={
            "rule_key": definition.rule_key,
            "version": row.version,
            "status": row.status.value,
            "rule_type": row.rule_type.value,
            "content_sha256": row.content_sha256,
        },
    )


# ------------------------------------------------------------------------------ правила


@router.get(
    "/rules",
    response_model=list[CalcRuleSummaryRead],
    summary="Правила реестра",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_rules(
    session: SessionDep,
    context: AuthDep,
    discipline: Annotated[CalcDiscipline | None, Query()] = None,
    system: Annotated[str | None, Query(max_length=64)] = None,
    rule_type: Annotated[CalcRuleType | None, Query()] = None,
    rule_status: Annotated[CalcRuleStatus | None, Query(alias="status")] = None,
) -> list[CalcRuleSummaryRead]:
    """По строке на правило: последняя версия, действующая утверждённая, разрешено ли в расчёте."""
    return await registry.list_rules(
        session,
        workspace_id=context.tenant,
        discipline=discipline,
        system=None if system is None else normalize_system_code(system),
        rule_type=rule_type,
        status=rule_status,
        on=registry.today(),
    )


@router.post(
    "/rules",
    response_model=CalcRuleVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Завести правило-черновик",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_rule(
    payload: CalcRuleCreate, session: SessionDep, context: AuthDep
) -> CalcRuleVersionRead:
    definition, row = await registry.create_rule(
        session,
        workspace_id=context.tenant,
        payload=payload,
        author=context.principal.user_id,
    )
    await audit_rule_version(session, context, AuditAction.CALC_RULE_CREATED, definition, row)
    await session.commit()
    return registry.version_read(definition, row, registry.today())


@router.get(
    "/rules/{rule_key}",
    response_model=CalcRuleRead,
    summary="Правило и все его версии",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_rule(rule_key: str, session: SessionDep, context: AuthDep) -> CalcRuleRead:
    definition = await registry.get_rule(session, workspace_id=context.tenant, rule_key=rule_key)
    if definition is None:
        raise not_found(_RULE)
    return registry.rule_read(definition, registry.today())


@router.get(
    "/rules/{rule_key}/versions/{version}",
    response_model=CalcRuleVersionRead,
    summary="Версия правила",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_rule_version(
    rule_key: str, version: int, session: SessionDep, context: AuthDep
) -> CalcRuleVersionRead:
    """Любая версия по номеру — и устаревшая: по ней воспроизводится старый расчёт."""
    definition = await registry.get_rule(session, workspace_id=context.tenant, rule_key=rule_key)
    row = next(
        (item for item in (definition.versions if definition else []) if item.version == version),
        None,
    )
    if definition is None or row is None:
        raise not_found(_RULE)
    return registry.version_read(definition, row, registry.today())


@router.put(
    "/rules/{rule_key}/versions/{version}",
    response_model=CalcRuleVersionRead,
    summary="Изменить черновик",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def update_calc_rule_draft(
    rule_key: str,
    version: int,
    payload: CalcRuleDraftUpdate,
    session: SessionDep,
    context: AuthDep,
) -> CalcRuleVersionRead:
    """Только черновик. Утверждённую версию на месте не изменить — 409, нужна новая версия."""
    try:
        definition, row = await registry.update_draft(
            session,
            workspace_id=context.tenant,
            rule_key=rule_key,
            version=version,
            payload=payload,
            editor=context.principal.user_id,
        )
    except LookupError:
        raise not_found(_RULE) from None
    await audit_rule_version(session, context, AuditAction.CALC_RULE_DRAFT_UPDATED, definition, row)
    await session.commit()
    return registry.version_read(definition, row, registry.today())


@router.post(
    "/rules/{rule_key}/versions",
    response_model=CalcRuleVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Новая версия правила",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_rule_version(
    rule_key: str, payload: CalcRuleVersionCreate, session: SessionDep, context: AuthDep
) -> CalcRuleVersionRead:
    try:
        definition, row = await registry.create_version(
            session,
            workspace_id=context.tenant,
            rule_key=rule_key,
            payload=payload,
            author=context.principal.user_id,
        )
    except LookupError:
        raise not_found(_RULE) from None
    await audit_rule_version(
        session, context, AuditAction.CALC_RULE_VERSION_CREATED, definition, row
    )
    await session.commit()
    return registry.version_read(definition, row, registry.today())


@router.post(
    "/rules/{rule_key}/versions/{version}/approve",
    response_model=CalcRuleVersionRead,
    summary="Утвердить версию правила",
    dependencies=[require(Permission.CALC_VERIFY)],
)
async def approve_calc_rule_version(
    rule_key: str,
    version: int,
    payload: CalcRuleApprove,
    session: SessionDep,
    context: AuthDep,
) -> CalcRuleVersionRead:
    """Основание по типу правила и разбор каждой опасности старых правил — обязательны."""
    try:
        definition, row, previous = await registry.approve(
            session,
            workspace_id=context.tenant,
            rule_key=rule_key,
            version=version,
            payload=payload,
            reviewer=context.principal.user_id,
        )
    except LookupError:
        raise not_found(_RULE) from None
    if previous is not None:
        await audit_rule_version(
            session, context, AuditAction.CALC_RULE_DEPRECATED, definition, previous
        )
    await audit_rule_version(session, context, AuditAction.CALC_RULE_APPROVED, definition, row)
    await session.commit()
    return registry.version_read(definition, row, registry.today())


@router.post(
    "/rules/{rule_key}/versions/{version}/reject",
    response_model=CalcRuleVersionRead,
    summary="Отклонить черновик правила",
    dependencies=[require(Permission.CALC_VERIFY)],
)
async def reject_calc_rule_version(
    rule_key: str,
    version: int,
    payload: CalcRuleDecision,
    session: SessionDep,
    context: AuthDep,
) -> CalcRuleVersionRead:
    try:
        definition, row = await registry.reject(
            session,
            workspace_id=context.tenant,
            rule_key=rule_key,
            version=version,
            payload=payload,
            reviewer=context.principal.user_id,
        )
    except LookupError:
        raise not_found(_RULE) from None
    await audit_rule_version(session, context, AuditAction.CALC_RULE_REJECTED, definition, row)
    await session.commit()
    return registry.version_read(definition, row, registry.today())


@router.post(
    "/rules/{rule_key}/versions/{version}/deprecate",
    response_model=CalcRuleVersionRead,
    summary="Вывести утверждённую версию из действия",
    dependencies=[require(Permission.CALC_VERIFY)],
)
async def deprecate_calc_rule_version(
    rule_key: str,
    version: int,
    payload: CalcRuleDecision,
    session: SessionDep,
    context: AuthDep,
) -> CalcRuleVersionRead:
    """Версия остаётся доступной по номеру, но для нового расчёта не выбирается."""
    try:
        definition, row = await registry.deprecate(
            session,
            workspace_id=context.tenant,
            rule_key=rule_key,
            version=version,
            payload=payload,
            reviewer=context.principal.user_id,
        )
    except LookupError:
        raise not_found(_RULE) from None
    await audit_rule_version(session, context, AuditAction.CALC_RULE_DEPRECATED, definition, row)
    await session.commit()
    return registry.version_read(definition, row, registry.today())


# ------------------------------------------------------------------ старый портал: карантин


@router.get(
    "/legacy-rules",
    response_model=CalcLegacyCatalogRead,
    summary="Правила старого портала — карантин",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_legacy_rules(
    catalog: Annotated[CalcLegacyCatalog | None, Query()] = None,
    legacy_class: Annotated[CalcLegacyClass | None, Query()] = None,
    hazard: Annotated[CalcLegacyHazard | None, Query()] = None,
    action: Annotated[CalcLegacyAction | None, Query()] = None,
    group_id: Annotated[str | None, Query(max_length=64)] = None,
) -> CalcLegacyCatalogRead:
    """Все 365 записей: не проверены и в расчёте не используются. Только чтение."""
    return catalog_read(
        catalog=catalog, legacy_class=legacy_class, hazard=hazard, action=action, group_id=group_id
    )


@router.get(
    "/legacy-rules/{legacy_id}",
    response_model=CalcLegacyRuleRead,
    summary="Правило старого портала",
    dependencies=[require(Permission.CALC_READ)],
)
async def get_calc_legacy_rule(legacy_id: str) -> CalcLegacyRuleRead:
    entry = load_catalog().get(legacy_id)
    if entry is None:
        raise not_found("Правило старого портала")
    return entry


@router.post(
    "/legacy-rules/{legacy_id}/drafts",
    response_model=CalcRuleVersionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Завести черновик по правилу старого портала",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_rule_from_legacy(
    legacy_id: str, payload: CalcRuleFromLegacy, session: SessionDep, context: AuthDep
) -> CalcRuleVersionRead:
    """Новое правило со своим ключом и версией 1 в статусе DRAFT; старое остаётся как было."""
    entry = load_catalog().get(legacy_id)
    if entry is None:
        raise not_found("Правило старого портала")
    definition, row = await registry.create_from_legacy(
        session,
        workspace_id=context.tenant,
        entry=entry,
        payload=payload,
        author=context.principal.user_id,
    )
    await audit_rule_version(session, context, AuditAction.CALC_RULE_CREATED, definition, row)
    await session.commit()
    return registry.version_read(definition, row, registry.today())
