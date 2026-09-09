"""Калибровка масштаба чертежа (ADR-0018).

Операций ровно столько, сколько нужно рабочему сценарию: посмотреть калибровки листа,
создать по известному размеру, назначить действующей, подтвердить. Удаления нет намеренно —
калибровка это доказательство, и измерения ссылаются на неё явно.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.v1.deps import SessionDep, WorkspaceDep, require
from app.auth.permissions import Permission
from app.domain import LengthUnit, VerificationState
from app.errors import not_found
from app.schemas import ScaleCalibrationCreate, ScaleCalibrationRead, ScaleVerificationWrite
from app.services import documents as documents_service
from app.services import scale as scale_service

router = APIRouter(tags=["scale"])


@router.get(
    "/sheets/{sheet_id}/scale-calibrations",
    response_model=list[ScaleCalibrationRead],
    summary="Калибровки масштаба листа",
    dependencies=[require(Permission.TAKEOFF_READ)],
)
async def list_sheet_calibrations(
    sheet_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> list[ScaleCalibrationRead]:
    """Все калибровки листа, новые сверху.

    Не страница: калибровок на листе единицы, а не сотни. Пагинация здесь была бы
    механикой без причины.
    """
    sheet = await documents_service.get_sheet(
        session, workspace_id=workspace.tenant, sheet_id=sheet_id
    )
    if sheet is None:
        raise not_found("Лист")

    rows = await scale_service.list_for_sheet(
        session, workspace_id=workspace.tenant, sheet_id=sheet.id
    )
    return [ScaleCalibrationRead.model_validate(row) for row in rows]


@router.post(
    "/sheets/{sheet_id}/scale-calibrations",
    response_model=ScaleCalibrationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Задать масштаб по известному размеру",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def create_sheet_calibration(
    sheet_id: uuid.UUID,
    payload: ScaleCalibrationCreate,
    session: SessionDep,
    workspace: WorkspaceDep,
) -> ScaleCalibrationRead:
    """Создаёт калибровку из двух точек и подписанного на чертеже размера.

    Коэффициент считает сервер. Клиент присылает точки и размер — не множитель.
    """
    sheet = await documents_service.get_sheet(
        session, workspace_id=workspace.tenant, sheet_id=sheet_id
    )
    if sheet is None:
        raise not_found("Лист")

    supersedes = None
    if payload.supersedes_id is not None:
        supersedes = await scale_service.get_calibration(
            session, workspace_id=workspace.tenant, calibration_id=payload.supersedes_id
        )
        if supersedes is None or supersedes.sheet_id != sheet.id:
            raise not_found("Калибровка")

    calibration = await scale_service.create_manual(
        session,
        sheet=sheet,
        point_a=(payload.point_a[0], payload.point_a[1]),
        point_b=(payload.point_b[0], payload.point_b[1]),
        input_value=payload.known_distance,
        input_unit=LengthUnit(payload.unit),
        created_by=workspace.principal.user_id,
        make_default=payload.make_default,
        supersedes=supersedes,
    )
    await session.commit()
    await session.refresh(calibration)
    return ScaleCalibrationRead.model_validate(calibration)


@router.get(
    "/scale-calibrations/{calibration_id}",
    response_model=ScaleCalibrationRead,
    summary="Калибровка",
    dependencies=[require(Permission.TAKEOFF_READ)],
)
async def read_calibration(
    calibration_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> ScaleCalibrationRead:
    calibration = await scale_service.get_calibration(
        session, workspace_id=workspace.tenant, calibration_id=calibration_id
    )
    if calibration is None:
        raise not_found("Калибровка")

    return ScaleCalibrationRead.model_validate(calibration)


@router.post(
    "/scale-calibrations/{calibration_id}/default",
    response_model=ScaleCalibrationRead,
    summary="Сделать масштаб действующим",
    dependencies=[require(Permission.TAKEOFF_EDIT)],
)
async def make_calibration_default(
    calibration_id: uuid.UUID, session: SessionDep, workspace: WorkspaceDep
) -> ScaleCalibrationRead:
    """Назначает калибровку действующей для листа.

    Уже посчитанные измерения не меняются: каждое хранит явную ссылку на свою калибровку.
    Перепривязка — отдельное действие, а не побочный эффект этого нажатия (ADR-0018).
    """
    calibration = await scale_service.get_calibration(
        session, workspace_id=workspace.tenant, calibration_id=calibration_id
    )
    if calibration is None:
        raise not_found("Калибровка")

    await scale_service.set_default(session, calibration=calibration)
    await session.commit()
    await session.refresh(calibration)
    return ScaleCalibrationRead.model_validate(calibration)


@router.post(
    "/scale-calibrations/{calibration_id}/verification",
    response_model=ScaleCalibrationRead,
    summary="Подтвердить масштаб",
    dependencies=[require(Permission.TAKEOFF_VERIFY)],
)
async def set_calibration_verification(
    calibration_id: uuid.UUID,
    payload: ScaleVerificationWrite,
    session: SessionDep,
    workspace: WorkspaceDep,
) -> ScaleCalibrationRead:
    """Подтверждает калибровку или снимает подтверждение.

    Отдельное право `takeoff.verify`: подтверждение — это ответственность за число перед
    заказчиком, и она не обязана совпадать с правом это число внести.
    """
    calibration = await scale_service.get_calibration(
        session, workspace_id=workspace.tenant, calibration_id=calibration_id
    )
    if calibration is None:
        raise not_found("Калибровка")

    await scale_service.set_verification(
        session,
        calibration=calibration,
        state=VerificationState(payload.state),
        actor=workspace.principal.user_id,
    )
    await session.commit()
    await session.refresh(calibration)
    return ScaleCalibrationRead.model_validate(calibration)
