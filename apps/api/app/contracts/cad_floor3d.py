"""Контракты 3D-вида этажа (ADR-0039): новые поля walls.json, ответ сборки модели, ввод человека.

Три группы:

- дополнение к `walls.json` от `tools/cad_walls` v1.1 (контур плиты, отверстия, перемычки) —
  отдельная модель `WallsFloorExtras`, чтобы не менять `WallsDocument`; лишние поля игнорируются;
- ответ API: готовые призмы в мм системы DXF и высоты с источником (фронт геометрию не выводит);
- ввод человека: толщина плиты проекта из разрезов и решения по отверстиям плиты.

Вид только показывает: площади и объёмов, кроме справочной `area_m2` плиты и отверстий, нет;
в итоги обмера, calc и MEP модель не входит.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.cad_constructions import (
    CadConstructionKind,
    CadHeightsRead,
    CadSheetFloorTitle,
    CadValueSource,
)

SLAB_SOURCE_REF_MAX = 200
HOLE_KEY_MAX = 32

# --------------------------------------------------------------------------- walls.json


class WallsSlab(BaseModel):
    """Наружный контур плиты после морфологического замыкания разрывов фасада."""

    model_config = ConfigDict(extra="ignore")

    shell: list[list[float]]
    area_mm2: float
    close_radius_mm: float | None = None


class WallsSlabHole(BaseModel):
    """Отверстие-кандидат: контур, замкнутый стенами без дверного проёма."""

    model_config = ConfigDict(extra="ignore")

    id: str
    shell: list[list[float]]
    area_mm2: float
    status: str = "candidate"
    reason: str | None = None


class WallsOpeningExtras(BaseModel):
    """Направление проёма, контур перемычки и полотно двери у проёма из walls.json."""

    model_config = ConfigDict(extra="ignore")

    id: str
    direction: list[float] | None = None
    lintel: list[list[float]] | None = None
    # Полотно двери (cad_walls v1.4): нет у безымянных разрывов, дверей без разрыва и старых файлов.
    leaf: list[list[float]] | None = None


class WallsFloorExtras(BaseModel):
    """Необязательные поля 3D-вида в walls.json. Поля нет в файле — файл старый (`walls_outdated`).

    Старый файл отличается от нового без плиты (нет стен): у нового ключ `slab` есть, значение
    `null`. Различает их `model_fields_set`.
    """

    model_config = ConfigDict(extra="ignore")

    slab: WallsSlab | None = None
    slab_holes: list[WallsSlabHole] = Field(default_factory=list)
    openings: list[WallsOpeningExtras] = Field(default_factory=list)

    @property
    def is_outdated(self) -> bool:
        return "slab" not in self.model_fields_set


# --------------------------------------------------------------------------- ответы

CadFloor3dHoleState = Literal["candidate", "enabled", "disabled"]
CadFloor3dFamily = Literal["masonry", "monolith"]
CadFloor3dOpeningKind = Literal["door", "gap"]


class CadFloor3dSlabRead(BaseModel):
    """Плита этажа: верх — отметка этажа, низ — отметка минус толщина плиты."""

    shell: list[list[float]]
    # Низ плиты; `None` — толщина плиты не определена.
    z_bottom_mm: int | None
    z_top_mm: int
    # Справка, не расчёт: площадь контура плиты без отверстий.
    area_m2: float


class CadFloor3dHoleRead(BaseModel):
    """Отверстие плиты. `candidate` — решения человека нет: рисуется как отверстие, но помечено."""

    key: str
    shell: list[list[float]]
    area_m2: float
    state: CadFloor3dHoleState


class CadFloor3dWallRead(BaseModel):
    """Призма стены или пилона: обвод из walls.json и отметки низа и верха."""

    construction_key: str
    kind: CadConstructionKind
    family: CadFloor3dFamily
    thickness_nominal_mm: float | None
    shell: list[list[float]]
    holes: list[list[list[float]]]
    z_bottom_mm: int
    # `None` — высота стены не определена (предупреждение `wall_height_missing`), не 0.
    z_top_mm: int | None


class CadFloor3dLintelRead(BaseModel):
    """Перемычка над проёмом: от высоты двери до верха стены."""

    opening_id: str
    kind: CadFloor3dOpeningKind
    shell: list[list[float]]
    z_bottom_mm: int
    z_top_mm: int
    door_height_mm: int
    # `manual` — зона двери человека; иначе источник действующей высоты двери листа.
    door_height_source: CadValueSource | None


class CadFloor3dDoorRead(BaseModel):
    """Полотно двери в разрыве стены: тонкая призма от отметки этажа до высоты двери."""

    opening_id: str
    shell: list[list[float]]
    z_bottom_mm: int
    z_top_mm: int
    door_height_mm: int
    # `manual` — зона двери человека; иначе источник действующей высоты двери листа.
    door_height_source: CadValueSource | None


class CadFloor3dWarningRead(BaseModel):
    code: str
    message: str


class CadFloor3dRead(BaseModel):
    """Модель этажа в мм системы DXF, как `polygon.shell` конструкций."""

    units: Literal["mm"]
    generator: str
    heights: CadHeightsRead
    # Заголовок плана из PDF (корпус, секция, этаж); нет в walls.json — `None`.
    title: CadSheetFloorTitle | None = None
    # Отметка этажа (верх плиты); не определена — 0 и `elevation_known = false`.
    base_z_mm: int
    elevation_known: bool
    slab: CadFloor3dSlabRead | None
    slab_holes: list[CadFloor3dHoleRead]
    walls: list[CadFloor3dWallRead]
    lintels: list[CadFloor3dLintelRead]
    # Полотна дверей (cad_walls v1.4); нет разрыва или старый walls.json — пусто.
    doors: list[CadFloor3dDoorRead] = Field(default_factory=list)
    # [minx, miny, maxx, maxy] по плите и стенам; геометрии нет — `None`.
    bbox: list[float] | None
    warnings: list[CadFloor3dWarningRead]


# --------------------------------------------------------------------------- ввод человека


class CadFloor3dHolePut(BaseModel):
    """Решение человека по отверстию: включено (есть отверстие) или выключено (плита сплошная)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


class CadProjectLevelsWrite(BaseModel):
    """Толщина плиты проекта из разрезов; пустая толщина снимает значение."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    slab_thickness_mm: int | None = Field(
        default=None, ge=100, le=1000, description="Толщина плиты по разрезам, мм"
    )
    slab_source_ref: str | None = Field(
        default=None,
        max_length=SLAB_SOURCE_REF_MAX,
        description="Лист разреза, например «АР1.1 л. 45, разрез 4-4»; обязателен при толщине",
    )

    @model_validator(mode="after")
    def _ref_required(self) -> CadProjectLevelsWrite:
        if self.slab_thickness_mm is not None and not self.slab_source_ref:
            raise ValueError("Укажите лист разреза, из которого взята толщина плиты")
        return self


class CadProjectLevelsRead(BaseModel):
    """Уровни проекта; записи нет — все поля `null`."""

    slab_thickness_mm: int | None
    slab_source_ref: str | None
    updated_at: datetime | None
