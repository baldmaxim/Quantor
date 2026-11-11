"""ВОР Заказчика в контуре «Конструкции CAD»: хранение, связи с группами, подсказки, сверка листа.

ВОР здесь - объект сверки (ADR-0038 п. 5): количества строк только показываются и на подсчёт
конструкций не влияют, в calc и таблицы обмера не пишутся. Привязка - к проекту. «Текущий» документ
проекта - самый поздний; по нему идут подсказки и список толщин.

Ключ группы - `вид|толщина_мм|материал` (материал может быть пустым). Строится одной функцией
`group_key` и для связей, и для сверки листа.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, get_args

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.contracts.cad_constructions import (
    CadConstructionGroupRead,
    CadConstructionKind,
    CadConstructionRead,
    CadMaterial,
)
from app.contracts.cad_vor import (
    MAX_SUGGESTIONS,
    CadVorCoverageGroupRead,
    CadVorDocumentRead,
    CadVorItemRead,
    CadVorKindHint,
    CadVorLinkRead,
    CadVorSheetColumnsRead,
    CadVorSuggestionRead,
    CadVorSuggestReason,
)
from app.models import CadVorDocument, CadVorItem, CadVorLink
from app.services.cad_vor_import import ParsedWorkbook, normalize_text

_INSERT_CHUNK: Final = 2000
_MAX_SEARCH_TOKENS: Final = 8

# Слова материала в нормализованном наименовании строки ВОР (основы слов).
MATERIAL_WORDS: Final[Mapping[str, tuple[str, ...]]] = {
    "aerated_concrete": ("газобетон", "газоблок", "ячеист"),
    "expanded_clay_block": ("керамзит",),
    "ceramic_block": ("керамическ", "керамоблок", "поризован"),
    "brick_solid": ("кирпич", "полнотел"),
    "brick_hollow": ("кирпич", "пустотел"),
    "silicate_block": ("силикат",),
    "gypsum_tongue_groove": ("пгп", "пазогреб", "гипсов"),
    "monolith_concrete": ("монолит", "железобетон", "ж/б"),
}
# Слова конкретного вида монолита: дают небольшую добавку к виду.
KIND_WORDS: Final[Mapping[str, tuple[str, ...]]] = {
    "monolith_wall": ("стен",),
    "monolith_pylon": ("пилон",),
    "monolith_column": ("колонн",),
}

SCORE_THICKNESS: Final = 10
SCORE_KIND: Final = 4
SCORE_KIND_WORD: Final = 2
SCORE_MATERIAL: Final = 3
SCORE_KIND_CONFLICT: Final = -6


# --------------------------------------------------------------------------- ключ группы


@dataclass(frozen=True, slots=True)
class GroupKeyParts:
    kind: CadConstructionKind
    thickness_mm: float
    material: str


_GROUP_KEY_RE: Final = re.compile(
    r"^(?P<kind>masonry|monolith_wall|monolith_pylon|monolith_column|floor_slab)\|"
    r"(?P<thickness>\d{1,4}(?:\.\d{1,3})?)\|(?P<material>[a-z_]{0,40})$"
)


_KINDS: Final[dict[str, CadConstructionKind]] = {
    kind: kind for kind in get_args(CadConstructionKind)
}


def format_thickness(thickness_mm: float) -> str:
    """Толщина в ключе: целая без «.0», дробная - как есть (137.5)."""
    rounded = round(thickness_mm, 3)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:g}"


def group_key(kind: str, thickness_mm: float, material: str | None) -> str:
    """Ключ группы `вид|толщина_мм|материал`; материала нет - `вид|толщина|`."""
    return f"{kind}|{format_thickness(thickness_mm)}|{material or ''}"


def parse_group_key(key: str) -> GroupKeyParts | None:
    found = _GROUP_KEY_RE.match(key)
    if found is None:
        return None
    return GroupKeyParts(
        _KINDS[found.group("kind")], float(found.group("thickness")), found.group("material")
    )


# --------------------------------------------------------------------------- представление


def item_read(item: CadVorItem) -> CadVorItemRead:
    kind: CadVorKindHint | None = None
    if item.kind_hint == "masonry":
        kind = "masonry"
    elif item.kind_hint == "monolith":
        kind = "monolith"
    return CadVorItemRead(
        id=item.id,
        document_id=item.document_id,
        row_no=item.row_no,
        sheet=item.sheet,
        code=item.code,
        name=item.name,
        unit=item.unit,
        quantity=None if item.quantity is None else float(item.quantity),
        section=item.section,
        thickness_hint_mm=item.thickness_hint_mm,
        kind_hint=kind,
    )


def document_read(document: CadVorDocument) -> CadVorDocumentRead:
    return CadVorDocumentRead(
        id=document.id,
        project_id=document.project_id,
        file_name=document.file_name,
        sha256=document.sha256,
        size=document.size,
        sheet_names=list(document.sheet_names),
        header_row=document.header_row,
        columns=[CadVorSheetColumnsRead.model_validate(entry) for entry in document.columns],
        rows_count=document.rows_count,
        uploaded_by=document.uploaded_by,
        created_at=document.created_at,
    )


# --------------------------------------------------------------------------- документы


async def list_documents(session: AsyncSession, *, project_id: uuid.UUID) -> list[CadVorDocument]:
    """Документы проекта, самый поздний (текущий) первым."""
    rows = await session.scalars(
        select(CadVorDocument)
        .where(CadVorDocument.project_id == project_id)
        .order_by(CadVorDocument.created_at.desc(), CadVorDocument.id)
    )
    return list(rows)


async def current_document(
    session: AsyncSession, *, project_id: uuid.UUID
) -> CadVorDocument | None:
    result = await session.execute(
        select(CadVorDocument)
        .where(CadVorDocument.project_id == project_id)
        .order_by(CadVorDocument.created_at.desc(), CadVorDocument.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_document(
    session: AsyncSession, *, project_id: uuid.UUID, document_id: uuid.UUID
) -> CadVorDocument | None:
    result = await session.execute(
        select(CadVorDocument).where(
            CadVorDocument.id == document_id, CadVorDocument.project_id == project_id
        )
    )
    return result.scalar_one_or_none()


async def create_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    file_name: str,
    storage_key: str,
    sha256: str,
    size: int,
    parsed: ParsedWorkbook,
    user_id: uuid.UUID | None,
) -> CadVorDocument:
    """Документ и все его строки; оригинал уже лежит в хранилище по `storage_key`."""
    document = CadVorDocument(
        id=document_id,
        workspace_id=workspace_id,
        project_id=project_id,
        file_name=file_name,
        storage_key=storage_key,
        sha256=sha256,
        size=size,
        sheet_names=[sheet.sheet for sheet in parsed.sheets],
        header_row=parsed.sheets[0].header_row,
        columns=[
            {
                "sheet": sheet.sheet,
                "header_row": sheet.header_row,
                "rows_count": len(sheet.items),
                "columns": dict(sheet.columns),
            }
            for sheet in parsed.sheets
        ],
        rows_count=parsed.items_count,
        uploaded_by=user_id,
    )
    session.add(document)
    await session.flush()
    rows = [
        {
            "id": uuid.uuid4(),
            "document_id": document_id,
            "row_no": item.row_no,
            "sheet": item.sheet,
            "code": item.code,
            "name": item.name,
            "unit": item.unit,
            "quantity": item.quantity,
            "section": item.section,
            "name_norm": item.name_norm,
            "thickness_hint_mm": item.thickness_hint_mm,
            "kind_hint": item.kind_hint,
        }
        for sheet in parsed.sheets
        for item in sheet.items
    ]
    for start in range(0, len(rows), _INSERT_CHUNK):
        await session.execute(pg_insert(CadVorItem), rows[start : start + _INSERT_CHUNK])
    await session.refresh(document)
    return document


async def delete_document(session: AsyncSession, *, document: CadVorDocument) -> None:
    """Каскадом уходят строки и связи с ними (внешние ключи)."""
    await session.delete(document)
    await session.flush()


# --------------------------------------------------------------------------- строки


def _items_filter(
    document_id: uuid.UUID, *, q: str | None, kind: CadVorKindHint | None, thickness: int | None
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [CadVorItem.document_id == document_id]
    if q:
        for token in normalize_text(q).split()[:_MAX_SEARCH_TOKENS]:
            conditions.append(CadVorItem.name_norm.contains(token, autoescape=True))
    if kind is not None:
        conditions.append(CadVorItem.kind_hint == kind)
    if thickness is not None:
        conditions.append(CadVorItem.thickness_hint_mm == thickness)
    return conditions


async def list_items(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    q: str | None,
    kind: CadVorKindHint | None,
    thickness: int | None,
    limit: int,
    offset: int,
) -> tuple[int, list[CadVorItem]]:
    conditions = _items_filter(document_id, q=q, kind=kind, thickness=thickness)
    total = await session.scalar(select(func.count()).select_from(CadVorItem).where(*conditions))
    rows = await session.scalars(
        select(CadVorItem)
        .where(*conditions)
        .order_by(CadVorItem.sheet, CadVorItem.row_no)
        .limit(limit)
        .offset(offset)
    )
    return total or 0, list(rows)


async def project_item_ids(
    session: AsyncSession, *, project_id: uuid.UUID, item_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """Какие из строк действительно принадлежат документам проекта."""
    if not item_ids:
        return set()
    rows = await session.scalars(
        select(CadVorItem.id)
        .join(CadVorDocument, CadVorItem.document_id == CadVorDocument.id)
        .where(CadVorDocument.project_id == project_id, CadVorItem.id.in_(item_ids))
    )
    return set(rows)


# --------------------------------------------------------------------------- связи


async def load_links(session: AsyncSession, *, project_id: uuid.UUID) -> list[CadVorLinkRead]:
    rows = await session.execute(
        select(CadVorLink, CadVorItem)
        .join(CadVorItem, CadVorLink.vor_item_id == CadVorItem.id)
        .where(CadVorLink.project_id == project_id)
        .order_by(CadVorLink.group_key, CadVorItem.sheet, CadVorItem.row_no)
    )
    return [
        CadVorLinkRead(
            id=link.id, group_key=link.group_key, item=item_read(item), created_at=link.created_at
        )
        for link, item in rows
    ]


def links_by_group(links: Sequence[CadVorLinkRead]) -> dict[str, list[CadVorItemRead]]:
    grouped: dict[str, list[CadVorItemRead]] = defaultdict(list)
    for link in links:
        grouped[link.group_key].append(link.item)
    return dict(grouped)


async def replace_links(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    key: str,
    item_ids: Sequence[uuid.UUID],
    user_id: uuid.UUID | None,
) -> None:
    """Набор связей группы становится ровно `item_ids`; пустой набор снимает все связи."""
    wanted = list(dict.fromkeys(item_ids))
    stale = [CadVorLink.project_id == project_id, CadVorLink.group_key == key]
    if wanted:
        stale.append(CadVorLink.vor_item_id.not_in(wanted))
    await session.execute(delete(CadVorLink).where(*stale))
    if wanted:
        statement = pg_insert(CadVorLink).values(
            [
                {
                    "id": uuid.uuid4(),
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "group_key": key,
                    "vor_item_id": item_id,
                    "created_by": user_id,
                }
                for item_id in wanted
            ]
        )
        await session.execute(
            statement.on_conflict_do_nothing(constraint="uq_cad_vor_links_project_group_item")
        )


# --------------------------------------------------------------------------- подсказки


def score_item(item: CadVorItem, parts: GroupKeyParts) -> tuple[int, list[CadVorSuggestReason]]:
    """Очки строки для группы: толщина (главный признак), вид, слова материала. Без моделей."""
    score = 0
    reasons: list[CadVorSuggestReason] = []
    if item.thickness_hint_mm is not None and item.thickness_hint_mm == round(parts.thickness_mm):
        score += SCORE_THICKNESS
        reasons.append("thickness")
    family = "masonry" if parts.kind == "masonry" else "monolith"
    kind_reason = False
    if item.kind_hint == family:
        score += SCORE_KIND
        kind_reason = True
    elif item.kind_hint is not None:
        score += SCORE_KIND_CONFLICT
    if any(word in item.name_norm for word in KIND_WORDS.get(parts.kind, ())):
        score += SCORE_KIND_WORD
        kind_reason = True
    if kind_reason:
        reasons.append("kind")
    if any(word in item.name_norm for word in MATERIAL_WORDS.get(parts.material, ())):
        score += SCORE_MATERIAL
        reasons.append("material")
    return score, reasons


async def suggest(
    session: AsyncSession, *, document_id: uuid.UUID, parts: GroupKeyParts
) -> list[CadVorSuggestionRead]:
    """До десяти строк-кандидатов для группы, лучшие первыми; связь ставит человек."""
    family = "masonry" if parts.kind == "masonry" else "monolith"
    words = (*MATERIAL_WORDS.get(parts.material, ()), *KIND_WORDS.get(parts.kind, ()))
    candidates: list[ColumnElement[bool]] = [
        CadVorItem.thickness_hint_mm == round(parts.thickness_mm),
        CadVorItem.kind_hint == family,
        *(CadVorItem.name_norm.contains(word, autoescape=True) for word in words),
    ]
    rows = await session.scalars(
        select(CadVorItem).where(CadVorItem.document_id == document_id, or_(*candidates))
    )
    ranked: list[tuple[int, str, int, CadVorSuggestionRead]] = []
    for item in rows:
        score, reasons = score_item(item, parts)
        if score > 0:
            ranked.append(
                (
                    score,
                    item.sheet,
                    item.row_no,
                    CadVorSuggestionRead(item=item_read(item), score=score, reasons=reasons),
                )
            )
    ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    return [entry[3] for entry in ranked[:MAX_SUGGESTIONS]]


async def vor_thicknesses(session: AsyncSession, *, document_id: uuid.UUID) -> list[int]:
    """Толщины, встретившиеся в наименованиях документа, по возрастанию."""
    rows = await session.scalars(
        select(CadVorItem.thickness_hint_mm)
        .where(CadVorItem.document_id == document_id, CadVorItem.thickness_hint_mm.is_not(None))
        .distinct()
        .order_by(CadVorItem.thickness_hint_mm)
    )
    return [value for value in rows if value is not None]


# --------------------------------------------------------------------------- сверка листа


@dataclass(frozen=True, slots=True)
class Coverage:
    groups: list[CadVorCoverageGroupRead]
    not_in_vor_keys: list[str]
    thickness_not_in_vor: list[str]


def build_coverage(
    *,
    totals: Sequence[CadConstructionGroupRead],
    constructions: Sequence[CadConstructionRead],
    linked: Mapping[str, Sequence[CadVorItemRead]],
    thicknesses: Sequence[int],
    has_vor: bool,
) -> Coverage:
    """Какие группы итогов листа связаны со строками ВОР, а какие в ВОР не вошли.

    Количества ВОР с количествами CAD не сравниваются: ВОР на весь объект, лист - его часть.
    В `not_in_vor_keys` попадают конструкции, учтённые в итогах (статус ok), чья группа не связана.
    Нет ВОР или нет в нём ни одной толщины - подсвечивать нечего, соответствующие списки пусты.
    """
    groups: list[CadVorCoverageGroupRead] = []
    unlinked: set[str] = set()
    for total in totals:
        key = group_key(total.kind, total.thickness_mm, total.material)
        items = list(linked.get(key, ()))
        groups.append(
            CadVorCoverageGroupRead(
                group_key=key,
                kind=total.kind,
                thickness_mm=total.thickness_mm,
                material=total.material,
                status="linked" if items else "not_in_vor",
                items=items,
            )
        )
        if not items:
            unlinked.add(key)
    not_in_vor_keys: list[str] = []
    if has_vor:
        for construction in constructions:
            thickness = construction.computed.thickness_mm
            if construction.computed.status != "ok" or thickness is None:
                continue
            # Действующий материал (ввод человека, иначе документ) — как в итогах листа.
            material: CadMaterial | None = construction.material.value
            if group_key(construction.kind, thickness, material) in unlinked:
                not_in_vor_keys.append(construction.id)
    known = set(thicknesses)
    thickness_not_in_vor = (
        [group.group_key for group in groups if round(group.thickness_mm) not in known]
        if has_vor and known
        else []
    )
    return Coverage(groups, not_in_vor_keys, thickness_not_in_vor)
