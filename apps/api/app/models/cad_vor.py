"""ВОР Заказчика в контуре «Конструкции CAD»: объект сверки, а не вход расчёта (ADR-0038 п. 5).

Три таблицы: загруженный документ, его строки и связи «группа конструкций - строка ВОР». Количества
строк хранятся только для показа рядом и на подсчёт не влияют; в Facts Registry, calc, таблицы
обмера и MEP они не попадают. Оригинал файла лежит в объектном хранилище, в базе - ключ и хеш.
Привязка - к проекту: ВОР один на весь объект, а не на лист.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, uuid_pk

GROUP_KEY_MAX = 64


class CadVorDocument(TimestampMixin, Base):
    """Загруженный XLSX с ВОР Заказчика; «текущий» документ проекта - самый поздний."""

    __tablename__ = "cad_vor_documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Разобранные листы: имена, строка заголовка первого листа и колонки по каждому листу.
    sheet_names: Mapped[list[str]] = mapped_column(
        pg.JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    header_row: Mapped[int] = mapped_column(Integer, nullable=False)
    columns: Mapped[list[dict[str, object]]] = mapped_column(
        pg.JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    rows_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint("size >= 0", name="size_non_negative"),
        CheckConstraint("rows_count >= 0", name="rows_count_non_negative"),
        CheckConstraint("header_row >= 1", name="header_row_positive"),
        CheckConstraint("jsonb_typeof(sheet_names) = 'array'", name="sheet_names_is_array"),
        CheckConstraint("jsonb_typeof(columns) = 'array'", name="columns_is_array"),
    )


class CadVorItem(Base):
    """Строка ВОР: шифр, наименование, единица, количество и подсказки для поиска."""

    __tablename__ = "cad_vor_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("cad_vor_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Номер строки в листе и имя листа: по ним строку находят в исходном файле.
    row_no: Mapped[int] = mapped_column(Integer, nullable=False)
    sheet: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64))
    # Справочно: на расчёт и сверку количеств не влияет. Не определено - NULL, а не 0.
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    # Ближайший вышестоящий заголовок раздела.
    section: Mapped[str | None] = mapped_column(Text)
    name_norm: Mapped[str] = mapped_column(Text, nullable=False)
    thickness_hint_mm: Mapped[int | None] = mapped_column(Integer)
    # masonry | monolith: подсказка по словам наименования.
    kind_hint: Mapped[str | None] = mapped_column(String(16))

    __table_args__ = (
        Index("ix_cad_vor_items_document_id_row_no", "document_id", "row_no"),
        CheckConstraint("row_no >= 1", name="row_no_positive"),
        CheckConstraint(
            "kind_hint is null or kind_hint in ('masonry', 'monolith')", name="kind_hint_values"
        ),
    )


class CadVorLink(Base):
    """Связь группы конструкций с строкой ВОР; ставит человек, на проект."""

    __tablename__ = "cad_vor_links"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # `вид|толщина_мм|материал`; материал может быть пустым.
    group_key: Mapped[str] = mapped_column(String(GROUP_KEY_MAX), nullable=False)
    vor_item_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("cad_vor_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id", "group_key", "vor_item_id", name="uq_cad_vor_links_project_group_item"
        ),
        CheckConstraint(
            f"char_length(group_key) between 3 and {GROUP_KEY_MAX}", name="group_key_length"
        ),
    )
