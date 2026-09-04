"""Флаги возможностей портала.

Stage 1 отдаёт наружу только то, что действительно работает: проекты, импорт распознанного
пакета и просмотрщик. Всё остальное объявлено выключенным, чтобы интерфейс честно показывал
границу этапа, а не имитировал функциональность.

Значения фиксированы в коде: конфигурируемые флаги появятся вместе с реальными потребителями
(промт 08). Список намеренно совпадает с разделами будущего интерфейса.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

FEATURE_FLAGS: Final[MappingProxyType[str, bool]] = MappingProxyType(
    {
        # --- работает или дорабатывается в Stage 1 ---
        "projects": True,
        "legacy_import": False,
        "viewer": False,
        # --- Stage 2 и далее ---
        "takeoff.manual": False,
        "takeoff.ai": False,
        "models.gateway": False,
        "reports": False,
        "bim.import": False,
        "drawing.compare": False,
    }
)
