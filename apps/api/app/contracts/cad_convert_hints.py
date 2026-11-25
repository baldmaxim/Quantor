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
MAX_HATCH_CLASSES: Final = 20
MAX_SIGNATURE_ID_LENGTH: Final = 100

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


HatchClassName = Literal["monolith", "masonry", "ignore"]
UnitFloat = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class CadHatchClass(BaseModel):
    """Класс подписи штриховки: числа берутся из `hatch_signatures.json` вида, не от модели."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    signature_id: str | None = Field(default=None, min_length=1, max_length=MAX_SIGNATURE_ID_LENGTH)
    color: tuple[UnitFloat, UnitFloat, UnitFloat]
    pen_pt: float = Field(gt=0, allow_inf_nan=False)
    angle_deg: float = Field(ge=0, lt=180, allow_inf_nan=False)
    pitch_pt: float = Field(gt=0, allow_inf_nan=False)
    class_: HatchClassName = Field(alias="class")


class CadConvertHints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_: Literal["quantor.cad_convert_hints.v1"] = Field(
        default=CONVERT_HINTS_SCHEMA, alias="schema"
    )
    page: Annotated[int, Field(ge=1)]
    # Без классов подписей нужна хотя бы одна рамка; при классах рамок может не быть.
    hints: list[CadConvertHint] = Field(default_factory=list, max_length=MAX_CONVERT_HINTS)
    hatch_classes: list[CadHatchClass] = Field(default_factory=list, max_length=MAX_HATCH_CLASSES)

    @model_validator(mode="after")
    def _unique_ids(self) -> CadConvertHints:
        if not self.hints and not self.hatch_classes:
            raise ValueError("нужна хотя бы одна рамка или один класс подписи штриховки")
        ids = [hint.id for hint in self.hints]
        if len(set(ids)) != len(ids):
            raise ValueError("id подсказок не должны повторяться")
        return self

    def to_params(self) -> dict[str, object]:
        """Объект для `params.convert_hints`: ровно поля формата движка.

        Пустой `hatch_classes` в объект не попадает: параметры (и их хеш) у подсказок без классов
        прежние.
        """
        params = self.model_dump(mode="json", by_alias=True, exclude={"hatch_classes"})
        if self.hatch_classes:
            params["hatch_classes"] = [
                item.model_dump(mode="json", by_alias=True, exclude_none=True)
                for item in self.hatch_classes
            ]
        return params


class CadHintAppliedRead(BaseModel):
    """Строка отчёта движка `hints_applied` по одной рамке (из checks.json вида)."""

    id: str
    type: str
    status: str
    added: int | None = None
    reason: str | None = None
    # Строка класса подписи штриховки (`type = "hatch_class"`): класс, подпись и площадь регионов.
    class_name: str | None = None
    signature_id: str | None = None
    area_mm2: float | None = None
