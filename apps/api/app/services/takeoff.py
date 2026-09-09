"""Строки обмера и измерения (ADR-0019).

Здесь живут инварианты, которые база выразить не может: совпадение проекта строки и листа,
совпадение типов, запрет записи в архивную строку и подмены источника. База держит форму
данных, сервис — их согласованность между таблицами.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import (
    COORDINATES_PER_POINT,
    EXACT_POINTS_BY_GEOMETRY,
    MAX_MEASUREMENT_BATCH,
    MAX_MEASUREMENT_POINTS,
    MIN_POINTS_BY_GEOMETRY,
    UNIT_BY_GEOMETRY,
    GeometryType,
    MeasurementSource,
)
from app.errors import DomainError, ErrorCode
from app.models import (
    Document,
    DocumentRevision,
    Measurement,
    Project,
    ScaleCalibration,
    Sheet,
    TakeoffItem,
)

# Предел числа вершин. Не про производительность: многоугольник из ста тысяч точек —
# это отказ, а не тяжёлая фигура. Без предела он же становится способом положить сервер
# одним запросом.

# Цвет строки по умолчанию. Ключ палитры темы, а не значение: хардкод hex здесь
# разъехался бы с тёмной темой.
DEFAULT_COLOR_KEY = "accent"


def validate_points(geometry_type: GeometryType, points: list[list[float]]) -> list[list[float]]:
    """Проверяет форму геометрии и возвращает канонические точки.

    Точки остаются в том порядке, в каком их поставил человек. Многоугольник **не**
    замыкается повторением первой точки: замыкание — свойство типа, а не данных.
    """
    exact = EXACT_POINTS_BY_GEOMETRY.get(geometry_type)
    minimum = MIN_POINTS_BY_GEOMETRY[geometry_type]

    if exact is not None and len(points) != exact:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"Для «{geometry_type.value}» нужно ровно {exact} точек, передано {len(points)}",
        )
    if len(points) < minimum:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"Для «{geometry_type.value}» нужно минимум {minimum} точек, передано {len(points)}",
        )
    if len(points) > MAX_MEASUREMENT_POINTS:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"Слишком много вершин: {len(points)}, предел {MAX_MEASUREMENT_POINTS}",
        )

    canonical: list[list[float]] = []
    for index, point in enumerate(points):
        if len(point) != COORDINATES_PER_POINT:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED, f"Точка {index + 1}: ожидается пара координат"
            )
        x, y = float(point[0]), float(point[1])
        for name, value in (("x", x), ("y", y)):
            # NaN и бесконечность прошли бы JSON и легли бы в базу, превратив любую
            # величину по этой геометрии в бессмыслицу.
            if value != value or value in (float("inf"), float("-inf")):
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    f"Точка {index + 1}: {name} должно быть конечным числом",
                )
            if not 0.0 <= value <= 1.0:
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED,
                    f"Точка {index + 1}: {name}={value} вне листа",
                )
        canonical.append([x, y])

    return canonical


# --------------------------------------------------------------------------- строки


def _items_scoped(workspace_id: uuid.UUID) -> Select[tuple[TakeoffItem]]:
    return (
        select(TakeoffItem)
        .join(Project, TakeoffItem.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
    )


async def create_item(
    session: AsyncSession,
    *,
    project: Project,
    name: str,
    geometry_type: GeometryType,
    code: str | None = None,
    color_key: str | None = None,
    created_by: uuid.UUID | None = None,
) -> TakeoffItem:
    """Создаёт строку обмера.

    Единица показа выводится из типа, а не принимается снаружи: свободное поле однажды
    разошлось бы с типом и показало площадь в метрах.
    """
    cleaned = name.strip()
    if not cleaned:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Название строки не может быть пустым")

    ordinal = await session.scalar(
        select(func.coalesce(func.max(TakeoffItem.ordinal), -1) + 1).where(
            TakeoffItem.project_id == project.id
        )
    )

    item = TakeoffItem(
        project_id=project.id,
        name=cleaned,
        code=code,
        geometry_type=geometry_type,
        display_unit=UNIT_BY_GEOMETRY[geometry_type],
        color_key=color_key or DEFAULT_COLOR_KEY,
        ordinal=int(ordinal or 0),
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(item)
    await session.flush()
    await session.refresh(item)
    return item


async def get_item(
    session: AsyncSession, *, workspace_id: uuid.UUID, item_id: uuid.UUID
) -> TakeoffItem | None:
    result = await session.execute(_items_scoped(workspace_id).where(TakeoffItem.id == item_id))
    return result.scalar_one_or_none()


async def list_items(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    include_archived: bool = False,
) -> list[TakeoffItem]:
    query = _items_scoped(workspace_id).where(TakeoffItem.project_id == project_id)
    if not include_archived:
        query = query.where(TakeoffItem.archived_at.is_(None))
    result = await session.execute(query.order_by(TakeoffItem.ordinal, TakeoffItem.created_at))
    return list(result.scalars().all())


async def archive_item(
    session: AsyncSession, *, item: TakeoffItem, actor: uuid.UUID | None = None
) -> TakeoffItem:
    """Архивирует строку.

    Не удаление: строка, по которой посчитаны объёмы, — это документ, и удалить её значит
    потерять объяснение чисел, которые могли уйти заказчику.
    """
    item.archived_at = datetime.now(UTC)
    item.updated_by = actor
    await session.flush()
    return item


async def restore_item(
    session: AsyncSession, *, item: TakeoffItem, actor: uuid.UUID | None = None
) -> TakeoffItem:
    item.archived_at = None
    item.updated_by = actor
    await session.flush()
    return item


# ----------------------------------------------------------------------- измерения


def _measurements_scoped(workspace_id: uuid.UUID) -> Select[tuple[Measurement]]:
    """Путь владения от измерения вверх до рабочего пространства."""
    return (
        select(Measurement)
        .join(Sheet, Measurement.sheet_id == Sheet.id)
        .join(DocumentRevision, Sheet.revision_id == DocumentRevision.id)
        .join(Document, DocumentRevision.document_id == Document.id)
        .join(Project, Document.project_id == Project.id)
        .where(Project.workspace_id == workspace_id)
    )


async def _sheet_project_id(session: AsyncSession, *, sheet_id: uuid.UUID) -> uuid.UUID | None:
    query = (
        select(Project.id)
        .join(Document, Document.project_id == Project.id)
        .join(DocumentRevision, DocumentRevision.document_id == Document.id)
        .join(Sheet, Sheet.revision_id == DocumentRevision.id)
        .where(Sheet.id == sheet_id)
    )
    found = await session.scalar(query)
    return uuid.UUID(str(found)) if found is not None else None


async def create_measurement(
    session: AsyncSession,
    *,
    item: TakeoffItem,
    sheet: Sheet,
    points: list[list[float]],
    calibration: ScaleCalibration | None = None,
    created_by: uuid.UUID | None = None,
) -> Measurement:
    """Создаёт измерение.

    Источник всегда `manual`: параметра для него нет намеренно. Иначе результат ручного
    обмера можно было бы выдать за проверенный автоматикой — ровно та подмена, ради
    предотвращения которой AI на этапе и запрещён.
    """
    if item.archived_at is not None:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "Строка в архиве и новых измерений не принимает",
        )

    sheet_project = await _sheet_project_id(session, sheet_id=sheet.id)
    if sheet_project != item.project_id:
        # Строка и лист из разных проектов — это либо ошибка клиента, либо попытка
        # сложить чужие объёмы в свой итог.
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, "Строка обмера и лист принадлежат разным проектам"
        )

    if calibration is not None and calibration.sheet_id != sheet.id:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Калибровка относится к другому листу")

    canonical = validate_points(item.geometry_type, points)

    measurement = Measurement(
        takeoff_item_id=item.id,
        sheet_id=sheet.id,
        geometry_type=item.geometry_type,
        points=canonical,
        source=MeasurementSource.MANUAL,
        scale_calibration_id=calibration.id if calibration is not None else None,
        version=1,
        created_by=created_by,
        updated_by=created_by,
    )
    session.add(measurement)
    await session.flush()
    await session.refresh(measurement)
    return measurement


async def update_geometry(
    session: AsyncSession,
    *,
    measurement: Measurement,
    points: list[list[float]],
    expected_version: int,
    actor: uuid.UUID | None = None,
) -> Measurement:
    """Меняет геометрию с проверкой версии.

    Двое, тянущие одну вершину, должны получить понятный конфликт, а не молча затереть
    работу друг друга.
    """
    if measurement.deleted_at is not None:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Измерение удалено")

    if measurement.version != expected_version:
        raise DomainError(
            ErrorCode.MEASUREMENT_VERSION_CONFLICT,
            f"Измерение изменено другим пользователем: версия {measurement.version},"
            f" а ожидалась {expected_version}",
        )

    measurement.points = validate_points(measurement.geometry_type, points)
    measurement.version += 1
    measurement.updated_by = actor
    await session.flush()
    return measurement


async def soft_delete(
    session: AsyncSession, *, measurement: Measurement, actor: uuid.UUID | None = None
) -> Measurement:
    """Помечает измерение удалённым.

    Мягкое удаление: измерение — основание величины, и жёсткое удаление уносит возможность
    объяснить, почему вчера в отчёте было другое число.
    """
    if measurement.deleted_at is None:
        measurement.deleted_at = datetime.now(UTC)
        measurement.updated_by = actor
        await session.flush()
    return measurement


async def get_measurement(
    session: AsyncSession, *, workspace_id: uuid.UUID, measurement_id: uuid.UUID
) -> Measurement | None:
    result = await session.execute(
        _measurements_scoped(workspace_id).where(
            Measurement.id == measurement_id, Measurement.deleted_at.is_(None)
        )
    )
    return result.scalar_one_or_none()


async def list_for_sheet(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    sheet_id: uuid.UUID,
    item_id: uuid.UUID | None = None,
) -> list[Measurement]:
    """Активные измерения листа. Удалённые не возвращаются никогда."""
    query = _measurements_scoped(workspace_id).where(
        Measurement.sheet_id == sheet_id, Measurement.deleted_at.is_(None)
    )
    if item_id is not None:
        query = query.where(Measurement.takeoff_item_id == item_id)
    result = await session.execute(query.order_by(Measurement.created_at))
    return list(result.scalars().all())


async def count_for_item(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    item_id: uuid.UUID,
    revision_id: uuid.UUID | None = None,
    sheet_id: uuid.UUID | None = None,
) -> int:
    """Сколько активных измерений у строки в **явно указанной** области.

    Область обязательна не из педантизма: сложить измерения двух ревизий одного документа
    значило бы посчитать одни и те же двери дважды — вторая ревизия это тот же чертёж
    после правок, а не соседнее здание (ADR-0019).
    """
    if revision_id is None and sheet_id is None:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            "Итог по строке требует явной области: ревизия или лист",
        )

    query = (
        select(func.count())
        .select_from(Measurement)
        .join(Sheet, Measurement.sheet_id == Sheet.id)
        .join(DocumentRevision, Sheet.revision_id == DocumentRevision.id)
        .join(Document, DocumentRevision.document_id == Document.id)
        .join(Project, Document.project_id == Project.id)
        .where(
            Project.workspace_id == workspace_id,
            Measurement.takeoff_item_id == item_id,
            Measurement.deleted_at.is_(None),
        )
    )
    if sheet_id is not None:
        query = query.where(Measurement.sheet_id == sheet_id)
    if revision_id is not None:
        query = query.where(Sheet.revision_id == revision_id)

    return int(await session.scalar(query) or 0)


# Предел пакета. Счёт ставит метки десятками, но не тысячами за один запрос: пакет без
# предела — это способ положить сервер, а не удобство.


async def update_item(
    session: AsyncSession,
    *,
    item: TakeoffItem,
    name: str | None = None,
    code: str | None = None,
    color_key: str | None = None,
    ordinal: int | None = None,
    actor: uuid.UUID | None = None,
) -> TakeoffItem:
    """Меняет описательные поля строки.

    Тип геометрии не меняется никогда: сменить его у строки с измерениями значило бы
    объявить посчитанные точки площадями. Нужен другой тип — заводится другая строка.
    """
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise DomainError(ErrorCode.VALIDATION_FAILED, "Название строки не может быть пустым")
        item.name = cleaned
    if code is not None:
        item.code = code or None
    if color_key is not None:
        item.color_key = color_key
    if ordinal is not None:
        item.ordinal = ordinal

    item.updated_by = actor
    await session.flush()
    return item


async def create_measurements_batch(
    session: AsyncSession,
    *,
    item: TakeoffItem,
    sheet: Sheet,
    batch: list[list[list[float]]],
    calibration: ScaleCalibration | None = None,
    created_by: uuid.UUID | None = None,
) -> list[Measurement]:
    """Создаёт несколько измерений одной транзакцией.

    Пакет **атомарен**: одна негодная геометрия отменяет весь пакет. Частичный результат
    заставил бы клиента разбираться, какие из двадцати меток сохранились, — а он в этот
    момент уже нарисовал все двадцать.
    """
    if not batch:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Пустой пакет")
    if len(batch) > MAX_MEASUREMENT_BATCH:
        raise DomainError(
            ErrorCode.VALIDATION_FAILED,
            f"В пакете {len(batch)} измерений, предел {MAX_MEASUREMENT_BATCH}",
        )

    created: list[Measurement] = []
    for points in batch:
        created.append(
            await create_measurement(
                session,
                item=item,
                sheet=sheet,
                points=points,
                calibration=calibration,
                created_by=created_by,
            )
        )
    return created


def geometry_digest(points: list[list[float]]) -> str:
    """Короткий отпечаток геометрии для журнала.

    В журнал не кладётся массив из тысяч координат: он раздул бы записи и ничего бы не
    объяснил. Отпечатка и числа точек хватает, чтобы понять, менялась ли геометрия.
    """
    payload = ";".join(f"{x!r},{y!r}" for x, y in points)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
