"""Строгое чтение выхода plangeom: только нужные нормализатору поля, лишнее игнорируется.

Читатель работает только с выходным JSON (parse_page / parse_document). Код plangeom не
импортируется и не используется. Формат библиотеки в альфе: незнакомая версия — отказ.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from building_model.constants import SUPPORTED_PLANGEOM_VERSION
from building_model.geometry import Pt

JsonObject = dict[str, object]

ALLOWED_VERDICTS = frozenset({"accepted", "needs_review"})
PLAN_KIND = "plan"


class UnsupportedVersionError(ValueError):
    """Версия plangeom, под которую нет строгой модели входа."""


class SheetValidationError(ValueError):
    """Лист подходит по kind и verdict, но его структура не соответствует модели входа."""


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class ScaleIn(_In):
    mm_per_pt: float | None = None
    method: str = "none"
    confident: bool = False
    disagrees_with_printed: bool = False


class KindIn(_In):
    kind: str


class AxisIn(_In):
    label: str | None = None
    angle: float = 0.0
    normal: Pt
    offset_mm: float
    bubbles: int = 0


class SegmentIn(_In):
    a: Pt
    b: Pt
    thickness_mm: float


class WallIn(_In):
    id: str
    thickness_mm: float
    role: str | None = None
    area_m2: float = 0.0
    polygon_mm: list[Pt] = []
    segments: list[SegmentIn] = []


class DoorIn(_In):
    id: str
    host_wall: str | None = None
    hinge_mm: Pt
    width_mm: float
    leaves: int = 1
    opening_mm: float
    gap_mm: float | None = None
    end_a_mm: Pt
    end_b_mm: Pt


class GapIn(_In):
    """Окно (windows) или пустой проём (openings): две точки по осевой линии разрыва."""

    id: str
    a_mm: Pt
    b_mm: Pt
    width_mm: float


class RoomIn(_In):
    id: str
    tag: str | None = None
    type: str
    type_source: str = "none"
    area_m2: float
    schedule_area_m2: float | None = None
    polygon_mm: list[Pt] = []


class StairIn(_In):
    id: str
    polygon_mm: list[Pt] = []
    slab_opening_mm: list[Pt] | None = None


class TitleIn(_In):
    floors: list[int] = []
    level_m: float | None = None
    levels_m: list[float] = []


class FloorLevelIn(_In):
    level_m: float | None = None


class SourceIn(_In):
    page: int
    width_pt: float
    height_pt: float
    page_in_volume: int | None = None


class SheetIn(_In):
    plangeom_version: str
    page: int
    verdict: str
    source: SourceIn
    scale: ScaleIn
    kind: KindIn
    section: str | None = None
    title: TitleIn | None = None
    floor_level: FloorLevelIn | None = None
    axes: list[AxisIn] | None = None
    walls: list[WallIn] = []
    doors: list[DoorIn] = []
    windows: list[GapIn] = []
    openings: list[GapIn] = []
    rooms: list[RoomIn] = []
    stairs: list[StairIn] = []
    slab_outlines_mm: list[list[Pt]] | None = None


@dataclass(frozen=True)
class Excluded:
    page: int
    reason: str


def sheet_levels_m(title: TitleIn | None, floor_level: FloorLevelIn | None) -> list[float]:
    """Отметки листа в метрах по возрастанию: штамп важнее отметки, напечатанной на плане."""
    if title is not None and title.levels_m:
        return sorted(title.levels_m)
    if title is not None and title.level_m is not None:
        return [title.level_m]
    if floor_level is not None and floor_level.level_m is not None:
        return [floor_level.level_m]
    return []


def _as_object(value: object, what: str) -> JsonObject:
    if not isinstance(value, dict):
        raise SheetValidationError(f"{what}: ожидался объект JSON")
    return {str(k): v for k, v in value.items()}


def _as_page(raw: JsonObject) -> int:
    page = raw.get("page")
    if not isinstance(page, int) or isinstance(page, bool):
        raise SheetValidationError("у листа нет целого поля page")
    return page


def _single_sheet_page(raw: JsonObject) -> int:
    """Номер страницы одиночного листа: parse_page пишет его только в source.page."""
    if isinstance(raw.get("page"), int) and not isinstance(raw.get("page"), bool):
        return _as_page(raw)
    source = raw.get("source")
    page = source.get("page") if isinstance(source, dict) else None
    if not isinstance(page, int) or isinstance(page, bool):
        raise SheetValidationError("у листа нет целого номера страницы (ни page, ни source.page)")
    return page


def exclusion_reason(raw: JsonObject) -> str | None:
    """Причина, по которой лист не годится для модели плана; None — лист годится."""
    verdict = raw.get("verdict")
    if not isinstance(verdict, str) or verdict not in ALLOWED_VERDICTS:
        return f"verdict:{verdict}"
    kind_obj = raw.get("kind")
    if not isinstance(kind_obj, dict):
        return "kind:missing"
    kind = kind_obj.get("kind")
    if kind != PLAN_KIND:
        return f"kind:{kind}"
    return None


@dataclass
class Document:
    """Комплект: сырые листы по номеру страницы и группировка зданий из вывода plangeom."""

    sheets: dict[int, JsonObject]
    building_pages: list[list[int]] = field(default_factory=list)
    _elevations: dict[int | None, list[float]] = field(default_factory=dict, repr=False)

    def pages(self) -> list[int]:
        return sorted(self.sheets)

    def building_of(self, page: int) -> int | None:
        for index, pages in enumerate(self.building_pages):
            if page in pages:
                return index
        return None

    def known_elevations_mm(self, page: int) -> list[float]:
        """Отметки (мм) всех планов того же здания комплекта: по ним берутся высоты этажей."""
        building = self.building_of(page)
        if building is None:
            return []
        if building not in self._elevations:
            found: set[float] = set()
            for p in self.building_pages[building]:
                raw = self.sheets.get(p)
                if raw is None or exclusion_reason(raw) is not None:
                    continue
                raw_title = raw.get("title")
                raw_level = raw.get("floor_level")
                title = None if raw_title is None else TitleIn.model_validate(raw_title)
                level = None if raw_level is None else FloorLevelIn.model_validate(raw_level)
                found.update(round(m * 1000.0, 1) for m in sheet_levels_m(title, level))
            self._elevations[building] = sorted(found)
        return self._elevations[building]


def _check_version(raw: JsonObject, where: str) -> None:
    version = raw.get("plangeom_version")
    if version != SUPPORTED_PLANGEOM_VERSION:
        raise UnsupportedVersionError(
            f"{where}: версия plangeom {version!r} не поддерживается, "
            f"строгая модель входа написана под {SUPPORTED_PLANGEOM_VERSION!r}"
        )


def document_from_json(data: object) -> Document:
    """Разбор уже загруженного JSON; версия проверяется у каждого листа до любого разбора."""
    top = _as_object(data, "корень файла")
    if "sheets" in top:
        if "plangeom_version" in top:
            _check_version(top, "комплект")
        raw_sheets = top["sheets"]
        if not isinstance(raw_sheets, list):
            raise SheetValidationError("поле sheets не список")
        sheets: dict[int, JsonObject] = {}
        for item in raw_sheets:
            sheet = _as_object(item, "лист")
            page = _as_page(sheet)
            _check_version(sheet, f"страница {page}")
            if page in sheets:
                raise SheetValidationError(f"страница {page} встречается дважды")
            sheets[page] = sheet
        return Document(sheets=sheets, building_pages=_building_pages(top.get("buildings")))
    if "plangeom_version" in top and "walls" in top:
        # Одиночный лист (parse_page): верхнего page нет, номер лежит в source.page.
        page = _single_sheet_page(top)
        _check_version(top, f"страница {page}")
        return Document(sheets={page: {**top, "page": page}})
    raise SheetValidationError("файл не похож на вывод parse_document или parse_page")


def _building_pages(value: object) -> list[list[int]]:
    result: list[list[int]] = []
    if not isinstance(value, list):
        return result
    for building in value:
        pages: list[int] = []
        if isinstance(building, dict):
            listed = building.get("sheets")
            if isinstance(listed, list):
                pages = sorted(p for p in listed if isinstance(p, int) and not isinstance(p, bool))
        result.append(pages)
    return result


def load_document(path: Path) -> Document:
    with path.open("r", encoding="utf-8") as fh:
        data: object = json.load(fh)
    return document_from_json(data)


def read_sheet(doc: Document, page: int) -> SheetIn | Excluded:
    """Лист с неподходящими verdict/kind исключается с причиной; битая структура — ошибка."""
    raw = doc.sheets.get(page)
    if raw is None:
        raise SheetValidationError(f"в комплекте нет страницы {page}")
    reason = exclusion_reason(raw)
    if reason is not None:
        return Excluded(page=page, reason=reason)
    try:
        return SheetIn.model_validate(raw)
    except ValidationError as exc:
        raise SheetValidationError(
            f"страница {page}: структура не соответствует модели входа ({exc.error_count()} ошибок)"
        ) from exc
