"""Вопросы к документации (ADR-0043, шаг 2, В3): чтение, ответы человека, отказ от кандидата.

Ответ создаёт только человек: из кандидата поиска (`document`), вводом (`manual`), принятием
норматива-допущения каталога (`norm_assumption`) либо отметкой «в проекте нет»
(`not_in_project`). Модель чисел не выдаёт; норматив - допущение со ссылкой на пункт СП, а не
ответ проекта, и попадает в ответы только по явному решению. Ответ хранит снимок происхождения
и не зависит от судьбы кандидата. Один ответ на вопрос в области (корпус, секция; NULL - весь
проект): повторное подтверждение заменяет прежний. Доступ к проекту проверяет вызывающий.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.doc_questions import (
    DocAnswerFlatOut,
    DocAnswerIn,
    DocAnswerOut,
    DocAnswerSource,
    DocAnswersOut,
    DocAssumptionOut,
    DocCandidateOut,
    DocCandidateStatus,
    DocQuestionOut,
    DocScopeOut,
    DocumentAnswerIn,
    DocValueOut,
    ManualAnswerIn,
    ManualValueIn,
    NormAssumptionAnswerIn,
    NotInProjectAnswerIn,
)
from app.errors import ErrorCode, http_error, not_found
from app.models import DocQuestionAnswer, DocQuestionCandidate, Project
from app.services.consistency.doc_questions import (
    DOC_QUESTIONS,
    DOC_QUESTIONS_VERSION,
    DocQuestion,
    DocQuestionCode,
    DocValueKind,
    NormAssumption,
    question_by_code,
)
from app.services.doc_questions import value_text_of

_ROSETTE_CODES: Final = frozenset({"rosette_down", "rosette_up"})
_ROUND_CODE: Final = "round"
_QUESTION_ORDER: Final = {
    question.code.value: index for index, question in enumerate(DOC_QUESTIONS)
}


def _invalid(message: str) -> Exception:
    return http_error(ErrorCode.VALIDATION_FAILED, message=message)


# --------------------------------------------------------------------------- выходные модели


def _value_out(value: dict[str, Any] | None) -> DocValueOut | None:
    return None if value is None else DocValueOut.model_validate(value)


def _candidate_out(row: DocQuestionCandidate) -> DocCandidateOut:
    return DocCandidateOut(
        id=row.id,
        question_code=row.question_code,
        value=DocValueOut.model_validate(row.value),
        value_text=row.value_text,
        quote=row.quote,
        revision_id=row.revision_id,
        page_index=row.page_index,
        page_label=row.page_label,
        file_name=row.file_name,
        building=row.building,
        section=row.section,
        level=row.level,
        score=row.score,
        occurrences=row.occurrences,
        status=DocCandidateStatus(row.status),
        versions={str(key): str(item) for key, item in row.versions.items()},
        created_at=row.created_at,
    )


def _answer_out(row: DocQuestionAnswer) -> DocAnswerOut:
    return DocAnswerOut.model_validate(
        {
            "id": row.id,
            "question_code": row.question_code,
            "source": row.source,
            "scope_building": row.scope_building,
            "scope_section": row.scope_section,
            "value": row.value,
            "value_text": row.value_text,
            "candidate_id": row.candidate_id,
            "file_name": row.file_name,
            "revision_id": row.revision_id,
            "page_index": row.page_index,
            "quote": row.quote,
            "norm_ref": row.norm_ref,
            "note": row.note,
            "catalog_version": row.catalog_version,
            "confirmed_by": row.confirmed_by,
            "confirmed_at": row.confirmed_at,
        }
    )


def _assumption_out(assumption: NormAssumption | None) -> DocAssumptionOut | None:
    if assumption is None:
        return None
    return DocAssumptionOut(
        mm_from=assumption.mm_from,
        mm_to=assumption.mm_to,
        reference=assumption.reference,
        status=assumption.status.value,
        note=assumption.note,
    )


def _answer_order(row: DocQuestionAnswer) -> tuple[str, str]:
    return (row.scope_building or "", row.scope_section or "")


# --------------------------------------------------------------------------- чтение


async def questions_view(
    session: AsyncSession, *, project_id: uuid.UUID
) -> tuple[list[DocQuestionOut], str]:
    """Каталог с кандидатами (по убыванию оценки) и ответами по областям; версия каталога."""
    candidates: dict[str, list[DocCandidateOut]] = defaultdict(list)
    rows = await session.scalars(
        select(DocQuestionCandidate)
        .where(
            DocQuestionCandidate.project_id == project_id,
            DocQuestionCandidate.status == DocCandidateStatus.CANDIDATE.value,
        )
        .order_by(
            DocQuestionCandidate.score.desc(),
            DocQuestionCandidate.occurrences.desc(),
            DocQuestionCandidate.file_name,
            DocQuestionCandidate.page_index,
            DocQuestionCandidate.id,
        )
    )
    for row in rows:
        candidates[row.question_code].append(_candidate_out(row))
    answers: dict[str, list[DocQuestionAnswer]] = defaultdict(list)
    for answer in await session.scalars(
        select(DocQuestionAnswer).where(DocQuestionAnswer.project_id == project_id)
    ):
        answers[answer.question_code].append(answer)
    questions = [
        DocQuestionOut(
            code=question.code.value,
            title=question.title,
            receiver_param=question.receiver_param,
            value_kind=question.value_kind.value,
            min_mm=question.min_mm,
            max_mm=question.max_mm,
            assumption=_assumption_out(question.assumption),
            candidates=candidates.get(question.code.value, []),
            answers=[
                _answer_out(answer)
                for answer in sorted(answers.get(question.code.value, []), key=_answer_order)
            ],
        )
        for question in DOC_QUESTIONS
    ]
    return questions, DOC_QUESTIONS_VERSION


async def list_answers(session: AsyncSession, *, project_id: uuid.UUID) -> DocAnswersOut:
    """Подтверждённые ответы проекта плоским списком с происхождением (контракт CAD-трасс)."""
    rows = await session.scalars(
        select(DocQuestionAnswer).where(DocQuestionAnswer.project_id == project_id)
    )
    known = [row for row in rows if row.question_code in _QUESTION_ORDER]
    known.sort(key=lambda row: (_QUESTION_ORDER[row.question_code], *_answer_order(row)))
    items = [
        DocAnswerFlatOut(
            answer_id=row.id,
            question_code=row.question_code,
            receiver_param=question_by_code(DocQuestionCode(row.question_code)).receiver_param,
            value=_value_out(row.value),
            value_text=row.value_text,
            source=DocAnswerSource(row.source),
            scope=DocScopeOut(building=row.scope_building, section=row.scope_section),
            file_name=row.file_name,
            revision_id=row.revision_id,
            page_index=row.page_index,
            quote=row.quote,
            norm_ref=row.norm_ref,
            note=row.note,
            catalog_version=row.catalog_version,
            confirmed_at=row.confirmed_at,
        )
        for row in known
    ]
    return DocAnswersOut(items=items)


# --------------------------------------------------------------------------- проверка значения


def _check_numbers(question: DocQuestion, numbers: list[int]) -> None:
    for number in numbers:
        if not question.min_mm <= number <= question.max_mm:
            raise _invalid(f"размер {number} мм вне допустимых {question.min_mm}-{question.max_mm}")


def manual_value(question: DocQuestion, value: ManualValueIn, value_text: str) -> dict[str, Any]:
    """Значение ручного ответа по виду вопроса; `display` собирает сервер. Иначе 422."""
    numbers = list(value.numbers)
    kind = question.value_kind
    if value.qualifier is not None and kind not in (DocValueKind.LENGTH_MM, DocValueKind.RANGE_MM):
        raise _invalid("«не менее / не более» применимо только к длине и диапазону")
    code = value.code
    display = value_text
    match kind:
        case DocValueKind.LENGTH_MM:
            if code is not None:
                raise _invalid("для длины код не задаётся")
            if len(numbers) != 1:
                raise _invalid("для длины нужно одно число, мм")
            display = str(numbers[0])
        case DocValueKind.RANGE_MM:
            if code is not None:
                raise _invalid("для диапазона код не задаётся")
            if len(numbers) == 2 and numbers[0] >= numbers[1]:
                raise _invalid("в диапазоне «от» должно быть меньше «до»")
            if len(numbers) not in (1, 2):
                raise _invalid("для диапазона нужно одно или два числа, мм")
            display = "-".join(str(item) for item in numbers)
        case DocValueKind.SECTION_MM:
            round_ok = question.code is DocQuestionCode.DUCT_SECTION and code == _ROUND_CODE
            if round_ok and len(numbers) == 1:
                display = f"Ø{numbers[0]}"
            elif len(numbers) == 2 and code is None:
                display = f"{numbers[0]}x{numbers[1]}"
            else:
                raise _invalid("для сечения нужны ширина и высота, мм (круглое - один диаметр)")
        case DocValueKind.ENUM:
            if numbers or (code is not None and code not in _ROSETTE_CODES):
                raise _invalid(
                    "для перечисления числа не задаются, код - rosette_down / rosette_up"
                )
        case DocValueKind.TEXT:
            if code is not None:
                raise _invalid("для текстового значения код не задаётся")
    _check_numbers(question, numbers)
    return {
        "kind": kind.value,
        "display": display,
        "numbers": numbers,
        "qualifier": value.qualifier,
        "code": code,
    }


def assumption_value(question: DocQuestion, assumption: NormAssumption) -> dict[str, Any]:
    """Значение норматива: «от - до» либо «не менее»; берётся из каталога, не вводится."""
    if assumption.mm_to is None:
        return {
            "kind": question.value_kind.value,
            "display": str(assumption.mm_from),
            "numbers": [assumption.mm_from],
            "qualifier": "min",
            "code": None,
        }
    return {
        "kind": DocValueKind.RANGE_MM.value,
        "display": f"{assumption.mm_from}-{assumption.mm_to}",
        "numbers": [assumption.mm_from, assumption.mm_to],
        "qualifier": None,
        "code": None,
    }


# --------------------------------------------------------------------------- ответы


async def _candidate_of(
    session: AsyncSession, *, project_id: uuid.UUID, candidate_id: uuid.UUID
) -> DocQuestionCandidate:
    row = await session.scalar(
        select(DocQuestionCandidate).where(
            DocQuestionCandidate.id == candidate_id, DocQuestionCandidate.project_id == project_id
        )
    )
    if row is None:
        raise not_found("Кандидат")
    return row


async def _fields_for(
    session: AsyncSession, *, project_id: uuid.UUID, question: DocQuestion, body: DocAnswerIn
) -> dict[str, Any]:
    """Поля ответа по источнику; незаполняемые поля явно None - замена не оставляет старого."""
    fields: dict[str, Any] = {
        "scope_building": body.scope_building,
        "scope_section": body.scope_section,
        "source": body.source,
        "value": None,
        "value_text": None,
        "candidate_id": None,
        "file_name": None,
        "revision_id": None,
        "page_index": None,
        "quote": None,
        "norm_ref": None,
        "note": body.note,
    }
    if isinstance(body, DocumentAnswerIn):
        candidate = await _candidate_of(
            session, project_id=project_id, candidate_id=body.candidate_id
        )
        if candidate.question_code != question.code.value:
            raise _invalid("кандидат относится к другому вопросу")
        if candidate.status != DocCandidateStatus.CANDIDATE.value:
            raise _invalid("кандидат отклонён")
        if not ({"scope_building", "scope_section"} & body.model_fields_set):
            fields["scope_building"], fields["scope_section"] = (
                candidate.building,
                candidate.section,
            )
        fields.update(
            value=candidate.value,
            value_text=candidate.value_text,
            candidate_id=candidate.id,
            file_name=candidate.file_name,
            revision_id=candidate.revision_id,
            page_index=candidate.page_index,
            quote=candidate.quote,
        )
    elif isinstance(body, ManualAnswerIn):
        value = manual_value(question, body.value, body.value_text)
        fields.update(value=value, value_text=body.value_text)
    elif isinstance(body, NormAssumptionAnswerIn):
        assumption = question.assumption
        if assumption is None:
            raise _invalid("у этого вопроса нет норматива-допущения")
        value = assumption_value(question, assumption)
        fields.update(
            value=value,
            value_text=f"{value_text_of(value)} ({assumption.reference})",
            norm_ref=assumption.reference,
            note=body.note or assumption.note,
        )
    elif isinstance(body, NotInProjectAnswerIn):
        pass
    return fields


async def create_answer(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    code: DocQuestionCode,
    body: DocAnswerIn,
    user_id: uuid.UUID,
) -> DocAnswerOut:
    """Подтверждает ответ; ответ в той же области заменяется (id сохраняется).

    Строка проекта берётся под блокировкой: два подтверждения в одной области подряд не
    упираются в уникальный индекс, а встают в очередь и заменяют друг друга.
    """
    question = question_by_code(code)
    await session.execute(select(Project.id).where(Project.id == project_id).with_for_update())
    fields = await _fields_for(session, project_id=project_id, question=question, body=body)
    existing = await session.scalar(
        select(DocQuestionAnswer)
        .where(
            DocQuestionAnswer.project_id == project_id,
            DocQuestionAnswer.question_code == code.value,
            func.coalesce(DocQuestionAnswer.scope_building, "") == (fields["scope_building"] or ""),
            func.coalesce(DocQuestionAnswer.scope_section, "") == (fields["scope_section"] or ""),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = existing or DocQuestionAnswer(project_id=project_id, question_code=code.value)
    for name, value in fields.items():
        setattr(row, name, value)
    row.catalog_version = DOC_QUESTIONS_VERSION
    row.confirmed_by = user_id
    row.confirmed_at = datetime.now(UTC)
    if existing is None:
        session.add(row)
    await session.flush()
    return _answer_out(row)


async def delete_answer(
    session: AsyncSession, *, project_id: uuid.UUID, answer_id: uuid.UUID
) -> None:
    row = await session.scalar(
        select(DocQuestionAnswer).where(
            DocQuestionAnswer.id == answer_id, DocQuestionAnswer.project_id == project_id
        )
    )
    if row is None:
        raise not_found("Ответ")
    await session.delete(row)
    await session.flush()


async def reject_candidate(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    user_id: uuid.UUID,
) -> DocCandidateOut:
    """Отклоняет кандидата; повторный поиск его не воскрешает. Повторный отказ - без изменений."""
    row = await session.scalar(
        select(DocQuestionCandidate)
        .where(
            DocQuestionCandidate.id == candidate_id, DocQuestionCandidate.project_id == project_id
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise not_found("Кандидат")
    if row.status != DocCandidateStatus.REJECTED.value:
        row.status = DocCandidateStatus.REJECTED.value
        row.reviewed_by = user_id
        row.reviewed_at = datetime.now(UTC)
        await session.flush()
    return _candidate_out(row)
