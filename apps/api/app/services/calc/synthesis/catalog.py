"""Статический каталог синтезаторов: `synthesizer_id@version` → определение в коде.

Демонстрационный синтезатор (PROMPT 05) скрыт из пользовательского списка; рабочие синтезаторы
ВК стадии П (PROMPT 06) — в `systems/vk/synthesizers.py`.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.services.calc.synthesis.definitions import SynthesizerDef, build_registry
from app.services.calc.synthesis.demo import RISER_STRUCTURE
from app.services.calc.systems.vk.synthesizers import VK_SYNTHESIZERS

SYNTHESIZERS: Final[MappingProxyType[tuple[str, int], SynthesizerDef]] = build_registry(
    (RISER_STRUCTURE, *VK_SYNTHESIZERS)
)
