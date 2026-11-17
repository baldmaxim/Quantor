"""Контракт общего вида здания для 3D: список этажей проекта с отметками и контуром плиты.

Вид только показывает: этаж — лист CAD с готовыми конструкциями; в итоги обмера, calc и MEP
он не входит. Высоты — те же действующие значения, что в модели этажа (ADR-0039).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.contracts.cad_constructions import CadConstructionKind

CadBuilding3dOutlineSource = Literal["slab", "bbox"]
# `reference` - эталонный этаж группы; `axes` - совмещён с эталоном по общим осям;
# `none` - не совмещён (смещение - запасное: центр контура на центр эталона или 0).
CadBuilding3dAlignment = Literal["reference", "axes", "none"]
# Постановка здания на объект: `reference` - опора (система объекта = система её эталона);
# `axes` - поставлено по общим маркам осей; `cores` - скопление зданий поставлено по совпадению
# ядер (монолита) с уже поставленными, с поворотом; `none` - не поставлено, геометрия в своей
# системе; `manual` - привязано человеком по двум парам точек (ADR-0052).
CadBuilding3dPlacement = Literal["reference", "axes", "cores", "manual", "none"]
# Откуда высота этажа, когда она не определена (`floor_height_known = false`): `derived_stack` -
# разность отметок до следующего этажа здания; `default` - типовая (соседа сверху нет).
CadBuilding3dHeightSource = Literal["derived_stack", "default"]
# Почему лист с конструкциями не вошёл в стопку этажей: `not_plan` - не план этажа или уровня
# (разрез, таблица); `superseded` - дубль плана на той же отметке, оставлен лист большей площади;
# `summary_unplaced` - сводный лист планов нескольких секций, не вставший на площадку.
CadBuilding3dServiceReason = Literal["not_plan", "superseded", "summary_unplaced"]


class CadBuilding3dWarningRead(BaseModel):
    code: str
    message: str


CadBuilding3dLevelSource = Literal["marks", "base"]


class CadBuilding3dWallRead(BaseModel):
    """Конструкция этажа для общего вида: внешнее кольцо в целых мм системы DXF, без отверстий."""

    # Идентификатор конструкции из walls.json: по нему клик в 3D находит карточку конструкции.
    id: str
    kind: CadConstructionKind
    # Открытое кольцо (без повтора первой точки), не менее 3 и не более 64 точек.
    shell: list[list[int]]
    # Верх конструкции по знаку отметки на плане (парапет, cad_walls v1.15), мм от 0.000;
    # `None` - верх по высоте этажа.
    top_mm: int | None = None


class CadBuilding3dWindowRead(BaseModel):
    """Окно этажа с высотой по виду фасада или ручному вводу листа (ADR-0048 п. 6).

    Контур проёма - открытое кольцо в целых мм, не более 16 точек, уже преобразованное как этаж
    (`rotation_deg`, `offset_mm`). Все z - абсолютные мм от +-0,000: подоконная часть - от
    `sill_z_bottom_mm` (верх плиты) до `glass_z_bottom_mm`, стекло - от `glass_z_bottom_mm` до
    `glass_z_top_mm`, перемычка - от `glass_z_top_mm` до `lintel_z_top_mm` (верх стены этажа).
    Верх окна не ниже верха стены - перемычки нет: `lintel_z_top_mm = glass_z_top_mm`; нет
    подоконной части - `sill_z_bottom_mm = glass_z_bottom_mm`. `accepted = false` - вид фасада
    не принят человеком: окно показывается как кандидат.
    """

    opening_id: str
    shell: list[list[int]]
    sill_z_bottom_mm: int
    glass_z_bottom_mm: int
    glass_z_top_mm: int
    lintel_z_top_mm: int
    accepted: bool
    source: Literal["facade", "manual"]


class CadBuilding3dLevelZoneRead(BaseModel):
    """Участок плиты этажа на своей отметке (кровля со скатами, ступенчатый первый этаж).

    Кольца - целые мм, уже преобразованные как этаж (`rotation_deg`, `offset_mm`), без повтора
    первой точки.
    `top_mm` - верх плиты участка от 0.000 (действующие высоты листа: ручная отметка этажа
    сдвигает все участки вместе); `mark_mm` / `max_mm` - отметки поверхности по знакам плана
    (уклон), `source = base` - знаков на участке нет, основной уровень листа.
    """

    shell: list[list[int]]
    holes: list[list[list[int]]]
    top_mm: int
    mark_mm: int | None
    max_mm: int | None
    source: CadBuilding3dLevelSource


class CadBuilding3dFloorRead(BaseModel):
    """Этаж здания: адрес листа, отметки и контур плиты в мм системы DXF."""

    job_id: UUID
    revision_id: UUID
    page_index: int
    view: int
    document_id: UUID | None
    label: str
    # Отметка этажа (верх плиты); не определена — 0 и `elevation_known = false`.
    elevation_known: bool
    base_z_mm: int
    # Высота этажа и толщина плиты; не определены — значения для отрисовки и
    # `*_known = false` (значение не из документации и не от человека).
    floor_height_mm: int
    floor_height_known: bool
    # Источник высоты для отрисовки, когда она не определена; определена - `None`.
    floor_height_source: CadBuilding3dHeightSource | None = None
    slab_thickness_mm: int
    slab_thickness_known: bool
    # Контур плиты (не более 200 точек) или прямоугольник по стенам.
    outline: list[list[float]]
    outline_source: CadBuilding3dOutlineSource
    # [minx, miny, maxx, maxy] по плите и стенам листа.
    bbox: list[float] | None
    # Корпус и секция из заголовка плана; нет заголовка - `None`.
    corps: str | None
    section: str | None
    # Здание (корпус + секция), к которому относится этаж: ключ и подпись для переключателя.
    group_key: str
    group_label: str
    # Преобразование вида (системы DXF листа) в систему группы или объекта, уже применённое к
    # контуру, bbox, конструкциям и участкам плиты этажа:
    #   p = R(rotation_deg) · p_вида + offset_mm
    # (поворот вокруг начала кадра вида, затем сдвиг; градусы против часовой стрелки).
    # `offset_mm` - совмещение с эталоном группы плюс постановка группы на объект
    # (`CadBuilding3dGroupRead.site_offset_mm`); у поставленной группы геометрия в системе объекта,
    # у не поставленной - в системе эталона группы.
    offset_mm: tuple[float, float]
    # `rotation_deg` - поворот этажа в группе, кратный 90 градусам, когда подписи общих осей листа
    # меняют направление относительно эталона (лист нарисован повёрнутым), плюс поворот группы
    # при посадке на объект по ядрам (`CadBuilding3dGroupRead.site_rotation_deg`).
    rotation_deg: float = 0.0
    alignment: CadBuilding3dAlignment
    # Подписи общих осей, по которым совмещён этаж (`alignment = axes`).
    alignment_axes: list[str]
    # Почему этаж не совмещён (`alignment = none`); иначе `None`.
    alignment_message: str | None
    # Качество совмещения по осям (`alignment = axes`): остаток согласных осей после сдвига (СКО
    # и максимум, мм) и число общих с эталоном марок; согласные - `alignment_axes`.
    alignment_rms_mm: float | None = None
    alignment_max_mm: float | None = None
    alignment_axes_common: int | None = None
    # Наклон шкалы лист - эталон, промилле: на столько расстояния между осями эталона больше, чем
    # на листе (масштабы листов расходятся). Осей для оценки мало - `None`.
    alignment_scale_permille: float | None = None
    # Этаж типового листа на несколько этажей, показанный копией геометрии листа: подпись листа.
    # Только для 3D: в объёмы листа копия не входит. У этажа самого листа - `None`.
    typical_of: str | None = None
    # Вид плана по заголовку (`floor` | `roof` | `roof_exit` | `technical`); старый файл - `None`.
    kind: str | None = None
    # Участки плиты на своих отметках (cad_walls v1.15). Есть - плита рисуется по ним, а не по
    # `outline`; пусто - одна плита на `base_z_mm`.
    levels: list[CadBuilding3dLevelZoneRead] = []
    # Контуры конструкций этажа (без плиты: она рисуется по `outline`), уже преобразованные как
    # этаж (`rotation_deg`, `offset_mm`). `None` - не запрошено (`walls=false`); при
    # `walls=true` - список (может быть пустым).
    walls: list[CadBuilding3dWallRead] | None = None
    # Окна этажа с высотой (фасад или ручной ввод листа), уже преобразованные как этаж. `None` - не
    # запрошено (`walls=false`); при `walls=true` - список (может быть пустым). Окна без высоты
    # не выдаются.
    windows: list[CadBuilding3dWindowRead] | None = None


class CadBuilding3dGroupRead(BaseModel):
    """Здание для переключателя вида: этажи одного корпуса и секции."""

    key: str
    label: str
    floor_count: int
    # Этажи, совмещённые по осям (эталон входит).
    aligned_count: int
    # Постановка на объект по общим маркам осей с другими зданиями (план паркинга несёт оси всех).
    placement: CadBuilding3dPlacement
    # Сдвиг из системы эталона группы в систему объекта, мм; уже применён к этажам группы.
    # С поворотом: точка объекта = R(site_rotation_deg) · точка группы + site_offset_mm.
    site_offset_mm: tuple[float, float]
    site_rotation_deg: float = 0.0
    # Доля монолита скопления, совпавшая с монолитом поставленных зданий (постановка по ядрам);
    # без попытки - `None`.
    placement_share: float | None = None
    # Марки, по которым здание поставлено, и ключ здания, к которому оно привязано.
    placement_axes: list[str]
    placement_anchor: str | None
    # Почему здание не поставлено (`placement = none`); иначе `None`.
    placement_message: str | None
    # Ручная привязка (`placement = manual`): id применённой привязки корпуса к площадке.
    site_pin_id: UUID | None = None


class CadBuilding3dServiceSheetRead(BaseModel):
    """Служебный лист: конструкции посчитаны, но в стопку этажей здания лист не входит."""

    job_id: UUID
    revision_id: UUID
    page_index: int
    view: int
    document_id: UUID | None
    label: str
    reason: CadBuilding3dServiceReason
    message: str


class CadBuilding3dRead(BaseModel):
    units: Literal["mm"]
    floors: list[CadBuilding3dFloorRead]
    groups: list[CadBuilding3dGroupRead]
    warnings: list[CadBuilding3dWarningRead]
    # Листы вне стопки этажей: не планы и дубли планов.
    service_sheets: list[CadBuilding3dServiceSheetRead] = []
