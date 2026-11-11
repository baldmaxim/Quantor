"""Контракты ВОР Заказчика в контуре «Конструкции CAD» (ADR-0038 п. 5).

ВОР - объект сверки: количества строк отдаются только для показа рядом и с количествами CAD не
сравниваются (ВОР на весь объект, лист - его часть). Не определено - `None`, а не 0.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.cad_constructions import CadConstructionKind, CadMaterial

# Вид, толщина (мм, целая или с долей), материал (может быть пустым): `masonry|100|aerated_concrete`
GROUP_KEY_PATTERN: Final = (
    r"^(?:masonry|monolith_wall|monolith_pylon|monolith_column)"
    r"\|\d{1,4}(?:\.\d{1,3})?\|[a-z_]{0,40}$"
)
MAX_LINKED_ITEMS: Final = 200
MAX_SUGGESTIONS: Final = 10

CadVorKindHint = Literal["masonry", "monolith"]
CadVorCoverageStatus = Literal["linked", "not_in_vor"]
# Почему строка предложена: совпала толщина, вид или слова материала.
CadVorSuggestReason = Literal["thickness", "kind", "material"]


class CadVorSheetColumnsRead(BaseModel):
    """Какие колонки распознаны на листе: роль -> номер колонки с единицы."""

    sheet: str
    header_row: int
    rows_count: int
    columns: dict[str, int]


class CadVorDocumentRead(BaseModel):
    id: UUID
    project_id: UUID
    file_name: str
    sha256: str
    size: int
    sheet_names: list[str]
    header_row: int
    columns: list[CadVorSheetColumnsRead]
    rows_count: int
    uploaded_by: UUID | None
    created_at: datetime


class CadVorItemRead(BaseModel):
    """Строка ВОР; `quantity` - справочно."""

    id: UUID
    document_id: UUID
    row_no: int
    sheet: str
    code: str | None
    name: str
    unit: str | None
    quantity: float | None
    section: str | None
    thickness_hint_mm: int | None
    kind_hint: CadVorKindHint | None


class CadVorItemsRead(BaseModel):
    total: int
    items: list[CadVorItemRead]


class CadVorLinkRead(BaseModel):
    id: UUID
    group_key: str
    item: CadVorItemRead
    created_at: datetime


class CadVorLinksWrite(BaseModel):
    """Полный набор строк ВОР группы: прежние связи группы заменяются."""

    vor_item_ids: list[UUID] = Field(default_factory=list, max_length=MAX_LINKED_ITEMS)


class CadVorSuggestionRead(BaseModel):
    """Строка-кандидат для группы: подсказка, связь ставит человек."""

    item: CadVorItemRead
    score: int
    reasons: list[CadVorSuggestReason]


class CadVorCoverageGroupRead(BaseModel):
    """Группа итогов листа и связанные с ней строки ВОР."""

    group_key: str
    kind: CadConstructionKind
    thickness_mm: float
    material: CadMaterial | None
    status: CadVorCoverageStatus
    # Справочно: количества ВОР с количествами CAD не сравниваются.
    items: list[CadVorItemRead]


class CadVorCoverageRead(BaseModel):
    """Сверка листа с ВОР: что из конструкций листа в ВОР не вошло."""

    job_id: UUID
    page_index: int
    view: int
    # ВОР загружен? Нет - подсвечивать нечего: `not_in_vor_keys` и `thickness_not_in_vor` пусты.
    has_vor: bool
    groups: list[CadVorCoverageGroupRead]
    # id конструкций (в итоги входят только со статусом ok), чья группа не связана со строкой ВОР.
    not_in_vor_keys: list[str]
    # Толщины, встречающиеся в наименованиях текущего ВОР, по возрастанию.
    vor_thicknesses: list[int]
    # group_key групп, чья толщина в ВОР не встречается ни разу: подсказка проверки номиналов.
    thickness_not_in_vor: list[str]
