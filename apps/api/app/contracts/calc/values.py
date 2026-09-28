"""Значение факта.

Числа ходят строками: `"12.5"`, а не `12.5`. JSON-число читается как float, и уже на входе
«3,3 м» становится 3.2999999999999998. Строка разбирается в Decimal без потерь, а схема
OpenAPI остаётся одной для запроса и ответа.

Каноническая форма значения — то, что хранится и сравнивается: число переведено в
каноническую единицу типа факта, лишние нули отброшены, текст очищен от повторных пробелов.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DecimalText = Annotated[
    str,
    Field(
        pattern=r"^-?\d{1,12}(\.\d{1,9})?$",
        description="Десятичное число строкой: «12.5», «-1», «0.035».",
    ),
]

_SPACES = re.compile(r"\s+")


def parse_decimal(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"«{text}» — не десятичное число") from error
    if not value.is_finite():
        raise ValueError("число должно быть конечным")
    return value


def decimal_text(value: Decimal) -> str:
    """Каноническая запись без экспоненты и хвостовых нулей: «3.300» → «3.3», «1E+2» → «100»."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def clean_text(value: str) -> str:
    return _SPACES.sub(" ", value).strip()


class CalcNumberValue(BaseModel):
    """Число с единицей: длина, высота, площадь."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["NUMBER"] = "NUMBER"
    value: DecimalText
    unit: Annotated[str, Field(min_length=1, max_length=16)]


class CalcCountValue(BaseModel):
    """Целое число сущностей: квартир, этажей, стояков. Единица говорит, что именно считается."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["COUNT"] = "COUNT"
    value: Annotated[int, Field(ge=0, le=1_000_000)]
    unit: Annotated[str | None, Field(default=None, max_length=16)] = None
    """Пусто — единица типа факта."""


class CalcBooleanValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["BOOLEAN"] = "BOOLEAN"
    value: bool


class CalcEnumValue(BaseModel):
    """Одно из значений, объявленных типом факта."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ENUM"] = "ENUM"
    value: Annotated[str, Field(min_length=1, max_length=64)]


class CalcTextValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["TEXT"] = "TEXT"
    value: Annotated[str, Field(min_length=1, max_length=500)]


class CalcRangeValue(BaseModel):
    """Диапазон: «17–25 этажей», «до 25». Хотя бы одна граница обязательна."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["RANGE"] = "RANGE"
    low: DecimalText | None = None
    high: DecimalText | None = None
    unit: Annotated[str, Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def _bounds(self) -> CalcRangeValue:
        if self.low is None and self.high is None:
            raise ValueError("у диапазона должна быть хотя бы одна граница")
        if (
            self.low is not None
            and self.high is not None
            and parse_decimal(self.low) > parse_decimal(self.high)
        ):
            raise ValueError("нижняя граница диапазона больше верхней")
        return self


CalcFactValue = Annotated[
    CalcNumberValue
    | CalcCountValue
    | CalcBooleanValue
    | CalcEnumValue
    | CalcTextValue
    | CalcRangeValue,
    Field(discriminator="kind"),
]
"""Значение факта — и на входе, и на выходе. Единая схема: числа строками."""
