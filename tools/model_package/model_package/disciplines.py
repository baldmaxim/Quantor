"""Код дисциплины (раздел 2): из суффикса имени файла, иначе из параметра, иначе `UNK`.

Суффикс - последний токен имени через `_` после отбрасывания хвоста вида ` (20260901)` и
чисто цифровых токенов (`…_ARCH_1 (20260901).ifc` → `ARCH`). Принимаются только известные коды,
чтобы `…_R22.ifc` не стал дисциплиной `R22`.
"""

from __future__ import annotations

import re
from pathlib import Path

UNKNOWN = "UNK"

DISCIPLINE_NAMES: dict[str, str] = {
    "ARCH": "Архитектура",
    "STR": "Конструкции",
    "EL": "Электроснабжение и электроосвещение",
    "LC": "Слаботочные системы",
    "PL": "Водоснабжение и канализация",
    "VAC": "Вентиляция и кондиционирование",
    "H": "Отопление",
    "FF": "Пожаротушение",
    "BMS": "Автоматизация и диспетчеризация",
    "TMS": "Тепломеханические решения",
    "GL": "Генплан и благоустройство",
    UNKNOWN: "Не определена",
}

_CODE = re.compile(r"^[A-Z0-9]{1,16}$")
_TAIL = re.compile(r"(\s*\([^()]*\))+\s*$")


def discipline_from_name(file_name: str) -> str | None:
    """Код дисциплины по суффиксу имени файла или `None`."""
    stem = _TAIL.sub("", Path(file_name).stem).strip()
    tokens = [t for t in re.split(r"[_\s]+", stem) if t]
    while tokens and tokens[-1].isdigit():
        tokens.pop()
    if not tokens:
        return None
    code = tokens[-1].upper()
    return code if code in DISCIPLINE_NAMES and code != UNKNOWN else None


def normalize_code(code: str) -> str:
    """Проверка кода из параметра `:ДИСЦИПЛИНА`: латиница и цифры, до 16 знаков."""
    value = code.strip().upper()
    if not _CODE.match(value):
        raise ValueError(f"Код дисциплины {code!r}: нужны латиница и цифры, до 16 знаков")
    return value


def resolve_discipline(file_name: str, explicit: str | None) -> tuple[str, list[str]]:
    """Дисциплина файла и предупреждения (параметр противоречит суффиксу имени)."""
    by_name = discipline_from_name(file_name)
    given = normalize_code(explicit) if explicit else None
    warnings: list[str] = []
    if by_name and given and by_name != given:
        warnings.append(
            f"{file_name}: дисциплина по имени файла {by_name}, в параметре {given}; "
            f"взята {by_name} (суффикс имени главнее)"
        )
    return by_name or given or UNKNOWN, warnings


def discipline_name(code: str) -> str:
    return DISCIPLINE_NAMES.get(code, code)


def split_ifc_arg(value: str) -> tuple[str, str | None]:
    r"""`ФАЙЛ[:ДИСЦИПЛИНА]` → (файл, код). Буква диска Windows (`C:\…`) не считается кодом."""
    head, sep, tail = value.rpartition(":")
    if sep and head and _CODE.match(tail.strip().upper()) and not re.match(r"^[A-Za-z]$", head):
        return head, tail.strip()
    return value, None
