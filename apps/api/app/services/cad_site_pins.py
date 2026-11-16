"""Ручная привязка корпуса к площадке (ADR-0052): запись, отзыв, чтение действующих.

Привязка неизменяема, кроме отзыва; новая привязка того же листа-источника отзывает прежнюю в той же
транзакции. Математика - `cad_site_pins_math`, применение - `cad_building3d.place_site_report`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_site_pins import CadSitePinCreate
from app.errors import DomainError, ErrorCode, not_found
from app.models import CadSitePin, Project, UserIdentity
from app.services import cad as cad_service
from app.services import cad_site_pins_math as pins_math

REPLACED_REASON = "заменён"


def _sheet(revision_id: uuid.UUID, page_index: int, view: int) -> pins_math.SheetKey:
    return revision_id, page_index, view


async def list_active(session: AsyncSession, *, project_id: uuid.UUID) -> list[CadSitePin]:
    return list(
        await session.scalars(
            select(CadSitePin)
            .where(CadSitePin.project_id == project_id, CadSitePin.revoked_at.is_(None))
            .order_by(CadSitePin.created_at, CadSitePin.id)
        )
    )


async def active_site_pins(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[pins_math.SitePin]:
    """Действующие привязки проекта для посадки зданий."""
    return [
        pins_math.SitePin(
            id=row.id,
            source=_sheet(row.source_revision_id, row.source_page_index, row.source_view),
            target=_sheet(row.target_revision_id, row.target_page_index, row.target_view),
            rotation_deg=row.rotation_deg,
            offset_mm=(row.offset_x_mm, row.offset_y_mm),
            baseline_mm=row.baseline_mm,
            residual_mm=row.residual_mm,
            created_at=row.created_at,
        )
        for row in await list_active(session, project_id=project_id)
    ]


async def author_name(session: AsyncSession, pin: CadSitePin) -> str | None:
    row = (
        await session.execute(
            select(UserIdentity.display_name, UserIdentity.email).where(
                UserIdentity.id == pin.created_by
            )
        )
    ).first()
    return None if row is None else (row[0] or row[1])


async def create_pin(
    session: AsyncSession,
    *,
    project: Project,
    body: CadSitePinCreate,
    user_id: uuid.UUID,
) -> CadSitePin:
    """Новая привязка; действующая привязка того же листа-источника отзывается («заменён»)."""
    source, target = body.source, body.target
    if _sheet(source.revision_id, source.page_index, source.view) == _sheet(
        target.revision_id, target.page_index, target.view
    ):
        raise DomainError(
            ErrorCode.CAD_SITE_PIN_INVALID,
            "Источник и цель - один и тот же лист: привяжите корпус к листу другого здания.",
        )
    for revision_id in {source.revision_id, target.revision_id}:
        if (
            await cad_service.revision_in_project(session, project=project, revision_id=revision_id)
            is None
        ):
            raise not_found("Ревизия")
    p1, p2 = body.source_points
    q1, q2 = body.target_points
    try:
        solved = pins_math.solve_pin(
            ((p1.x_mm, p1.y_mm), (p2.x_mm, p2.y_mm)), ((q1.x_mm, q1.y_mm), (q2.x_mm, q2.y_mm))
        )
    except pins_math.SitePinError as error:
        raise DomainError(ErrorCode.CAD_SITE_PIN_INVALID, str(error)) from error
    previous = await session.scalars(
        select(CadSitePin)
        .where(
            CadSitePin.project_id == project.id,
            CadSitePin.revoked_at.is_(None),
            CadSitePin.source_revision_id == source.revision_id,
            CadSitePin.source_page_index == source.page_index,
            CadSitePin.source_view == source.view,
        )
        .with_for_update()
    )
    for old in previous:
        old.revoked_at = func.now()
        old.revoked_by = user_id
        old.revoke_reason = REPLACED_REASON
    await session.flush()
    pin = CadSitePin(
        workspace_id=project.workspace_id,
        project_id=project.id,
        source_revision_id=source.revision_id,
        source_page_index=source.page_index,
        source_view=source.view,
        target_revision_id=target.revision_id,
        target_page_index=target.page_index,
        target_view=target.view,
        source_x1_mm=p1.x_mm,
        source_y1_mm=p1.y_mm,
        source_x2_mm=p2.x_mm,
        source_y2_mm=p2.y_mm,
        target_x1_mm=q1.x_mm,
        target_y1_mm=q1.y_mm,
        target_x2_mm=q2.x_mm,
        target_y2_mm=q2.y_mm,
        rotation_deg=solved.rotation_deg,
        offset_x_mm=solved.offset_mm[0],
        offset_y_mm=solved.offset_mm[1],
        baseline_mm=solved.baseline_mm,
        residual_mm=solved.residual_mm,
        note=body.note,
        created_by=user_id,
    )
    session.add(pin)
    try:
        await session.flush()
    except IntegrityError as error:
        raise DomainError(
            ErrorCode.CAD_SITE_PIN_INVALID,
            "Привязка этого листа изменилась одновременно: повторите запрос.",
        ) from error
    await session.refresh(pin)
    return pin


async def pin_in_project(
    session: AsyncSession, *, project_id: uuid.UUID, pin_id: uuid.UUID
) -> CadSitePin:
    pin = await session.scalar(
        select(CadSitePin)
        .where(CadSitePin.id == pin_id, CadSitePin.project_id == project_id)
        .with_for_update()
    )
    if pin is None:
        raise not_found("Привязка")
    return pin


async def revoke_pin(
    session: AsyncSession, *, pin: CadSitePin, reason: str | None, user_id: uuid.UUID
) -> CadSitePin:
    """Отзыв ставится один раз; повторный - 409 (`CAD_ALREADY_REVOKED`)."""
    if pin.revoked_at is not None:
        raise DomainError(ErrorCode.CAD_ALREADY_REVOKED)
    pin.revoked_at = func.now()
    pin.revoked_by = user_id
    pin.revoke_reason = reason
    await session.flush()
    await session.refresh(pin)
    return pin
