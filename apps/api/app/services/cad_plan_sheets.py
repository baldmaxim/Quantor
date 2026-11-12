"""Листы-планы ревизии: по названию листа (ADR-0045, массовый запуск PDF -> CAD).

Название — из штампа (`documents.sheet_titles`), а без него — название из паспорта листа или
подпись страницы. Листом-планом считается лист со словом «план» (отдельным словом, с падежными
окончаниями): «План 3 этажа», «Поэтажный план», «Фрагмент плана», «Планы этажей». «Генплан»,
«Планировка» и «Схема планировочной организации» планами не являются. Тип листа из паспорта
(`SheetKind`) решает раньше названия: `floor_plan` — план, любой другой тип — не план.
"""

from __future__ import annotations

import re
from typing import Final

from app.services.consistency.dictionaries import SheetKind

_PLAN_WORD: Final = re.compile(
    r"(?<![а-яё])план(?:ы|а|ов|е|ом|ам|ами|ах)?(?![а-яё])", re.IGNORECASE
)


def is_plan_title(title: str | None) -> bool:
    return bool(title) and _PLAN_WORD.search(title or "") is not None


def is_plan_sheet(
    *,
    stamp_title: str | None,
    passport_kind: str | None,
    passport_title: str | None,
    page_label: str | None,
) -> bool:
    """Лист-план: штамп со словом «план» -> тип паспорта -> название без типа."""
    if stamp_title and is_plan_title(stamp_title):
        return True
    if passport_kind == SheetKind.FLOOR_PLAN.value:
        return True
    if passport_kind is not None:
        return False
    return is_plan_title(stamp_title or passport_title or page_label)
