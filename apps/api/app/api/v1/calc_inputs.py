"""API сбора исходных данных стадии П (ADR-0030, PROMPT 02).

Сбор фактов из распознанного пакета, записи о сборе, каталог требований ВК, матрица
готовности и таблица фактов экрана «Исходные данные». Закрыто тем же флагом `calc.portal`,
пути — под `/calc/`, без маркеров обмера и `/mep/`.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.calc import project_in_scope
from app.api.v1.deps import AuthDep, SessionDep, require, require_feature
from app.auth.permissions import Permission
from app.contracts.calc.enums import (
    CalcDiscipline,
    CalcReadinessStatus,
    CalcRequirementLevel,
)
from app.contracts.calc.fact_types import fact_type_def
from app.contracts.calc.inspections import (
    CalcCollectableDocumentRead,
    CalcInspectionCreate,
    CalcInspectionRead,
    CalcInspectionSummary,
)
from app.contracts.calc.readiness import CalcInputFactPage, CalcReadinessRead
from app.contracts.calc.requirements import (
    CalcRequirementCatalogRead,
    CalcRequirementRead,
    CalcSystemRead,
)
from app.contracts.calc.subjects import normalize_system_code
from app.domain import AuditAction
from app.services import audit as audit_service
from app.services.calc import input_facts, inspections, readiness
from app.services.calc.systems.vk.requirements import (
    VK_REQUIREMENTS,
    VK_REQUIREMENTS_VERSION,
    VK_SYSTEMS,
    requirements_for,
)

router = APIRouter(prefix="/calc", tags=["calc"], dependencies=[require_feature("calc.portal")])


@router.get(
    "/requirements",
    response_model=CalcRequirementCatalogRead,
    summary="Каталог исходных данных ВК стадии П",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_requirements() -> CalcRequirementCatalogRead:
    """Что понадобится калькулятору В1, Т3, Т4, К1: уровень, область, можно ли вывести."""
    return CalcRequirementCatalogRead(
        version=VK_REQUIREMENTS_VERSION,
        discipline=CalcDiscipline.VK,
        systems=[
            CalcSystemRead(discipline=system.discipline, code=system.code, title=system.title)
            for system in VK_SYSTEMS
        ],
        requirements=[
            CalcRequirementRead(
                id=item.id,
                title=item.title,
                group=item.group,
                fact_type=item.fact_type,
                fact_type_title=(
                    definition.title
                    if (definition := fact_type_def(item.fact_type))
                    else item.fact_type
                ),
                scope=item.scope,
                level=item.level,
                assumption=item.assumption,
                description=item.description,
                systems=list(item.systems),
                derivable_from=list(item.derivable_from),
                expected_sources=list(item.expected_sources),
            )
            for item in VK_REQUIREMENTS
        ],
    )


@router.get(
    "/projects/{project_id}/documents",
    response_model=list[CalcCollectableDocumentRead],
    summary="Документы проекта для сбора фактов",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_documents(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcCollectableDocumentRead]:
    """Ревизии с распознанным текстом и без, подсказка по штампу, последний сбор."""
    project = await project_in_scope(session, context, project_id)
    return await inspections.list_collectable_documents(session, project=project)


@router.post(
    "/projects/{project_id}/inspections",
    response_model=CalcInspectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Собрать факты из распознанного документа",
    dependencies=[require(Permission.CALC_EDIT)],
)
async def create_calc_inspection(
    project_id: uuid.UUID, payload: CalcInspectionCreate, session: SessionDep, context: AuthDep
) -> CalcInspectionRead:
    """Адаптеры читают готовый текст блоков; распознавание не повторяется и не меняется."""
    project = await project_in_scope(session, context, project_id)
    inspection = await inspections.run_inspection(
        session, project=project, payload=payload, user_id=context.principal.user_id
    )
    summary = CalcInspectionSummary.model_validate(inspection.summary)
    await audit_service.record(
        session,
        context,
        action=AuditAction.CALC_INSPECTION_COMPLETED,
        resource_type="calc_inspection",
        resource_id=str(inspection.id),
        after={
            "document_revision_id": str(inspection.document_revision_id),
            "source_class": inspection.source_class.value,
            "document_stage": inspection.document_stage.value,
            "accepted": summary.accepted,
            "created": summary.created,
            "withdrawn": summary.withdrawn,
        },
    )
    await session.commit()
    return CalcInspectionRead.model_validate(inspection)


@router.get(
    "/projects/{project_id}/inspections",
    response_model=list[CalcInspectionRead],
    summary="Сборы фактов проекта",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_inspections(
    project_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> list[CalcInspectionRead]:
    project = await project_in_scope(session, context, project_id)
    rows = await inspections.list_inspections(session, project_id=project.id)
    return [CalcInspectionRead.model_validate(row) for row in rows]


@router.get(
    "/projects/{project_id}/readiness",
    response_model=CalcReadinessRead,
    summary="Готовность исходных данных к расчёту",
    dependencies=[require(Permission.CALC_READ)],
)
async def read_calc_readiness(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    system: Annotated[str | None, Query(max_length=8, description="Система: «В1»")] = None,
    levels: Annotated[
        list[CalcRequirementLevel] | None, Query(alias="level", description="Уровни")
    ] = None,
    statuses: Annotated[
        list[CalcReadinessStatus] | None, Query(alias="status", description="Состояния")
    ] = None,
) -> CalcReadinessRead:
    """Что известно для расчёта и чего не хватает; фильтры сужают строки, но не счётчики."""
    project = await project_in_scope(session, context, project_id)
    result = await readiness.load_readiness(
        session,
        project=project,
        version=VK_REQUIREMENTS_VERSION,
        systems=VK_SYSTEMS,
        requirements_for=requirements_for,
    )
    code = normalize_system_code(system) if system else None
    systems = [item for item in result.systems if code is None or item.system_code == code]
    for item in systems:
        item.rows = [
            row
            for row in item.rows
            if (not levels or row.level in levels) and (not statuses or row.status in statuses)
        ]
    return result.model_copy(update={"systems": systems})


@router.get(
    "/projects/{project_id}/input-facts",
    response_model=CalcInputFactPage,
    summary="Факты проекта для экрана «Исходные данные»",
    dependencies=[require(Permission.CALC_READ)],
)
async def list_calc_input_facts(
    project_id: uuid.UUID,
    session: SessionDep,
    context: AuthDep,
    fact_type: Annotated[str | None, Query(max_length=64, description="Тип факта")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CalcInputFactPage:
    """Действующие утверждения и ответ сервера, идёт ли каждое в расчёт."""
    project = await project_in_scope(session, context, project_id)
    return await input_facts.list_input_facts(
        session, project=project, fact_type=fact_type, limit=limit, offset=offset
    )
