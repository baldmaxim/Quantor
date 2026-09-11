"""API ручного обмера (ADR-0019).

Набор компактный намеренно: не эндпоинт на поле, а операция на действие пользователя.
Списки читаются по листу — просмотрщик открывает один лист, а не документ на 77 страниц.

В журнал пишется завершённое действие, а не движение указателя, и не массив координат:
отпечатка и числа точек хватает, чтобы понять, менялась ли геометрия, а тысяча пар чисел
раздула бы журнал и ничего бы не объяснила.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1.deps import AuthDep, SessionDep, WorkspaceDep, require, require_feature
from app.auth.permissions import Permission
from app.domain import AuditAction
from app.errors import not_found
from app.models import ScaleCalibration, Sheet, TakeoffItem
from app.schemas import (
    MeasurementBatchCreate,
    MeasurementCreate,
    MeasurementQuantityRead,
    MeasurementRead,
    MeasurementUpdate,
    SheetQuantitiesRead,
    TakeoffItemCreate,
    TakeoffItemQuantityRead,
    TakeoffItemRead,
    TakeoffItemUpdate,
)
from app.services import audit as audit_service
from app.services import documents as documents_service
from app.services import projects as projects_service
from app.services import scale as scale_service
from app.services import takeoff as takeoff_service

# Весь ручной обмер закрыт пилотным флагом: выключен для пространства — возможности нет и в
# API, а не только на экране (ADR-0023).
router = APIRouter(tags=["takeoff"], dependencies=[require_feature("takeoff.manual")])


# ---------------------------------------------------------------------- строки обмера


@router.get(
    "/projects/{project_id}/takeoff-items",
    response_model=list[TakeoffItemRead],
    summary="Строки обмера проекта",
    dependencies=[require(Permission.TAKEOFF_READ)],
)
async def list_takeoff_items(
    project_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    include_archived: Annotated[bool, Query(description="Показать архивные строки")] = False,
) -> list[TakeoffItemRead]:
    """Список строк проекта. Не страница: строк у проекта десятки, а не тысячи."""
    project = await projects_service.get_project(
        session, workspace_id=workspace.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")

    rows = await takeoff_service.list_items(
        session,
        workspace_id=workspace.tenant,
        project_id=project.id,
        include_archived=include_archived,
    )
    return [TakeoffItemRead.model_validate(row) for row in rows]


@router.post(
    "/projects/{project_id}/takeoff-items",
    response_model=TakeoffItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать строку обмера",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def create_takeoff_item(
    project_id: uuid.UUID,
    payload: TakeoffItemCreate,
    session: SessionDep,
    context: AuthDep,
) -> TakeoffItemRead:
    project = await projects_service.get_project(
        session, workspace_id=context.tenant, project_id=project_id
    )
    if project is None:
        raise not_found("Проект")

    item = await takeoff_service.create_item(
        session,
        project=project,
        name=payload.name,
        geometry_type=payload.geometry_type,
        code=payload.code,
        color_key=payload.color_key,
        created_by=context.principal.user_id,
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.TAKEOFF_ITEM_CREATED,
        resource_type="takeoff_item",
        resource_id=str(item.id),
        after={"name": item.name, "geometry_type": item.geometry_type.value},
    )
    await session.commit()
    await session.refresh(item)
    return TakeoffItemRead.model_validate(item)


@router.patch(
    "/takeoff-items/{item_id}",
    response_model=TakeoffItemRead,
    summary="Изменить строку обмера",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def update_takeoff_item(
    item_id: uuid.UUID,
    payload: TakeoffItemUpdate,
    session: SessionDep,
    context: AuthDep,
) -> TakeoffItemRead:
    """Меняет описание строки.

    Типа геометрии в запросе нет: сменить его у строки с измерениями значило бы объявить
    посчитанные точки площадями.
    """
    item = await takeoff_service.get_item(session, workspace_id=context.tenant, item_id=item_id)
    if item is None:
        raise not_found("Строка обмера")

    before = {"name": item.name, "code": item.code, "ordinal": item.ordinal}
    await takeoff_service.update_item(
        session,
        item=item,
        name=payload.name,
        code=payload.code,
        color_key=payload.color_key,
        ordinal=payload.ordinal,
        actor=context.principal.user_id,
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.TAKEOFF_ITEM_UPDATED,
        resource_type="takeoff_item",
        resource_id=str(item.id),
        before=before,
        after={"name": item.name, "code": item.code, "ordinal": item.ordinal},
    )
    await session.commit()
    await session.refresh(item)
    return TakeoffItemRead.model_validate(item)


@router.post(
    "/takeoff-items/{item_id}/archive",
    response_model=TakeoffItemRead,
    summary="Архивировать строку обмера",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def archive_takeoff_item(
    item_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> TakeoffItemRead:
    """Архивирует строку.

    Удаления нет: строка, по которой посчитаны объёмы, — это документ, и удалить её значит
    потерять объяснение чисел, которые могли уйти заказчику.
    """
    item = await takeoff_service.get_item(session, workspace_id=context.tenant, item_id=item_id)
    if item is None:
        raise not_found("Строка обмера")

    await takeoff_service.archive_item(session, item=item, actor=context.principal.user_id)
    await audit_service.record(
        session,
        context,
        action=AuditAction.TAKEOFF_ITEM_ARCHIVED,
        resource_type="takeoff_item",
        resource_id=str(item.id),
        after={"name": item.name},
    )
    await session.commit()
    await session.refresh(item)
    return TakeoffItemRead.model_validate(item)


# ------------------------------------------------------------------------- измерения


async def _sheet_or_404(session: SessionDep, workspace: WorkspaceDep, sheet_id: uuid.UUID) -> Sheet:
    sheet = await documents_service.get_sheet(
        session, workspace_id=workspace.tenant, sheet_id=sheet_id
    )
    if sheet is None:
        raise not_found("Лист")
    return sheet


@router.get(
    "/sheets/{sheet_id}/measurements",
    response_model=list[MeasurementRead],
    summary="Измерения листа",
    dependencies=[require(Permission.TAKEOFF_READ)],
)
async def list_sheet_measurements(
    sheet_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
    takeoff_item_id: Annotated[uuid.UUID | None, Query(description="Фильтр по строке")] = None,
) -> list[MeasurementRead]:
    """Активные измерения одного листа.

    Именно листа, а не документа: просмотрщик показывает открытую страницу, и тянуть
    измерения всех 77 листов ради одного — это тот же N+1, только наоборот.
    """
    sheet = await _sheet_or_404(session, workspace, sheet_id)
    rows = await takeoff_service.list_for_sheet(
        session,
        workspace_id=workspace.tenant,
        sheet_id=sheet.id,
        item_id=takeoff_item_id,
    )
    return [MeasurementRead.model_validate(row) for row in rows]


async def _resolve_item_and_calibration(
    session: SessionDep,
    context: AuthDep,
    sheet_id: uuid.UUID,
    item_id: uuid.UUID,
    calibration_id: uuid.UUID | None,
) -> tuple[TakeoffItem, ScaleCalibration | None]:
    """Достаёт строку и калибровку, уже ограниченные рабочим пространством.

    Чужие идентификаторы не находятся, а не запрещаются: 403 подтвердил бы существование
    объекта и превратил перебор в разведку.
    """
    item = await takeoff_service.get_item(session, workspace_id=context.tenant, item_id=item_id)
    if item is None:
        raise not_found("Строка обмера")

    calibration = None
    if calibration_id is not None:
        calibration = await scale_service.get_calibration(
            session, workspace_id=context.tenant, calibration_id=calibration_id
        )
        if calibration is None:
            raise not_found("Калибровка")
    else:
        # Действующая калибровка листа — умолчание, а не обязательство: у счёта её может
        # не быть вовсе, и это не ошибка.
        calibration = await scale_service.get_default(
            session, workspace_id=context.tenant, sheet_id=sheet_id
        )

    return item, calibration


@router.post(
    "/sheets/{sheet_id}/measurements",
    response_model=MeasurementRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать измерение",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def create_measurement(
    sheet_id: uuid.UUID,
    payload: MeasurementCreate,
    session: SessionDep,
    context: AuthDep,
) -> MeasurementRead:
    sheet = await _sheet_or_404(session, context, sheet_id)
    item, calibration = await _resolve_item_and_calibration(
        session, context, sheet.id, payload.takeoff_item_id, payload.scale_calibration_id
    )

    measurement = await takeoff_service.create_measurement(
        session,
        item=item,
        sheet=sheet,
        points=payload.points,
        calibration=calibration,
        created_by=context.principal.user_id,
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.MEASUREMENT_CREATED,
        resource_type="measurement",
        resource_id=str(measurement.id),
        after={
            "takeoff_item_id": str(item.id),
            "sheet_id": str(sheet.id),
            "geometry_type": measurement.geometry_type.value,
            "point_count": len(measurement.points),
            "geometry_digest": takeoff_service.geometry_digest(measurement.points),
        },
    )
    await session.commit()
    await session.refresh(measurement)
    return MeasurementRead.model_validate(measurement)


@router.post(
    "/sheets/{sheet_id}/measurements/batch",
    response_model=list[MeasurementRead],
    status_code=status.HTTP_201_CREATED,
    summary="Создать несколько измерений",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def create_measurements_batch(
    sheet_id: uuid.UUID,
    payload: MeasurementBatchCreate,
    session: SessionDep,
    context: AuthDep,
) -> list[MeasurementRead]:
    """Пакетная постановка. Нужна счёту: метки ставят подряд, а не по одной с ожиданием.

    Пакет атомарен: одна негодная геометрия отменяет весь. Частичный результат заставил бы
    клиента выяснять, какие из двадцати меток сохранились, — а он их уже нарисовал.
    """
    sheet = await _sheet_or_404(session, context, sheet_id)
    item, calibration = await _resolve_item_and_calibration(
        session, context, sheet.id, payload.takeoff_item_id, payload.scale_calibration_id
    )

    created = await takeoff_service.create_measurements_batch(
        session,
        item=item,
        sheet=sheet,
        batch=payload.items,
        calibration=calibration,
        created_by=context.principal.user_id,
    )
    # Сводка, а не список из двухсот идентификаторов: журнал должен объяснять, а не хранить.
    await audit_service.record(
        session,
        context,
        action=AuditAction.MEASUREMENT_BATCH_CREATED,
        resource_type="measurement",
        resource_id=str(item.id),
        after={
            "sheet_id": str(sheet.id),
            "created": len(created),
            "geometry_type": item.geometry_type.value,
        },
    )
    await session.commit()
    return [MeasurementRead.model_validate(row) for row in created]


@router.patch(
    "/measurements/{measurement_id}",
    response_model=MeasurementRead,
    summary="Изменить геометрию измерения",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def update_measurement(
    measurement_id: uuid.UUID,
    payload: MeasurementUpdate,
    session: SessionDep,
    context: AuthDep,
) -> MeasurementRead:
    """Правит геометрию с проверкой версии.

    Версия обязательна: без неё клиент, открывший лист десять минут назад, молча перетёр бы
    чужую правку. Расхождение — 409 с понятным кодом, а не тихая перезапись.
    """
    measurement = await takeoff_service.get_measurement(
        session, workspace_id=context.tenant, measurement_id=measurement_id
    )
    if measurement is None:
        raise not_found("Измерение")

    before = {
        "version": measurement.version,
        "point_count": len(measurement.points),
        "geometry_digest": takeoff_service.geometry_digest(measurement.points),
    }
    await takeoff_service.update_geometry(
        session,
        measurement=measurement,
        points=payload.points,
        expected_version=payload.version,
        actor=context.principal.user_id,
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.MEASUREMENT_UPDATED,
        resource_type="measurement",
        resource_id=str(measurement.id),
        before=before,
        after={
            "version": measurement.version,
            "point_count": len(measurement.points),
            "geometry_digest": takeoff_service.geometry_digest(measurement.points),
        },
    )
    await session.commit()
    await session.refresh(measurement)
    return MeasurementRead.model_validate(measurement)


@router.delete(
    "/measurements/{measurement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить измерение",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def delete_measurement(
    measurement_id: uuid.UUID, session: SessionDep, context: AuthDep
) -> None:
    """Мягкое удаление: запись остаётся объяснением вчерашнего числа."""
    measurement = await takeoff_service.get_measurement(
        session, workspace_id=context.tenant, measurement_id=measurement_id
    )
    if measurement is None:
        raise not_found("Измерение")

    await takeoff_service.soft_delete(
        session, measurement=measurement, actor=context.principal.user_id
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.MEASUREMENT_DELETED,
        resource_type="measurement",
        resource_id=str(measurement.id),
        before={"takeoff_item_id": str(measurement.takeoff_item_id)},
    )
    await session.commit()


# ------------------------------------------------------------------------- величины


@router.get(
    "/sheets/{sheet_id}/quantities",
    response_model=SheetQuantitiesRead,
    summary="Величины листа",
    dependencies=[require(Permission.TAKEOFF_READ)],
)
async def read_sheet_quantities(
    sheet_id: uuid.UUID,
    session: SessionDep,
    workspace: WorkspaceDep,
) -> SheetQuantitiesRead:
    """Величины всех измерений открытого листа и итоги по строкам обмера.

    Один запрос на лист, а не на измерение: просмотрщик показывает страницу целиком, и
    сотня обращений ради сотни меток была бы тем же N+1, только со стороны клиента.

    Область — лист и его ревизия, и это указано в ответе. Итог по документу складывал бы
    измерения разных ревизий и посчитал бы одни и те же двери дважды (ADR-0019).

    Величина без масштаба возвращается состоянием `unavailable_no_scale`, а не нулём: ноль
    — это утверждение о величине, и ложное.
    """
    sheet = await _sheet_or_404(session, workspace, sheet_id)
    computed = await takeoff_service.quantities_for_sheet(
        session, workspace_id=workspace.tenant, sheet=sheet
    )

    return SheetQuantitiesRead(
        sheet_id=computed.sheet_id,
        revision_id=computed.revision_id,
        page_geometry_fingerprint=computed.page_geometry_fingerprint,
        measurements=[
            MeasurementQuantityRead.model_validate(result, from_attributes=True)
            for result in computed.results
        ],
        totals=[
            TakeoffItemQuantityRead.model_validate(total, from_attributes=True)
            for total in computed.totals
        ],
    )
