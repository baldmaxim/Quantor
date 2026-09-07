"""Общие части моделей: первичный ключ и отметки времени."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, func
from sqlalchemy import Enum as SaEnum
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    """Первичный ключ UUID.

    Версия 4, а не 7: в Python 3.12 нет uuid7 в стандартной библиотеке, а тянуть зависимость
    ради генерации идентификаторов на текущих объёмах незачем. Переход на 7 возможен без
    изменения схемы — тип колонки тот же.
    """
    return mapped_column(pg.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def str_enum[E: StrEnum](enum_cls: type[E], *, name: str, length: int = 32) -> SaEnum:
    """Перечисление как VARCHAR с CHECK.

    values_callable обязателен: без него SQLAlchemy пишет в базу имена членов (ACTIVE),
    а не значения (active), и данные расходятся с тем, что отдаёт API.

    Длина по умолчанию рассчитана на доменные состояния. Словари вроде действий аудита
    длиннее, поэтому её можно поднять — но не занижать: обрезанное значение не пройдёт CHECK
    и уронит вставку в самый неудобный момент.
    """
    return SaEnum(
        enum_cls,
        native_enum=False,
        length=length,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )


class TimestampMixin:
    """created_at/updated_at с часовым поясом: без него сравнение времени в проде врёт."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class CreatedAtMixin:
    """Только время создания — для неизменяемых записей."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
