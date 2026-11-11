"""Справочник типов помещений зоны CAD (ADR-0042): единственный источник кодов.

Тип помещения нужен отделке: по нему зоне подбирается шаблон. МОП-коды допустимы только зоне
вида `room_mop`, квартирные - только `room_apartment`; у двери и машино-места типа нет.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

CadRoomType = Literal[
    # МОП
    "lift_hall",
    "vestibule",
    "airlock",
    "corridor",
    "stair",
    "entrance_hall",
    "pui",
    "garbage",
    "tech",
    "mop_other",
    # квартира
    "living",
    "kitchen",
    "bath",
    "wc",
    "hall",
    "storage",
    "balcony",
    "apt_other",
]
CadRoomTypeSource = Literal["manual", "derived"]

MOP_ROOM_TYPES: Final[frozenset[str]] = frozenset(
    {
        "lift_hall",
        "vestibule",
        "airlock",
        "corridor",
        "stair",
        "entrance_hall",
        "pui",
        "garbage",
        "tech",
        "mop_other",
    }
)
APARTMENT_ROOM_TYPES: Final[frozenset[str]] = frozenset(
    {"living", "kitchen", "bath", "wc", "hall", "storage", "balcony", "apt_other"}
)
ROOM_TYPE_VALUES: Final[tuple[str, ...]] = get_args(CadRoomType)
