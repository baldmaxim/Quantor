"""Ручной обмер: строка списка и её геометрия (ADR-0019).

```text
TakeoffItem   рабочая строка проекта: «Двери», «Перегородка ПГ-1»
  └── Measurement × N   геометрия на конкретном листе
```

`Measurement` хранится отдельно от `Region` и никогда из него не выводится: область —
свидетельство распознавалки, измерение — намерение человека (ADR-0008). Общая таблица
означала бы, что исправление разметки молча меняет посчитанный объём.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import postgresql as pg
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain import GeometryType, MeasurementSource, QuantityUnit
from app.models.mixins import TimestampMixin, str_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.scale import ScaleCalibration
    from app.models.sheet import Sheet


class TakeoffItem(TimestampMixin, Base):
    """Строка списка обмеров.

    Это рабочая строка, а не позиция сметы и не узел классификатора: у сметной позиции
    есть расценка и сборник, а онтология строительных элементов появится не раньше
    распознавания. Пользователь называет строку сам.

    Иерархии нет намеренно. Поле `parent_id` «на всякий случай» немедленно обрастает кодом
    обхода, который потом никто не решится удалить, — а требования на дерево пока нет.
    """

    __tablename__ = "takeoff_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Необязательный код: у кого-то есть своя нумерация, у кого-то нет. Требовать её
    # значило бы навязать чужой порядок работы.
    code: Mapped[str | None] = mapped_column(String(64))

    # Тип задаётся строке, а не измерению: иначе в «Дверях» оказались бы и точки,
    # и площади, а сложить их было бы нечем.
    geometry_type: Mapped[GeometryType] = mapped_column(
        str_enum(GeometryType, name="geometry_type"), nullable=False
    )
    # Выводится из типа и проверяется базой ниже. Свободное поле однажды разошлось бы
    # с типом и показало площадь в метрах.
    display_unit: Mapped[QuantityUnit] = mapped_column(
        str_enum(QuantityUnit, name="quantity_unit", length=8), nullable=False
    )

    # Цвет строки на чертеже. Ключ палитры темы, а не hex: хардкод цвета здесь
    # разъехался бы с тёмной темой.
    color_key: Mapped[str] = mapped_column(
        String(32), nullable=False, default="accent", server_default="accent"
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Архивация вместо удаления: строка, по которой посчитаны объёмы, — это документ.
    # Удалить её значит потерять объяснение чисел, которые могли уйти заказчику.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    project: Mapped[Project] = relationship(back_populates="takeoff_items")
    measurements: Mapped[list[Measurement]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # Единственное место, где соответствие типа и единицы становится физически
        # непредставимым иначе.
        CheckConstraint(
            "(geometry_type = 'count' and display_unit = 'pcs')"
            " or (geometry_type in ('line', 'polyline') and display_unit = 'm')"
            " or (geometry_type = 'polygon' and display_unit = 'm2')",
            name="unit_matches_geometry",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        Index("ix_takeoff_items_project_id_ordinal", "project_id", "ordinal"),
        # Активные строки: список проекта читается на каждом открытии рабочей области,
        # а архивные в нём не участвуют.
        Index(
            "ix_takeoff_items_active",
            "project_id",
            "ordinal",
            postgresql_where=text("archived_at is null"),
        ),
        UniqueConstraint("project_id", "name", name="uq_takeoff_items_project_name"),
    )


class Measurement(TimestampMixin, Base):
    """Геометрия обмера на конкретном листе.

    Координаты — нормализованные точки листа, тот же канон, что у областей: `[[x, y], …]`
    от левого верхнего угла, значения в [0, 1].

    Многоугольник **не замыкается** повторением первой точки: замыкание — свойство типа,
    а не данных, и дублирующая точка ломала бы счёт вершин.
    """

    __tablename__ = "measurements"

    id: Mapped[uuid.UUID] = uuid_pk()
    takeoff_item_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("takeoff_items.id", ondelete="CASCADE"), nullable=False
    )
    sheet_id: Mapped[uuid.UUID] = mapped_column(
        pg.UUID(as_uuid=True), ForeignKey("sheets.id", ondelete="CASCADE"), nullable=False
    )

    # Дублирует тип строки: сверка идёт в сервисе, а здесь тип нужен, чтобы CHECK числа
    # точек можно было записать одной строкой, не заглядывая в соседнюю таблицу.
    geometry_type: Mapped[GeometryType] = mapped_column(
        str_enum(GeometryType, name="geometry_type"), nullable=False
    )
    points: Mapped[list[list[float]]] = mapped_column(pg.JSONB, nullable=False)

    source: Mapped[MeasurementSource] = mapped_column(
        str_enum(MeasurementSource, name="measurement_source"),
        nullable=False,
        default=MeasurementSource.MANUAL,
        server_default=MeasurementSource.MANUAL.value,
    )

    # Та калибровка, по которой посчитано, а не «действующая на сейчас». Отсюда свойство,
    # ради которого всё и делается: смена масштаба листа не меняет уже посчитанное
    # (ADR-0018).
    #
    # NO ACTION, а не RESTRICT: проверка откладывается до конца операции, и удаление листа
    # с каскадом на измерения и калибровки проходит, а точечное удаление калибровки
    # из-под живого измерения — нет. Величина без основания не величина.
    scale_calibration_id: Mapped[uuid.UUID | None] = mapped_column(
        pg.UUID(as_uuid=True),
        ForeignKey("scale_calibrations.id", ondelete="NO ACTION"),
        nullable=True,
    )

    # Оптимистичная блокировка: двое, тянущие одну вершину, должны получить понятный
    # конфликт, а не молча затереть работу друг друга.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # Мягкое удаление: измерение — основание величины, и жёсткое удаление уносит
    # возможность объяснить, почему вчера в отчёте было другое число.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(pg.UUID(as_uuid=True))

    measurement_metadata: Mapped[dict[str, Any]] = mapped_column(
        pg.JSONB, nullable=False, default=dict, server_default="{}"
    )

    item: Mapped[TakeoffItem] = relationship(back_populates="measurements")
    sheet: Mapped[Sheet] = relationship(back_populates="measurements")
    calibration: Mapped[ScaleCalibration | None] = relationship()

    __table_args__ = (
        # Число точек проверяет база, а не только сервис: проверка в приложении ловит
        # ошибку пользователя, проверка здесь — ошибку программиста. Многоугольник из двух
        # точек не имеет площади, и получить его нельзя ни через API, ни ручным SQL.
        CheckConstraint(
            "jsonb_typeof(points) = 'array' and ("
            "(geometry_type = 'count' and jsonb_array_length(points) = 1)"
            " or (geometry_type = 'line' and jsonb_array_length(points) = 2)"
            " or (geometry_type = 'polyline' and jsonb_array_length(points) >= 2)"
            " or (geometry_type = 'polygon' and jsonb_array_length(points) >= 3))",
            name="points_match_geometry",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_measurements_sheet_id_item_id", "sheet_id", "takeoff_item_id"),
        # Активные измерения листа: их читает просмотрщик при каждом открытии.
        Index(
            "ix_measurements_active",
            "sheet_id",
            "takeoff_item_id",
            postgresql_where=text("deleted_at is null"),
        ),
        Index("ix_measurements_item_id", "takeoff_item_id"),
    )
