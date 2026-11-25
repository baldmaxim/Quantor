"""Заполнение ВОР Заказчика (ADR-0055, п. 7): объекты сверки Quantor и сравнение с позициями ВОР.

Три вида объектов, все количества - от движка, ничего не пересчитывается:
- группы конструкций листа (`CadConstructionGroupRead`, ключ как у связей конструкций);
- двери - проёмы `kind=door` результата конструкций, группа «тип x ширина x высота»;
- отделка зон МОП - слои ведомости отделки, группа «поверхность x работа x материал».

Количества Заказчика ни во что не подставляются: они стоят рядом с количеством Quantor. Цен нет.
Модуль чистый: листы читает вызывающий (API), сюда приходят готовые результаты.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_constructions import CadConstructionGroupRead, CadOpeningRead
from app.contracts.cad_finishes import CadFinishZoneRead, FinishSurface
from app.contracts.cad_vor import MAX_SUGGESTIONS, CadVorLinkRead, CadVorSuggestionRead
from app.contracts.vor_fill import (
    MATCH_TOLERANCE,
    VorFillItemRead,
    VorFillStatus,
    VorKindUnavailableRead,
    VorObjectKind,
    VorObjectRead,
    VorObjectSourceRead,
    VorQuantityRead,
    VorQuantityUnit,
)
from app.models import CadVorItem
from app.services import cad_vor as vor_service

KIND_LABELS: Final[Mapping[str, str]] = {
    "masonry": "Кладка",
    "monolith_wall": "Монолитная стена",
    "monolith_pylon": "Пилон",
    "monolith_column": "Колонна",
    "frame_partition": "Каркасная перегородка",
    "floor_slab": "Плита перекрытия",
}
MATERIAL_LABELS: Final[Mapping[str, str]] = {
    "aerated_concrete": "газобетон",
    "expanded_clay_block": "керамзитобетонный блок",
    "ceramic_block": "керамический блок",
    "brick_solid": "кирпич полнотелый",
    "brick_hollow": "кирпич пустотелый",
    "silicate_block": "силикатный блок",
    "gypsum_tongue_groove": "пазогребневая плита",
    "monolith_concrete": "монолитный железобетон",
    "other": "другой материал",
}
SURFACE_LABELS: Final[Mapping[str, str]] = {"floor": "Пол", "walls": "Стены", "ceiling": "Потолок"}

_UNITS: Final[Mapping[str, VorQuantityUnit]] = {
    "м3": "m3",
    "мкуб": "m3",
    "кубм": "m3",
    "куб": "m3",
    "м2": "m2",
    "мкв": "m2",
    "квм": "m2",
    "кв": "m2",
    "м": "m",
    "мп": "m",
    "погм": "m",
    "пм": "m",
    "шт": "pcs",
    "штук": "pcs",
    "штука": "pcs",
}
_UNIT_NOISE: Final = re.compile(r"[\s.,/]")

DOOR_WORDS: Final = ("двер",)
SURFACE_WORDS: Final[Mapping[str, tuple[str, ...]]] = {
    "floor": ("пол", "стяжк", "плитк", "линолеум", "ламинат"),
    "walls": ("стен", "штукатур", "окраск", "покраск", "обои", "шпатл"),
    "ceiling": ("потол",),
}
SCORE_WORD: Final = 4
SCORE_UNIT: Final = 3


def normalize_unit(raw: str | None) -> VorQuantityUnit | None:
    """Единица позиции ВОР в виде движка; не распознана - `None` (не складывается)."""
    if raw is None:
        return None
    text = _UNIT_NOISE.sub("", raw.lower().replace("ё", "е").replace("³", "3").replace("²", "2"))
    return _UNITS.get(text)


# --------------------------------------------------------------------------- входы


@dataclass(frozen=True, slots=True)
class SheetSource:
    label: str
    job_id: uuid.UUID
    page_index: int
    view: int
    note: str | None = None
    floors: int = 1  # число этажей листа: количества типового листа умножаются на него

    def read(self) -> VorObjectSourceRead:
        return VorObjectSourceRead(
            label=self.label,
            job_id=self.job_id,
            page_index=self.page_index,
            view=self.view,
            note=self.note,
        )


@dataclass(frozen=True, slots=True)
class SheetObjects:
    """Результат конструкций листа: итоги групп, проёмы и высота двери листа (мм)."""

    source: SheetSource
    totals: Sequence[CadConstructionGroupRead]
    openings: Sequence[CadOpeningRead]
    door_height_mm: int | None


@dataclass(frozen=True, slots=True)
class FinishObjects:
    """Зоны листа из ведомости отделки (нужны только `room_mop`)."""

    source: SheetSource
    zones: Sequence[CadFinishZoneRead]


# --------------------------------------------------------------------------- объекты


@dataclass(slots=True)
class _Acc:
    kind: VorObjectKind
    title: str
    quantities: dict[VorQuantityUnit, float] = field(default_factory=dict)
    incomplete: bool = False
    sources: list[SheetSource] = field(default_factory=list)

    def add(self, unit: VorQuantityUnit, value: float | None, floors: int = 1) -> None:
        if value is None:
            self.incomplete = True
            return
        self.quantities[unit] = self.quantities.get(unit, 0.0) + value * floors

    def touch(self, source: SheetSource) -> None:
        if source not in self.sources:
            self.sources.append(source)


def _digest(text: str, size: int) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:size]  # noqa: S324 - ключ, не защита


def construction_title(total: CadConstructionGroupRead) -> str:
    kind = KIND_LABELS.get(total.kind, total.kind)
    material = MATERIAL_LABELS.get(total.material, total.material) if total.material else None
    head = f"{kind}: перемычки над проёмами" if total.element == "lintel" else kind
    parts = [head, f"{vor_service.format_thickness(total.thickness_mm)} мм"]
    if material:
        parts.append(material)
    return ", ".join(parts)


def _construction_quantities(
    total: CadConstructionGroupRead,
) -> list[tuple[VorQuantityUnit, float | None]]:
    """Величины группы в единицах ВОР; неприменимые (нет у вида) не выдаются."""
    rows: list[tuple[VorQuantityUnit, float | None]] = []
    if total.element == "lintel":
        rows.append(("pcs", float(total.count)))
        rows.append(("m", total.length_m))
        return rows
    if total.volume_m3 is not None:
        rows.append(("m3", total.volume_m3))
    area = total.area_m2 if total.area_m2 is not None else total.wall_area_m2
    rows.append(("m2", area))
    rows.append(("m", total.length_m))
    return rows


def door_key(opening: CadOpeningRead, height_mm: int | None) -> str:
    block = (opening.block_name or "").strip().lower()
    kind = _digest(block, 8) if block else ""
    height = "n" if height_mm is None else str(height_mm)
    return f"door|{kind}|{round(opening.width_mm)}x{height}"


def door_title(opening: CadOpeningRead, height_mm: int | None) -> str:
    height = "высота не определена" if height_mm is None else f"{height_mm} мм"
    block = f", блок {opening.block_name}" if opening.block_name else ""
    return f"Дверь {round(opening.width_mm)} x {height}{block}"


def finish_key(surface: FinishSurface, work: str, material: str | None) -> str:
    layer = f"{work}|{material or ''}"
    return f"finish|{surface}|{_digest(layer, 10)}"


def finish_title(surface: FinishSurface, work: str, material: str | None) -> str:
    label = SURFACE_LABELS.get(surface, surface)
    return f"{label} (МОП): {work}" + (f", {material}" if material else "")


def build_objects(
    sheets: Sequence[SheetObjects], finishes: Sequence[FinishObjects]
) -> list[VorObjectRead]:
    """Объекты сверки проекта: суммы по ключу группы со всех листов.

    Количества типового листа умножаются на число этажей его паспорта (`SheetSource.floors`).
    """
    acc: dict[str, _Acc] = {}
    for sheet in sheets:
        for total in sheet.totals:
            key = vor_service.group_key(
                total.kind, total.thickness_mm, total.material, total.element
            )
            entry = acc.setdefault(key, _Acc("construction", construction_title(total)))
            entry.touch(sheet.source)
            for unit, value in _construction_quantities(total):
                entry.add(unit, value, sheet.source.floors)
        for opening in sheet.openings:
            # Проём без двери (gap, окно) и разрыв маячного ряда - не дверь.
            if opening.kind != "door" or opening.marker_row_gap or opening.status == "no_data":
                continue
            key = door_key(opening, sheet.door_height_mm)
            entry = acc.setdefault(key, _Acc("door", door_title(opening, sheet.door_height_mm)))
            entry.touch(sheet.source)
            entry.add("pcs", 1.0, sheet.source.floors)
    for finish in finishes:
        for zone in finish.zones:
            if zone.kind != "room_mop":
                continue
            for layer in zone.layers:
                key = finish_key(layer.surface, layer.work, layer.material)
                entry = acc.setdefault(
                    key, _Acc("finish", finish_title(layer.surface, layer.work, layer.material))
                )
                entry.touch(finish.source)
                entry.add("m2", layer.area_m2, finish.source.floors)
    return [
        VorObjectRead(
            group_key=key,
            kind=entry.kind,
            title=entry.title,
            quantities=[
                VorQuantityRead(unit=unit, value=round(value, 4))
                for unit, value in entry.quantities.items()
            ],
            incomplete=entry.incomplete,
            sources=[source.read() for source in entry.sources],
        )
        for key, entry in sorted(
            acc.items(), key=lambda pair: (pair[1].kind, pair[1].title, pair[0])
        )
    ]


def unavailable_kinds(
    objects: Sequence[VorObjectRead], *, sheets_count: int, mop_zones_count: int
) -> list[VorKindUnavailableRead]:
    """Причина по виду, для которого объектов нет."""
    present = {obj.kind for obj in objects}
    result: list[VorKindUnavailableRead] = []
    if "construction" not in present:
        reason = (
            "нет листов с готовыми конструкциями"
            if sheets_count == 0
            else "на листах нет учтённых конструкций"
        )
        result.append(VorKindUnavailableRead(kind="construction", reason=reason))
    if "door" not in present:
        reason = (
            "нет листов с готовыми конструкциями"
            if sheets_count == 0
            else "в результатах конструкций нет дверных проёмов"
        )
        result.append(VorKindUnavailableRead(kind="door", reason=reason))
    if "finish" not in present:
        reason = (
            "зон МОП в проекте нет"
            if mop_zones_count == 0
            else "у зон МОП нет слоёв отделки: назначьте шаблоны отделки"
        )
        result.append(VorKindUnavailableRead(kind="finish", reason=reason))
    return result


# --------------------------------------------------------------------------- сравнение


def _status(customer: float | None, quantor: float) -> VorFillStatus:
    if customer is None:
        return "no_customer"
    if abs(quantor - customer) <= MATCH_TOLERANCE * abs(customer) + 1e-9:
        return "match"
    return "differs"


def compare(
    links: Sequence[CadVorLinkRead], objects: Mapping[str, VorObjectRead]
) -> list[VorFillItemRead]:
    """Позиции ВОР, у которых есть связь: количество Заказчика, Quantor, разница и статус."""
    keys_by_item: dict[uuid.UUID, list[str]] = defaultdict(list)
    first: dict[uuid.UUID, CadVorLinkRead] = {}
    for link in links:
        keys_by_item[link.item.id].append(link.group_key)
        first.setdefault(link.item.id, link)
    rows: list[VorFillItemRead] = []
    for item_id, link in first.items():
        item = link.item
        keys = list(dict.fromkeys(keys_by_item[item_id]))
        present = [objects[key] for key in keys if key in objects]
        missing = [key for key in keys if key not in objects]
        unit = normalize_unit(item.unit)
        quantor: float | None = None
        status: VorFillStatus
        if not present:
            status = "no_quantor"
        elif unit is None:
            status = "unit_mismatch"
        else:
            values: list[float] = []
            for obj in present:
                found = next((q.value for q in obj.quantities if q.unit == unit), None)
                if found is None:
                    break
                values.append(found)
            if len(values) != len(present):
                status = "unit_mismatch"
            else:
                quantor = round(sum(values), 4)
                status = _status(item.quantity, quantor)
        difference = (
            None if quantor is None or item.quantity is None else round(quantor - item.quantity, 4)
        )
        percent = (
            None
            if difference is None or not item.quantity
            else round(difference / item.quantity * 100, 2)
        )
        rows.append(
            VorFillItemRead(
                item=item,
                status=status,
                customer_quantity=item.quantity,
                unit=unit,
                quantor_quantity=quantor,
                difference=difference,
                difference_percent=percent,
                group_keys=keys,
                missing_group_keys=missing,
                sources=list(dict.fromkeys(s.label for obj in present for s in obj.sources)),
            )
        )
    rows.sort(key=lambda row: (row.item.sheet, row.item.row_no))
    return rows


# --------------------------------------------------------------------------- подсказки


_DOOR_KEY: Final = re.compile(r"^door\|")
_FINISH_KEY: Final = re.compile(r"^finish\|(?P<surface>floor|walls|ceiling)\|")


def is_fill_key(key: str) -> bool:
    return _DOOR_KEY.match(key) is not None or _FINISH_KEY.match(key) is not None


async def suggest(
    session: AsyncSession, *, document_id: uuid.UUID, key: str
) -> list[CadVorSuggestionRead]:
    """Подсказка строк ВОР для двери или отделки по словам наименования и единице; без моделей."""
    found = _FINISH_KEY.match(key)
    if found is not None:
        words = SURFACE_WORDS[found.group("surface")]
        want: VorQuantityUnit = "m2"
    else:
        words = DOOR_WORDS
        want = "pcs"
    rows = await session.scalars(
        select(CadVorItem).where(
            CadVorItem.document_id == document_id,
            or_(*(CadVorItem.name_norm.contains(word, autoescape=True) for word in words)),
        )
    )
    ranked: list[tuple[int, str, int, CadVorSuggestionRead]] = []
    for item in rows:
        score = SCORE_WORD
        if normalize_unit(item.unit) == want:
            score += SCORE_UNIT
        ranked.append(
            (
                score,
                item.sheet,
                item.row_no,
                CadVorSuggestionRead(
                    item=vor_service.item_read(item), score=score, reasons=["kind"]
                ),
            )
        )
    ranked.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    return [entry[3] for entry in ranked[:MAX_SUGGESTIONS]]
