"""Место и система факта — «субъект» в ключе факта.

Субъект задаётся кодами, как их пишут в документах: корпус «1», секция «2», этаж «12» или
группа этажей «2..24», помещение «кв. 12», система «В1» раздела ВК. Коды, а не
идентификаторы строк: два источника, назвавшие один и тот же корпус, должны попасть в один
ключ без общей таблицы мест.

Обозначения систем нормализуются: латинские буквы, неотличимые от кириллических (B, T, K, P…),
приводятся к кириллице. В распознанном тексте, в xlsx и в ВОР встречается то одно, то другое,
и «B1» с латинской B иначе стал бы отдельной системой.

Квалификатор уточняет, что именно считается, из закрытого перечня типа факта: тип квартиры
«R2», вид прибора «WC». Он часть ключа: две квартиры разных типов — разные ключи, а не спор.
"""

from __future__ import annotations

import re
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.calc.enums import CalcDiscipline

SUBJECT_FIELDS: Final[tuple[str, ...]] = (
    "building",
    "section",
    "floor",
    "room",
    "discipline",
    "system_code",
    "qualifier",
)

# Символы-разделители ключа в кодах запрещены: иначе два разных субъекта могли бы дать
# одинаковую строку ключа.
_FORBIDDEN = re.compile(r"[|=;@]")
_SPACES = re.compile(r"\s+")
_FLOOR = re.compile(r"^-?\d{1,3}(\.\.-?\d{1,3})?$")
_QUALIFIER = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")

_LOOKALIKES: Final[dict[str, str]] = {
    "A": "А",
    "B": "В",
    "C": "С",
    "E": "Е",
    "H": "Н",
    "K": "К",
    "M": "М",
    "O": "О",
    "P": "Р",
    "T": "Т",
    "X": "Х",
    "Y": "У",
}

SubjectCode = Annotated[str, Field(min_length=1, max_length=64)]


def _clean(value: str) -> str:
    cleaned = _SPACES.sub(" ", value).strip()
    if not cleaned:
        raise ValueError("код не может быть пустым")
    if _FORBIDDEN.search(cleaned):
        raise ValueError("код не может содержать символы | = ; @")
    return cleaned


def normalize_system_code(value: str) -> str:
    """«b1» и «В1» — одна система: верхний регистр, латинские двойники заменены кириллицей."""
    cleaned = _clean(value).upper().replace(" ", "")
    return "".join(_LOOKALIKES.get(char, char) for char in cleaned)


def _floor_code(value: str) -> str:
    cleaned = _clean(value).replace(" ", "")
    if not _FLOOR.match(cleaned):
        raise ValueError("этаж — целое число («12», «-1») или диапазон «2..24»")
    if ".." in cleaned:
        low, high = (int(part) for part in cleaned.split(".."))
        if low >= high:
            raise ValueError("в диапазоне этажей начало должно быть меньше конца")
        return f"{low}..{high}"
    return str(int(cleaned))


class CalcFactSubject(BaseModel):
    """К чему относится факт: место в здании и, если нужно, инженерная система."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    building: SubjectCode | None = None
    """Корпус — код, как в документах: «1», «2А»."""
    section: SubjectCode | None = None
    """Секция."""
    floor: SubjectCode | None = None
    """Этаж «12», подземный «-1» или группа этажей «2..24»."""
    room: SubjectCode | None = None
    """Помещение или квартира."""
    discipline: CalcDiscipline | None = None
    """Раздел: без него «В1» водопровода не отличить от «В1» вытяжной вентиляции."""
    system_code: SubjectCode | None = None
    """Обозначение системы: «В1», «Т3», «К1», «П1»."""
    qualifier: SubjectCode | None = None
    """Значение из перечня квалификаторов типа факта: тип квартиры «R2», прибор «WC»."""

    @field_validator("building", "section", "room")
    @classmethod
    def _plain(cls, value: str | None) -> str | None:
        return None if value is None else _clean(value)

    @field_validator("floor")
    @classmethod
    def _floor(cls, value: str | None) -> str | None:
        return None if value is None else _floor_code(value)

    @field_validator("system_code")
    @classmethod
    def _system(cls, value: str | None) -> str | None:
        return None if value is None else normalize_system_code(value)

    @field_validator("qualifier")
    @classmethod
    def _qualifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean(value).upper()
        if not _QUALIFIER.match(cleaned):
            raise ValueError("квалификатор — код из перечня типа факта: «R2», «WC»")
        return cleaned

    @model_validator(mode="after")
    def _system_needs_discipline(self) -> CalcFactSubject:
        if self.system_code is not None and self.discipline is None:
            raise ValueError("у системы должен быть указан раздел")
        return self

    def present_fields(self) -> frozenset[str]:
        return frozenset(name for name in SUBJECT_FIELDS if getattr(self, name) is not None)

    def key(self) -> str:
        """Каноническая строка субъекта: порядок полей фиксирован, пустые пропущены."""
        parts: list[str] = []
        for name in SUBJECT_FIELDS:
            value = getattr(self, name)
            if value is not None:
                parts.append(
                    f"{name}={value.value if isinstance(value, CalcDiscipline) else value}"
                )
        return "|".join(parts) if parts else "project"
