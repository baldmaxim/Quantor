"""Версии промтов ИИ-проверки и статистика по ним (админка)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts.cad_ai_review import AiRole
from app.models.ai_prompt import AI_PROMPT_MAX_BYTES, AI_PROMPT_MAX_NOTE

AiPromptStatus = Literal["draft", "active", "archived"]


class AiPromptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AiRole
    text: str = Field(min_length=1)
    note: str | None = Field(default=None, max_length=AI_PROMPT_MAX_NOTE)

    @field_validator("text")
    @classmethod
    def check_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Текст промта пуст")
        if len(value.encode()) > AI_PROMPT_MAX_BYTES:
            raise ValueError("Текст промта больше 64 КиБ")
        return value


class AiPromptSummary(BaseModel):
    """Версия без текста: список не тащит до 64 КиБ на строку."""

    id: UUID
    role: AiRole
    version: int
    status: AiPromptStatus
    note: str | None
    created_by: UUID | None
    created_at: datetime
    activated_at: datetime | None
    text_bytes: int


class AiPromptRead(AiPromptSummary):
    text: str


class AiPromptStatsRow(BaseModel):
    """Итоги прогонов одной версии. Прогоны без версии (до версионирования) не учитываются."""

    prompt_id: UUID
    role: AiRole
    version: int
    status: AiPromptStatus
    runs_total: int
    runs_succeeded: int
    runs_failed: int
    # Средние и суммы считаются по прогонам, где значение есть; нет ни одного - null, не 0.
    cost_avg_usd: float | None
    cost_sum_usd: float | None
    duration_avg_ms: float | None
    verdicts: dict[str, int]
    findings_total: int
    findings_by_type: dict[str, int]
    # Судьба замечаний ИИ этой версии: открыты, закрыты, удалены (ключа уже нет в cad_remarks).
    remarks_open: int
    remarks_resolved: int
    remarks_deleted: int


class AiPromptStats(BaseModel):
    rows: list[AiPromptStatsRow]
