"""Контракты заполнения ВОР Заказчика (ADR-0055, п. 7): сравнение и выгрузка копии формы.

Количества Quantor - только от движка (конструкции, проёмы, отделка зон МОП), с происхождением:
лист, вид, задание. Количества Заказчика ни во что не подставляются: они стоят рядом. Цен нет.
Не определено - `None`, а не 0.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel

from app.contracts.cad_vor import CadVorItemRead

# Допуск совпадения количества с ВОР, доля от количества Заказчика.
MATCH_TOLERANCE: Final = 0.02

VorObjectKind = Literal["construction", "door", "finish"]
# Единица количества объекта: м3, м2, м, шт.
VorQuantityUnit = Literal["m3", "m2", "m", "pcs"]
VorFillStatus = Literal["match", "differs", "no_quantor", "unit_mismatch", "no_customer"]


class VorQuantityRead(BaseModel):
    unit: VorQuantityUnit
    value: float


class VorObjectSourceRead(BaseModel):
    """Откуда количество: лист (вид), его задание и примечание (типовые этажи листа)."""

    label: str
    job_id: UUID
    page_index: int
    view: int
    note: str | None


class VorObjectRead(BaseModel):
    """Объект сверки Quantor: группа конструкций, тип двери или слой отделки МОП."""

    group_key: str
    kind: VorObjectKind
    title: str
    quantities: list[VorQuantityRead]
    # Часть листов дала неопределённую величину: сумма неполная.
    incomplete: bool
    sources: list[VorObjectSourceRead]


class VorKindUnavailableRead(BaseModel):
    """Почему объектов вида нет (или не по всем листам)."""

    kind: VorObjectKind
    reason: str


class VorFillItemRead(BaseModel):
    """Позиция ВОР, связанная с объектами Quantor, и сравнение количеств."""

    item: CadVorItemRead
    status: VorFillStatus
    customer_quantity: float | None
    # Единица позиции, приведённая к виду движка; `None` - единица не распознана.
    unit: VorQuantityUnit | None
    quantor_quantity: float | None
    difference: float | None
    difference_percent: float | None
    group_keys: list[str]
    # Связанные ключи, которых нет в текущем результате проекта.
    missing_group_keys: list[str]
    sources: list[str]


class VorFillRead(BaseModel):
    document_id: UUID | None
    has_vor: bool
    items: list[VorFillItemRead]
    # Объекты Quantor без связи: кандидаты в «нет в ВОР».
    unlinked: list[VorObjectRead]
    # Все объекты проекта (для выбора связи у позиции).
    objects: list[VorObjectRead]
    unavailable: list[VorKindUnavailableRead]
    warnings: list[str]
    skipped_sheets: list[str]


class VorFillExportRead(BaseModel):
    """Выгруженный файл: копия формы Заказчика с колонками Quantor."""

    file_name: str
    size: int
    created_at: datetime
    download_url: str
