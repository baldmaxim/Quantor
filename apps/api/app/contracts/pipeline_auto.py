"""Пилот автопайплайна: проекты, где после загрузки документов всё запускается само."""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PipelineAutoPilot(BaseModel):
    """Пилот: проекты и предел автозапуска CAD на проект (заданий преобразования всего)."""

    model_config = ConfigDict(extra="forbid")

    project_ids: list[UUID] = Field(min_length=1, max_length=20)
    max_cad_sheets_per_project: Annotated[int, Field(ge=0, le=200)] = 3

    @field_validator("project_ids")
    @classmethod
    def _unique_projects(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("проекты не должны повторяться")
        return value


class PipelineAutoState(BaseModel):
    """Включён ли автопайплайн для проекта: от этого зависит окно прямых вопросов человеку."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
