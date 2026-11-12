"""Вопросы к документации (ADR-0043, шаг 2, В3): поиск кандидатов, ответы, отказ, выдача ответов.

Маршруты закрыты флагом пространства `project.consistency` на сервере; чтение - право чтения
документов, запуск поиска и ответы - право загрузки. Чужой проект - 404. Подтверждающий -
текущий пользователь.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.auth.resolver import require_authenticated
from app.contracts.doc_questions import (
    DocAnswerIn,
    DocAnswerOut,
    DocAnswersOut,
    DocCandidateOut,
    DocQuestionsOut,
)
from app.errors import not_found
from app.models import Project
from app.schemas import JobRead
from app.services import doc_answers, doc_questions
from app.services import projects as projects_service
from app.services.consistency.doc_questions import DocQuestionCode

router = APIRouter(
    tags=["doc-questions"],
    dependencies=[require_feature("project.consistency")],
)


async def _project(session: SessionDep, context: AuthDep, project_id: uuid.UUID) -> Project:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")
    return project


@router.post(
    "/projects/{project_id}/doc-questions/search",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить поиск ответов на вопросы к документации; активное задание возвращается",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def start_doc_questions_search(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> JobRead:
    project = await _project(session, context, project_id)
    job = await doc_questions.schedule_search(session, project=project)
    response = JobRead.model_validate(job)
    await session.commit()
    return response


@router.get(
    "/projects/{project_id}/doc-questions",
    response_model=DocQuestionsOut,
    summary="Каталог вопросов с кандидатами и ответами по областям и итог последнего поиска",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def get_doc_questions(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> DocQuestionsOut:
    await _project(session, context, project_id)
    questions, catalog_version = await doc_answers.questions_view(session, project_id=project_id)
    last_search = await doc_questions.latest_search_summary(
        session, workspace_id=context.tenant, project_id=project_id
    )
    return DocQuestionsOut(
        catalog_version=catalog_version, questions=questions, last_search=last_search
    )


@router.post(
    "/projects/{project_id}/doc-questions/{code}/answers",
    response_model=DocAnswerOut,
    summary="Подтвердить ответ на вопрос; ответ в той же области заменяется",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def put_doc_answer(
    project_id: uuid.UUID,
    code: DocQuestionCode,
    body: DocAnswerIn,
    session: SessionDep,
    context: AuthDep,
) -> DocAnswerOut:
    await _project(session, context, project_id)
    response = await doc_answers.create_answer(
        session,
        project_id=project_id,
        code=code,
        body=body,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return response


@router.delete(
    "/projects/{project_id}/doc-questions/answers/{answer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить подтверждённый ответ",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def remove_doc_answer(
    project_id: uuid.UUID, answer_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> Response:
    await _project(session, context, project_id)
    await doc_answers.delete_answer(session, project_id=project_id, answer_id=answer_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/doc-questions/candidates/{candidate_id}/reject",
    response_model=DocCandidateOut,
    summary="Отклонить кандидата; повторный поиск его не воскрешает",
    dependencies=[require(Permission.DOCUMENT_UPLOAD)],
)
async def reject_doc_candidate(
    project_id: uuid.UUID, candidate_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> DocCandidateOut:
    await _project(session, context, project_id)
    response = await doc_answers.reject_candidate(
        session,
        project_id=project_id,
        candidate_id=candidate_id,
        user_id=context.principal.user_id,
    )
    await session.commit()
    return response


@router.get(
    "/projects/{project_id}/doc-answers",
    response_model=DocAnswersOut,
    summary="Подтверждённые ответы проекта с происхождением: плоский список для CAD-трасс",
    dependencies=[require(Permission.DOCUMENT_READ)],
)
async def list_doc_answers(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> DocAnswersOut:
    await _project(session, context, project_id)
    return await doc_answers.list_answers(session, project_id=project_id)


# Отдельная группа под общим требованием опознания; флаг пространства - на самом `router`.
qa_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_authenticated)])
qa_router.include_router(router)
