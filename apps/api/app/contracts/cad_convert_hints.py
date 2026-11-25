"""Подсказки замечаний в преобразование PDF -> DXF (`quantor.cad_convert_hints.v1`).

Рамка `bbox_pt` - пункты отображаемой страницы PDF от левого верхнего угла (с учётом /Rotate), как
у замечаний проверяющего. Рамка только указывает движку область повторного поиска; геометрию и
размеры строит движок.
"""

from __future__ import annotations

import math
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

CONVERT_HINTS_SCHEMA: Final = "quantor.cad_convert_hints.v1"
MAX_CONVERT_HINTS: Final = 100
MAX_HINT_ID_LENGTH: Final = 64
MAX_HINT_COMMENT_LENGTH: Final = 500

Coordinate = StrictInt | StrictFloat


class CadConvertHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=MAX_HINT_ID_LENGTH)
    type: Literal["missing_wall", "missing_door"]
    bbox_pt: tuple[Coordinate, Coordinate, Coordinate, Coordinate]
    comment: str = Field(default="", max_length=MAX_HINT_COMMENT_LENGTH)

    @model_validator(mode="after")
    def _check_bbox(self) -> CadConvertHint:
        x0, y0, x1, y1 = self.bbox_pt
        if not all(math.isfinite(value) for value in self.bbox_pt):
            raise ValueError("bbox_pt: числа должны быть конечными")
        if not (x0 < x1 and y0 < y1):
            raise ValueError("bbox_pt: x0 < x1 и y0 < y1")
        return self


class CadConvertHints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_: Literal["quantor.cad_convert_hints.v1"] = Field(
        default=CONVERT_HINTS_SCHEMA, alias="schema"
    )
    page: Annotated[int, Field(ge=1)]
    hints: list[CadConvertHint] = Field(min_length=1, max_length=MAX_CONVERT_HINTS)

    @model_validator(mode="after")
    def _unique_ids(self) -> CadConvertHints:
        ids = [hint.id for hint in self.hints]
        if len(set(ids)) != len(ids):
            raise ValueError("id подсказок не должны повторяться")
        return self

    def to_params(self) -> dict[str, object]:
        """Объект для `params.convert_hints`: ровно поля формата движка."""
        return self.model_dump(mode="json", by_alias=True)


class CadHintAppliedRead(BaseModel):
    """Строка отчёта движка `hints_applied` по одной рамке (из checks.json вида)."""

    id: str
    type: str
    status: str
    added: int | None = None
    reason: str | None = None
