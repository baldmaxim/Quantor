"""Листы-планы ревизии: по названию листа (ADR-0045, массовый запуск PDF -> CAD).

Название — из штампа (`documents.sheet_titles`), а без него — подпись страницы. Листом-планом
считается лист со словом «план» (отдельным словом, с падежными окончаниями): «План 3 этажа»,
«Поэтажный план», «Фрагмент плана», «Планы этажей». «Генплан», «Планировка» и «Схема
планировочной организации» планами не являются.
"""

from __future__ import annotations

import re
from typing import Final

_PLAN_WORD: Final = re.compile(
    r"(?<![а-яё])план(?:ы|а|ов|е|ом|ам|ами|ах)?(?![а-яё])", re.IGNORECASE
)


def is_plan_title(title: str | None) -> bool:
    return bool(title) and _PLAN_WORD.search(title or "") is not None
