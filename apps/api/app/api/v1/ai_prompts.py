"""Версии промтов ИИ-проверки вида CAD: правка в админке и статистика прогонов.

Удаления нет: версия, на которую ссылаются прогоны, остаётся в истории.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.deps import AuthDep, SessionDep, require
from app.auth.permissions import Permission
from app.contracts.ai_prompts import (
    AiPromptCreate,
    AiPromptRead,
    AiPromptStats,
    AiPromptSummary,
)
from app.contracts.cad_ai_review import AiPromptRole
from app.models import AiPromptVersion
from app.services import ai_prompts as service

router = APIRouter(
    prefix="/admin/ai-prompts",
    tags=["admin"],
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)


def _summary(row: AiPromptVersion) -> AiPromptSummary:
    return AiPromptSummary.model_validate(
        {
            "id": row.id,
            "role": row.role,
            "version": row.version,
            "status": row.status,
            "note": row.note,
            "created_by": row.created_by,
            "created_at": row.created_at,
            "activated_at": row.activated_at,
            "text_bytes": len(row.text.encode()),
        }
    )


def _read(row: AiPromptVersion) -> AiPromptRead:
    return AiPromptRead(**_summary(row).model_dump(), text=row.text)


@router.get("", response_model=list[AiPromptSummary], summary="Версии промтов ИИ")
async def list_ai_prompts(
    session: SessionDep,
    role: Annotated[
        AiPromptRole | None, Query(description="Роль: corrector, verifier, vor_mapper или style")
    ] = None,
) -> list[AiPromptSummary]:
    return [_summary(row) for row in await service.list_versions(session, role)]


# Статика объявлена раньше `/{prompt_id}`: иначе «stats» разбирался бы как идентификатор.
@router.get("/stats", response_model=AiPromptStats, summary="Статистика прогонов по версиям")
async def ai_prompt_stats(session: SessionDep) -> AiPromptStats:
    return AiPromptStats(rows=await service.stats(session))


@router.post(
    "",
    response_model=AiPromptRead,
    status_code=status.HTTP_201_CREATED,
    summary="Новая версия промта (черновик)",
)
async def create_ai_prompt(
    body: AiPromptCreate, session: SessionDep, context: AuthDep
) -> AiPromptRead:
    return _read(await service.create_version(session, body, context.principal.user_id))


@router.get("/{prompt_id}", response_model=AiPromptRead, summary="Версия промта с текстом")
async def get_ai_prompt(prompt_id: uuid.UUID, session: SessionDep) -> AiPromptRead:
    return _read(await service.get_version(session, prompt_id))


@router.post(
    "/{prompt_id}/activate",
    response_model=AiPromptRead,
    summary="Сделать версию активной",
)
async def activate_ai_prompt(prompt_id: uuid.UUID, session: SessionDep) -> AiPromptRead:
    return _read(await service.activate_version(session, prompt_id))
