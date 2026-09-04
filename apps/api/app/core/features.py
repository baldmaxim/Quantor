"""Флаги возможностей портала.

Портал показывает только то, что действительно работает. Всё остальное объявлено
выключенным, чтобы интерфейс честно показывал границу этапа, а не имитировал
функциональность.

Флаги переопределяются переменной окружения `FEATURE_FLAGS` в виде `takeoff.ai=true,reports=true`.
Это нужно для демонстраций и отладки; включение флага не создаёт функциональность,
а лишь перестаёт её прятать.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

# --- работает или дорабатывается в Stage 1 ---
STAGE1_FEATURES: Final[tuple[str, ...]] = (
    "projects",
    "documents",
    "uploads",
    "legacy_import",
    "viewer",
)

# --- Stage 2 и далее: объявлены, но не реализованы ---
STAGE2_FEATURES: Final[tuple[str, ...]] = (
    "takeoff.manual",
    "takeoff.ai",
    "models.gateway",
    "reports",
    "bim.import",
    "drawing.compare",
)

DEFAULTS: Final[MappingProxyType[str, bool]] = MappingProxyType(
    {
        "projects": True,
        "documents": True,
        "uploads": True,
        "legacy_import": True,
        # Просмотрщик появится в промте 07.
        "viewer": False,
        **dict.fromkeys(STAGE2_FEATURES, False),
    }
)


def parse_overrides(raw: str) -> dict[str, bool]:
    """Разбирает `takeoff.ai=true,reports=false`.

    Неизвестные имена игнорируются: опечатка в окружении не должна порождать флаг,
    которого нет в продукте.
    """
    overrides: dict[str, bool] = {}
    for chunk in raw.split(","):
        name, _, value = chunk.partition("=")
        name = name.strip()
        if name in DEFAULTS:
            overrides[name] = value.strip().lower() in ("1", "true", "yes", "on")
    return overrides


def resolve(raw_overrides: str = "") -> dict[str, bool]:
    """Итоговый набор флагов."""
    return {**DEFAULTS, **parse_overrides(raw_overrides)}
