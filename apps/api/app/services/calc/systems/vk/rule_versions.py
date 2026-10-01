"""Версия правила по заявке калькулятора ВК (PROMPT 06, доработка для гейта).

Инженер вносит только то, что решает он: тип правила из допустимых заявкой, значения параметров,
основание и ограничения. Контракт реализации собирается по заявке (`rule_templates`), поэтому его
не набирают руками и не могут разойтись с кодом. Утверждение — обычной операцией реестра правил,
другим человеком.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.calc.enums import CalcRuleStatus
from app.contracts.calc.passport import CalcVkRuleVersionCreate
from app.contracts.calc.rules import CalcRuleCreate, CalcRuleDraftUpdate, CalcRuleVersionCreate
from app.domain import AuditAction
from app.errors import DomainError, ErrorCode
from app.models import CalcRuleDefinition, CalcRuleVersion
from app.services.calc.rules import registry
from app.services.calc.systems.vk.rule_needs import NEEDS_BY_KEY
from app.services.calc.systems.vk.rule_templates import rule_content


def _invalid(message: str) -> DomainError:
    return DomainError(ErrorCode.CALC_RULE_CONTENT_INVALID, message)


async def save(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    rule_key: str,
    payload: CalcVkRuleVersionCreate,
    author: uuid.UUID | None,
) -> tuple[CalcRuleDefinition, CalcRuleVersion, AuditAction]:
    """Черновик по заявке: новое правило, правка черновика или новая версия.

    LookupError — заявки с таким ключом нет.
    """
    need = NEEDS_BY_KEY.get(rule_key)
    if need is None:
        raise LookupError(rule_key)
    if payload.rule_type not in need.rule_types:
        allowed = ", ".join(item.value for item in need.rule_types)
        raise _invalid(f"тип {payload.rule_type.value} заявкой не допускается: {allowed}")
    given = [item.name for item in payload.parameters]
    expected = sorted(term.name for term in need.parameters)
    if sorted(given) != expected:
        raise _invalid("нужны ровно параметры заявки: " + (", ".join(expected) or "без параметров"))
    try:
        content = rule_content(
            need,
            {item.name: item.value for item in payload.parameters},
            sources=[item.model_dump(mode="json") for item in payload.sources],
            rule_type=payload.rule_type,
            impact=payload.impact,
            limitations=payload.limitations,
        )
    except ValueError as error:
        raise _invalid(str(error)) from error

    definition = await registry.get_rule(session, workspace_id=workspace_id, rule_key=rule_key)
    if definition is None:
        created, row = await registry.create_rule(
            session,
            workspace_id=workspace_id,
            payload=CalcRuleCreate(rule_key=rule_key, content=content),
            author=author,
        )
        return created, row, AuditAction.CALC_RULE_CREATED
    draft = next(
        (item for item in definition.versions if item.status is CalcRuleStatus.DRAFT), None
    )
    if draft is not None:
        updated, row = await registry.update_draft(
            session,
            workspace_id=workspace_id,
            rule_key=rule_key,
            version=draft.version,
            payload=CalcRuleDraftUpdate(content=content),
            editor=author,
        )
        return updated, row, AuditAction.CALC_RULE_DRAFT_UPDATED
    if payload.change_reason is None:
        raise _invalid("у правила уже есть решённые версии: укажите причину новой версии")
    extended, row = await registry.create_version(
        session,
        workspace_id=workspace_id,
        rule_key=rule_key,
        payload=CalcRuleVersionCreate(change_reason=payload.change_reason, content=content),
        author=author,
    )
    return extended, row, AuditAction.CALC_RULE_VERSION_CREATED
