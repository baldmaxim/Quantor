"""Калибровка масштаба чертежа.

Коэффициент «миллиметр на точку PDF», полученный от человека по известному размеру
(ADR-0018). Хранится вместе с доказательством: обеими точками, введённым значением и
геометрией страницы, на которой он посчитан.

Неизменяема. Исправить «6000» на «6200» в той же строке нельзя — создаётся новая
калибровка, старая остаётся. Причина не в аккуратности: величина, посчитанная вчера и
предъявленная заказчику, обязана воспроизводиться сегодня.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import LengthUnit, ScaleScopeKind, ScaleSource, VerificationState
from app.models.mixins import CreatedAtMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.sheet import Sheet


class ScaleCalibration(CreatedAtMixin, Base):
    """Масштаб листа: сколько миллиметров мира в одной точке PDF.

    Коэффициент привязан к точке PDF, а не к нормализованной координате. Точка PDF —
    физическая единица документа, одинаковая по обеим осям, поэтому одно число описывает
    и горизонталь, и вертикаль, и диагональ. Прежний `units_per_normalized` этого не мог:
    на прямоугольной странице 0,1 по X и 0,1 по Y — разные расстояния.
    """

    __tablename__ = "scale_calibrations"

    id: Mapped[uuid.UUID] = uuid_pk()
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("sheets.id", ondelete="CASCADE"), nullable=False
    )

    scope_kind: Mapped[ScaleScopeKind] = mapped_column(
        str_enum(ScaleScopeKind, name="scale_scope_kind"),
        nullable=False,
        default=ScaleScopeKind.SHEET,
        server_default=ScaleScopeKind.SHEET.value,
    )
    # Область действия локального масштаба. На Stage 2A всегда пусто: создаётся только
    # scope_kind=sheet. Колонка заведена сразу, чтобы узел 1:20 на листе 1:100 не требовал
    # миграции данных, когда до него дойдут руки.
    scope_polygon_norm: Mapped[list[list[float]] | None] = mapped_column(pg.JSONB)

    # --- доказательство ---
    #
    # Без этих полей калибровку невозможно проверить: остался бы коэффициент, про который
    # никто не помнит, откуда он взялся.

    point_a_x: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    point_a_y: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    point_b_x: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)
    point_b_y: Mapped[Decimal] = mapped_column(Numeric(9, 8), nullable=False)

    # Что именно набрал человек: 6000 и «мм» либо 6 и «м». Сохраняется в исходном виде —
    # приведённое к миллиметрам значение уже не расскажет, что было введено.
    input_value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    input_unit: Mapped[LengthUnit] = mapped_column(
        str_enum(LengthUnit, name="length_unit", length=8), nullable=False
    )

    known_distance_mm: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # Расстояние между точками в точках PDF. Считает сервер: коэффициент, присланный
    # клиентом, означал бы величину, изменяемую запросом.
    page_distance_pt: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    mm_per_pt: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)

    # Отпечаток геометрии, на которой посчитан коэффициент. Переизвлечение геометрии другой
    # версией парсера обязано быть заметным, а не молча менять смысл старой калибровки.
    page_geometry_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    source: Mapped[ScaleSource] = mapped_column(
        str_enum(ScaleSource, name="scale_source"), nullable=False, default=ScaleSource.MANUAL
    )
    verification_state: Mapped[VerificationState] = mapped_column(
        str_enum(VerificationState, name="verification_state"),
        nullable=False,
        default=VerificationState.UNVERIFIED,
        server_default=VerificationState.UNVERIFIED.value,
    )

    # Действующая калибровка листа: предлагается новым измерениям. Смена не трогает уже
    # посчитанное — измерение хранит явную ссылку на свою калибровку (ADR-0018).
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Какую калибровку эта заменяет. Ссылка, а не удаление: цепочка версий должна
    # оставаться читаемой.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("scale_calibrations.id", ondelete="SET NULL")
    )

    # Автор и проверяющий — без внешнего ключа намеренно, как и в журнале действий:
    # доказательство обязано пережить удаление личности, о которой рассказывает.
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    calibration_metadata: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    sheet: Mapped[Sheet] = relationship(back_populates="scale_calibrations")

    __table_args__ = (
        # Отрезок нулевой длины дал бы деление на ноль, а слишком короткий — коэффициент,
        # в котором ошибка клика превращается в ошибку всех объёмов листа.
        CheckConstraint("page_distance_pt > 0", name="page_distance_positive"),
        CheckConstraint("known_distance_mm > 0", name="known_distance_positive"),
        CheckConstraint("input_value > 0", name="input_value_positive"),
        CheckConstraint("mm_per_pt > 0", name="mm_per_pt_positive"),
        CheckConstraint(
            "point_a_x between 0 and 1 and point_a_y between 0 and 1"
            " and point_b_x between 0 and 1 and point_b_y between 0 and 1",
            name="points_normalized",
        ),
        CheckConstraint("length(page_geometry_fingerprint) = 64", name="fingerprint_length"),
        # Локальная область только у region-калибровки: полигон у листовой означал бы,
        # что область задана и не действует — состояние, которое нечем объяснить.
        CheckConstraint(
            "scope_kind = 'region' or scope_polygon_norm is null",
            name="scope_polygon_only_for_region",
        ),
        Index("ix_scale_calibrations_sheet_id_created_at", "sheet_id", "created_at"),
        # Действующая калибровка у листа ровно одна. Частичный уникальный индекс, а не
        # проверка в сервисе: два «основных» масштаба — это два разных ответа на вопрос,
        # сколько метров в стене.
        Index(
            "uq_scale_calibrations_default_per_sheet",
            "sheet_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )
