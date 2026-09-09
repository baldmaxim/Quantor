"""Калибровка масштаба чертежа (ADR-0018).

Коэффициент считает **сервер** из двух нормализованных точек и канонической геометрии
страницы. Готовый коэффициент от клиента не принимается никогда: величину, которую можно
задать запросом, защитить перед заказчиком нечем.

```text
page_distance_pt = |to_pdf(A) − to_pdf(B)|
mm_per_pt        = known_distance_mm / page_distance_pt
```
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import LengthUnit, ScaleScopeKind, ScaleSource, VerificationState
from app.errors import DomainError, ErrorCode
from app.models import Document, DocumentRevision, PageGeometry, Project, ScaleCalibration, Sheet
from app.services.geometry.transform import (
    NormalizedPoint,
    PageGeometryValue,
    distance_pdf_points,
    normalized_to_pdf_display,
)

# Ниже этого порога калибровка бессмысленна: на отрезке в пять точек промах курсора
# на одну точку — это двадцать процентов ошибки, и она умножит все объёмы листа.
# Настоящие размерные линии на A1 занимают сотни точек, поэтому порог отсекает
# случайный двойной щелчок, а не рабочий сценарий.
MIN_PAGE_DISTANCE_PT: Final = Decimal("5")

# Разрядность хранения. Совпадает с колонками: округление здесь, а не по дороге.
_DISTANCE_QUANT: Final = Decimal("0.000001")
_FACTOR_QUANT: Final = Decimal("0.000000000001")
_MM_QUANT: Final = Decimal("0.0001")


def to_millimetres(value: Decimal, unit: LengthUnit) -> Decimal:
    """Приводит введённое значение к миллиметрам.

    Умножение на целое, а не на дробь: 6 м → 6000 мм точно, без потери разряда.
    """
    return (value * unit.to_mm).quantize(_MM_QUANT)


def geometry_value(geometry: PageGeometry) -> PageGeometryValue:
    """Граница «Decimal → float» для расчёта (ADR-0017)."""
    return PageGeometryValue.from_decimal(geometry.display_width_pt, geometry.display_height_pt)


def compute_factor(
    *,
    geometry: PageGeometry,
    point_a: tuple[Decimal, Decimal],
    point_b: tuple[Decimal, Decimal],
    known_distance_mm: Decimal,
) -> tuple[Decimal, Decimal]:
    """Считает расстояние в точках PDF и коэффициент «мм на точку».

    Возвращает `(page_distance_pt, mm_per_pt)`.
    """
    page = geometry_value(geometry)
    first = normalized_to_pdf_display(NormalizedPoint(float(point_a[0]), float(point_a[1])), page)
    second = normalized_to_pdf_display(NormalizedPoint(float(point_b[0]), float(point_b[1])), page)

    distance = Decimal(repr(distance_pdf_points(first, second))).quantize(_DISTANCE_QUANT)
    if distance < MIN_PAGE_DISTANCE_PT:
        raise DomainError(
            ErrorCode.SCALE_SEGMENT_TOO_SHORT,
            f"Отрезок {distance} pt короче допустимых {MIN_PAGE_DISTANCE_PT} pt:"
            " ошибка клика превратилась бы в ошибку всех объёмов листа",
        )

    factor = (known_distance_mm / distance).quantize(_FACTOR_QUANT)
    if factor <= 0:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, "Коэффициент масштаба должен быть больше нуля"
        )
    return distance, factor


async def find_sheet_geometry(session: AsyncSession, *, sheet_id: uuid.UUID) -> PageGeometry | None:
    """Геометрия листа или её отсутствие.

    Отдельно от `sheet_geometry`, потому что отсутствие геометрии — это разное для разных
    вызывающих: калибровать без неё нельзя и это отказ, а показать величину — можно,
    состоянием «недоступна».
    """
    found = await session.execute(select(PageGeometry).where(PageGeometry.sheet_id == sheet_id))
    return found.scalar_one_or_none()


async def sheet_geometry(session: AsyncSession, *, sheet_id: uuid.UUID) -> PageGeometry:
    """Каноническая геометрия листа. Без неё калибровать не от чего."""
    geometry = await find_sheet_geometry(session, sheet_id=sheet_id)
    if geometry is None:
        raise DomainError(
            ErrorCode.SCALE_GEOMETRY_REQUIRED,
            "Геометрия страницы ещё не извлечена: масштаб не к чему привязать",
        )
    return geometry


async def create_manual(
    session: AsyncSession,
    *,
    sheet: Sheet,
    point_a: tuple[Decimal, Decimal],
    point_b: tuple[Decimal, Decimal],
    input_value: Decimal,
    input_unit: LengthUnit,
    created_by: uuid.UUID | None,
    make_default: bool = True,
    supersedes: ScaleCalibration | None = None,
) -> ScaleCalibration:
    """Создаёт ручную калибровку.

    Источник всегда `manual`: подставить сюда `detected_dimension` через публичный путь
    нельзя, иначе ручную калибровку можно было бы выдать за автоматически подтверждённую.
    """
    geometry = await sheet_geometry(session, sheet_id=sheet.id)
    known_mm = to_millimetres(input_value, input_unit)
    distance, factor = compute_factor(
        geometry=geometry, point_a=point_a, point_b=point_b, known_distance_mm=known_mm
    )

    calibration = ScaleCalibration(
        sheet_id=sheet.id,
        scope_kind=ScaleScopeKind.SHEET,
        point_a_x=point_a[0],
        point_a_y=point_a[1],
        point_b_x=point_b[0],
        point_b_y=point_b[1],
        input_value=input_value,
        input_unit=input_unit,
        known_distance_mm=known_mm,
        page_distance_pt=distance,
        mm_per_pt=factor,
        page_geometry_fingerprint=geometry.geometry_fingerprint,
        source=ScaleSource.MANUAL,
        verification_state=VerificationState.UNVERIFIED,
        is_default=False,
        supersedes_id=supersedes.id if supersedes is not None else None,
        created_by=created_by,
    )
    session.add(calibration)
    await session.flush()

    if make_default:
        await set_default(session, calibration=calibration)

    await session.refresh(calibration)
    return calibration


async def set_default(session: AsyncSession, *, calibration: ScaleCalibration) -> ScaleCalibration:
    """Делает калибровку действующей для листа.

    Прежняя перестаёт быть действующей, но **не удаляется и не меняется**: измерения,
    посчитанные по ней, хранят на неё явную ссылку, и их значения остаются прежними.
    Перепривязка существующих измерений — отдельное действие, а не побочный эффект.

    Снятие флага у остальных идёт до установки своего: частичный уникальный индекс
    допускает ровно одну действующую калибровку на лист, и обратный порядок упёрся бы
    в него.
    """
    await session.execute(
        update(ScaleCalibration)
        .where(
            ScaleCalibration.sheet_id == calibration.sheet_id,
            ScaleCalibration.id != calibration.id,
            ScaleCalibration.is_default.is_(True),
        )
        .values(is_default=False)
    )
    await session.flush()

    calibration.is_default = True
    await session.flush()
    return calibration


async def set_verification(
    session: AsyncSession,
    *,
    calibration: ScaleCalibration,
    state: VerificationState,
    actor: uuid.UUID | None,
) -> ScaleCalibration:
    """Подтверждает калибровку или снимает подтверждение.

    Единственное изменяемое в калибровке — состояние проверки. Сам коэффициент и его
    доказательство неизменяемы: исправление создаёт новую калибровку (ADR-0018).
    """
    calibration.verification_state = state
    if state is VerificationState.UNVERIFIED:
        calibration.verified_by = None
        calibration.verified_at = None
    else:
        calibration.verified_by = actor
        calibration.verified_at = datetime.now(UTC)
    await session.flush()
    return calibration


def _scoped(workspace_id: uuid.UUID) -> Select[tuple[ScaleCalibration]]:
    """Путь владения от калибровки вверх до рабочего пространства."""
    return (
        select(ScaleCalibration)
        .join(Sheet, ScaleCalibration.sheet_id == Sheet.id)
        .join(DocumentRevision, Sheet.revision_id == DocumentRevision.id)
        .join(Document, DocumentRevision.document_id == Document.id)
        .join(Project, Document.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
    )


async def list_for_sheet(
    session: AsyncSession, *, workspace_id: uuid.UUID, sheet_id: uuid.UUID
) -> list[ScaleCalibration]:
    """Все калибровки листа, новые сверху.

    Их может быть несколько: план 1:100 и узел 1:20 на одном листе — обычное дело.
    """
    query = (
        _scoped(workspace_id)
        .where(ScaleCalibration.sheet_id == sheet_id)
        .order_by(ScaleCalibration.created_at.desc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_calibration(
    session: AsyncSession, *, workspace_id: uuid.UUID, calibration_id: uuid.UUID
) -> ScaleCalibration | None:
    """Калибровка внутри своего пространства. Чужая не находится, а не запрещается."""
    result = await session.execute(
        _scoped(workspace_id).where(ScaleCalibration.id == calibration_id)
    )
    return result.scalar_one_or_none()


async def get_default(
    session: AsyncSession, *, workspace_id: uuid.UUID, sheet_id: uuid.UUID
) -> ScaleCalibration | None:
    """Действующая калибровка листа: та, что предлагается новым измерениям."""
    query = _scoped(workspace_id).where(
        ScaleCalibration.sheet_id == sheet_id, ScaleCalibration.is_default.is_(True)
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()
