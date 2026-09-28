"""Статический каталог синтезаторов: `synthesizer_id@version` → определение в коде.

Сейчас только демонстрационный синтезатор (PROMPT 05). Реальные синтезаторы ВК — кодом так же.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.services.calc.synthesis.definitions import SynthesizerDef, build_registry
from app.services.calc.synthesis.demo import RISER_STRUCTURE

SYNTHESIZERS: Final[MappingProxyType[tuple[str, int], SynthesizerDef]] = build_registry(
    (RISER_STRUCTURE,)
)
