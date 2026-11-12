"""Контракты реестра стояков листа CAD (ADR-0041, схема файла `cad_risers.v1`)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RISERS_SCHEMA: Final = "cad_risers.v1"
MAX_RISERS: Final = 120
MARK_MAX: Final = 32
TEXT_MAX: Final = 200
DN_MIN_MM: Final = 10
DN_MAX_MM: Final = 400
COUNT_MAX: Final = 8
SHAFT_ID_PATTERN: Final = r"^S\d{2,3}$"
SECTION_MIN_MM: Final = 50
SECTION_MAX_MM: Final = 3000
CHANNEL_D_MIN_MM: Final = 50
CHANNEL_D_MAX_MM: Final = 2000
FLOOR_MIN: Final = -10
FLOOR_MAX: Final = 200
EI_MAX: Final = 16


class RiserSystem(StrEnum):
    """Система стояка. Отопление в реестр не входит: генерируется как в cad_mep.v5."""

    V1 = "V1"
    T3 = "T3"
    T4 = "T4"
    VPV = "VPV"
    AUP = "AUP"
    FS = "FS"
    K1 = "K1"
    K2 = "K2"
    K4 = "K4"
    DRK = "DRK"
    VZH = "VZH"
    MO = "MO"
    VMOP = "VMOP"
    PMOP = "PMOP"
    DU = "DU"
    KDU = "KDU"
    DP = "DP"
    TRV = "TRV"


# Трубные системы: у них только `dn_mm`; воздушные: только `section_mm` или `d_mm`.
PIPE_SYSTEMS: Final = frozenset(
    {
        RiserSystem.V1,
        RiserSystem.T3,
        RiserSystem.T4,
        RiserSystem.VPV,
        RiserSystem.AUP,
        RiserSystem.FS,
        RiserSystem.K1,
        RiserSystem.K2,
        RiserSystem.K4,
        RiserSystem.DRK,
    }
)
AIR_SYSTEMS: Final = frozenset(
    {
        RiserSystem.VZH,
        RiserSystem.MO,
        RiserSystem.VMOP,
        RiserSystem.PMOP,
        RiserSystem.DU,
        RiserSystem.KDU,
        RiserSystem.DP,
        RiserSystem.TRV,
    }
)


class RiserServes(StrEnum):
    """Что обслуживает стояк (необязательная подсказка генератору)."""

    APARTMENTS = "apartments"
    CORRIDOR = "corridor"
    LOBBY_PBZ = "lobby_pbz"
    TAMBOUR = "tambour"
    STAIR = "stair"
    LIFT = "lift"
    PARKING = "parking"


class RiserValve(StrEnum):
    """Клапан на стояке: нет, нормально открытый, нормально закрытый."""

    NONE = "none"
    NO = "NO"
    NZ = "NZ"


# Поля cad_mep.v10: в файл для генератора попадают только заданные (ADR-0041, A3), поэтому
# реестр без них даёт прежний файл и прежний sha256.
V10_OPTIONAL_FIELDS: Final = ("section_mm", "d_mm", "floors", "serves", "valve", "ei")


class RiserRole(StrEnum):
    OWN = "own"
    TRANSIT = "transit"


class CadRiserEntry(BaseModel):
    """Одна запись реестра; поля - как в файле `risers.json`, который читает генератор."""

    model_config = ConfigDict(extra="forbid")

    system: RiserSystem
    mark: str = Field(min_length=1, max_length=MARK_MAX)
    dn_mm: int | None = Field(default=None, ge=DN_MIN_MM, le=DN_MAX_MM)
    role: RiserRole
    count: int = Field(default=1, ge=1, le=COUNT_MAX)
    shaft_id: str | None = Field(default=None, pattern=SHAFT_ID_PATTERN)
    source: str | None = Field(default=None, max_length=TEXT_MAX)
    note: str | None = Field(default=None, max_length=TEXT_MAX)
    # Поля cad_mep.v10, необязательные. Сечение прямоугольного канала `[a, b]` или Ø круглого, мм.
    section_mm: (
        tuple[
            Annotated[int, Field(ge=SECTION_MIN_MM, le=SECTION_MAX_MM)],
            Annotated[int, Field(ge=SECTION_MIN_MM, le=SECTION_MAX_MM)],
        ]
        | None
    ) = None
    d_mm: int | None = Field(default=None, ge=CHANNEL_D_MIN_MM, le=CHANNEL_D_MAX_MM)
    # Этажи `[от, до]` включительно.
    floors: (
        tuple[
            Annotated[int, Field(ge=FLOOR_MIN, le=FLOOR_MAX)],
            Annotated[int, Field(ge=FLOOR_MIN, le=FLOOR_MAX)],
        ]
        | None
    ) = None
    serves: RiserServes | None = None
    valve: RiserValve | None = None
    ei: str | None = Field(default=None, max_length=EI_MAX)

    @field_validator("mark", mode="before")
    @classmethod
    def _strip_mark(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("shaft_id", "source", "note", "ei", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        """Пустая строка поля формы - то же, что «не задано»."""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def _check_system_fields(self) -> CadRiserEntry:
        if self.section_mm is not None and self.d_mm is not None:
            raise ValueError("section_mm и d_mm задаются не вместе")
        if self.system in PIPE_SYSTEMS and (self.section_mm is not None or self.d_mm is not None):
            raise ValueError("у трубной системы нет section_mm и d_mm: задайте dn_mm")
        if self.system in AIR_SYSTEMS and self.dn_mm is not None:
            raise ValueError("у воздушной системы нет dn_mm: задайте section_mm или d_mm")
        if self.floors is not None and self.floors[0] > self.floors[1]:
            raise ValueError("floors: начало диапазона больше конца")
        return self


class CadSheetRisersPut(BaseModel):
    """Реестр листа заменяется целиком; пустой список = реестра нет."""

    model_config = ConfigDict(extra="forbid")

    risers: list[CadRiserEntry] = Field(max_length=MAX_RISERS)


class CadSheetRisersOut(BaseModel):
    revision_id: UUID
    page_index: int
    view: int
    risers: list[CadRiserEntry]
    # `null` - реестр не вводился.
    updated_at: datetime | None
