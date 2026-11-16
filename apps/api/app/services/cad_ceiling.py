"""Подвесной потолок коридора для трасс механики: из подтверждённого ответа к документации.

Вопрос каталога `corridor_ceiling_height` (receiver_param `corridor_ceiling_height_mm`). Отбор -
как у высоты в свету (`cad_sections`): флаг `project.consistency`, ответы `document` и `manual` с
числом, самая точная область для листа по подтверждённому паспорту. Нет ответа - ничего не
передаётся: движок сам берёт допущение и выдаёт замечание.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import DocQuestionAnswer
from app.services import cad_mep as cad_mep_service
from app.services.cad_sections import (
    _DOC_SOURCES,
    WARNING_DOC_AMBIGUOUS,
    WARNING_DOC_OUT_OF_RANGE,
    DocAnswerOrigin,
    _doc_answers_enabled,
    _first_number,
    _plan_passport_marks,
    _scope_rank,
)
from app.services.consistency.doc_questions import DocQuestionCode

_QUESTION: Final = DocQuestionCode.CORRIDOR_CEILING_HEIGHT.value
CEILING_HEIGHT_MIN_MM: Final = cad_mep_service.CEILING_HEIGHT_MIN_MM
CEILING_HEIGHT_MAX_MM: Final = cad_mep_service.CEILING_HEIGHT_MAX_MM
WARNING_CEILING_AMBIGUOUS: Final = "ceiling_doc_ambiguous"
WARNING_CEILING_OUT_OF_RANGE: Final = "ceiling_doc_out_of_range"

# Те же причины, что у высоты в свету, но свои коды для показа в задании.
_WARNING_CODES: Final = {
    WARNING_DOC_AMBIGUOUS: WARNING_CEILING_AMBIGUOUS,
    WARNING_DOC_OUT_OF_RANGE: WARNING_CEILING_OUT_OF_RANGE,
}


@dataclass(frozen=True, slots=True)
class CeilingHeight:
    """Высота подвесного потолка коридора для генератора и откуда она взята."""

    ceiling_height_mm: int | None = None
    doc_answer: DocAnswerOrigin | None = None
    warnings: tuple[str, ...] = ()


async def resolve_ceiling_height(
    session: AsyncSession,
    *,
    settings: Settings,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    plan_revision_id: uuid.UUID,
    plan_page_index: int,
) -> CeilingHeight:
    """Подтверждённый ответ о потолке коридора для листа плана либо пусто (и предупреждение)."""
    if not await _doc_answers_enabled(session, settings, workspace_id):
        return CeilingHeight()
    rows = list(
        (
            await session.scalars(
                select(DocQuestionAnswer)
                .where(
                    DocQuestionAnswer.project_id == project_id,
                    DocQuestionAnswer.question_code == _QUESTION,
                    DocQuestionAnswer.source.in_(_DOC_SOURCES),
                    DocQuestionAnswer.value.is_not(None),
                )
                .order_by(DocQuestionAnswer.confirmed_at.desc(), DocQuestionAnswer.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if not rows:
        return CeilingHeight()
    building, section = await _plan_passport_marks(
        session, revision_id=plan_revision_id, page_index=plan_page_index
    )
    ranked = [
        (rank, row)
        for row in rows
        if _first_number(row) is not None
        and (rank := _scope_rank(row, building, section)) is not None
    ]
    if not ranked:
        return CeilingHeight()
    best = max(rank for rank, _ in ranked)
    top = [row for rank, row in ranked if rank == best]
    if len({_first_number(row) for row in top}) > 1:
        return CeilingHeight(warnings=(_WARNING_CODES[WARNING_DOC_AMBIGUOUS],))
    chosen = top[0]
    number = _first_number(chosen)
    if number is None or not CEILING_HEIGHT_MIN_MM <= number <= CEILING_HEIGHT_MAX_MM:
        return CeilingHeight(warnings=(_WARNING_CODES[WARNING_DOC_OUT_OF_RANGE],))
    return CeilingHeight(
        ceiling_height_mm=number,
        doc_answer=DocAnswerOrigin(
            answer_id=chosen.id,
            question_code=chosen.question_code,
            answer_source=chosen.source,
            file_name=chosen.file_name,
            page_index=chosen.page_index,
        ),
    )
