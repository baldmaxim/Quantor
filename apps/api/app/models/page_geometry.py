"""Каноническая геометрия страницы PDF.

Единственный серверный источник размера страницы для расчёта физических величин (ADR-0016).
Растровые `Sheet.width_px`/`height_px` в этом расчёте не участвуют никогда: это пиксели
распознавалки, снятые с непостоянной плотностью.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import COORDINATE_SPACE_PDF_DISPLAY_POINTS_TOP_LEFT
from app.models.mixins import CreatedAtMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.sheet import Sheet


class PageGeometry(CreatedAtMixin, Base):
    """Отображаемая геометрия одной страницы, один к одному с листом.

    Строка есть — геометрия известна целиком. Строки нет — она неизвестна. Состояния
    «половина геометрии» не существует, и ради этого таблица отдельная: набор nullable-колонок
    в `sheets` такое состояние допускал бы.
    """

    __tablename__ = "page_geometries"

    id: Mapped[uuid.UUID] = uuid_pk()
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("sheets.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Пространство названо явно и хранится в строке: если оно когда-нибудь изменится,
    # старые записи останутся читаемыми, а не станут молча значить другое.
    coordinate_space: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=COORDINATE_SPACE_PDF_DISPLAY_POINTS_TOP_LEFT,
        server_default=COORDINATE_SPACE_PDF_DISPLAY_POINTS_TOP_LEFT,
    )

    # Отображаемый размер: поворот страницы уже учтён. Numeric, а не float, ради
    # воспроизводимости отпечатка: у десятичного значения каноническая запись одна и та же
    # в PostgreSQL, Python и TypeScript. 0,0001 pt — 35 нанометров чертежа.
    display_width_pt: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    display_height_pt: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)

    # `/Rotate` исходной страницы. Хранится как происхождение и для сверки с отрисовщиком;
    # к нормализованным координатам повторно НЕ применяется (ADR-0008).
    pdf_rotation: Mapped[int] = mapped_column(Integer, nullable=False)

    # Рамки в исходном пространстве PDF: начало внизу слева, поворот не применён.
    # Диагностика и происхождение, а не короткий путь к измерению — отображаемая страница
    # это crop_box, пересечённый с media_box и повёрнутый.
    media_box: Mapped[list[float]] = mapped_column(pg.JSONB, nullable=False)
    crop_box: Mapped[list[float]] = mapped_column(pg.JSONB, nullable=False)

    parser_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)

    # SHA-256 ревизии, из которой извлечено. Денормализован намеренно: он же делает
    # повторный запуск задания идемпотентным без обращения к ревизии.
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # Отпечаток канонического содержимого. Отвечает одним сравнением на вопрос «та ли это
    # геометрия, по которой посчитана величина».
    geometry_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Всё, что парсер сообщил сверх колонок: пригодится при разборе расхождений.
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    sheet: Mapped[Sheet] = relationship(back_populates="geometry")

    __table_args__ = (
        CheckConstraint(
            f"coordinate_space = '{COORDINATE_SPACE_PDF_DISPLAY_POINTS_TOP_LEFT}'",
            name="coordinate_space_known",
        ),
        # Нулевая или отрицательная страница — не «странные данные», а неверный расчёт:
        # на неё делят при переводе в нормализованные координаты.
        CheckConstraint(
            "display_width_pt > 0 and display_height_pt > 0", name="display_size_positive"
        ),
        CheckConstraint("pdf_rotation in (0, 90, 180, 270)", name="pdf_rotation_allowed"),
        CheckConstraint("length(source_sha256) = 64", name="source_sha256_length"),
        CheckConstraint("length(geometry_fingerprint) = 64", name="fingerprint_length"),
    )
