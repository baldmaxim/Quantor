"""Вход пилота и отчёт проверки обводок."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import JobStatus

SourceRole = Literal["project", "explanatory_note", "terms_of_reference", "contract"]
SOURCE_ROLES = ("project", "explanatory_note", "terms_of_reference", "contract")


class PilotFloor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    floor: int
    pdf_page: int = Field(ge=1, le=999)
    view: int = Field(ge=1, le=99)


class OutlinePilot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    revision_id: UUID
    section: int = Field(ge=1)
    floors: list[PilotFloor] = Field(min_length=2, max_length=3)
    sources: dict[SourceRole, str]

    @model_validator(mode="after")
    def verify_scope(self) -> "OutlinePilot":
        if len({row.floor for row in self.floors}) != len(self.floors):
            raise ValueError("Этажи пилота должны различаться")
        if len({(row.pdf_page, row.view) for row in self.floors}) != len(self.floors):
            raise ValueError("Виды пилота должны различаться")
        if set(self.sources) != set(SOURCE_ROLES) or len(set(self.sources.values())) != 4:
            raise ValueError("Нужны четыре разных источника")
        if any(
            not path.startswith("/") or not path.endswith(".md") for path in self.sources.values()
        ):
            raise ValueError("Укажите абсолютные пути к Markdown на kg_claude")
        return self


class SourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: SourceRole
    applicability: Literal["applicable", "no_relevant_requirement", "unclear"]
    reference: str = Field(min_length=1, max_length=400)
    observation: str = Field(min_length=1, max_length=1000)


class OutlineFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: Literal["blocking", "major", "minor"]
    location: str = Field(min_length=1, max_length=400)
    observation: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=1000)
    suggested_fix: str = Field(min_length=1, max_length=1000)


class OutlineReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["ready_for_human_review", "needs_correction", "insufficient_evidence"]
    sources: list[SourceEvidence] = Field(min_length=4, max_length=4)
    findings: list[OutlineFinding] = Field(max_length=25)
    limitations: list[str] = Field(max_length=12)

    @model_validator(mode="after")
    def verify_verdict(self) -> "OutlineReport":
        if {row.role for row in self.sources} != set(SOURCE_ROLES):
            raise ValueError("Нужна оценка каждого из четырёх источников")
        if self.verdict == "ready_for_human_review" and any(
            row.priority != "minor" for row in self.findings
        ):
            raise ValueError("Существенные замечания требуют исправления")
        if self.verdict == "needs_correction" and not self.findings:
            raise ValueError("Нужны замечания с местами исправления")
        return self


class OutlineReviewResult(BaseModel):
    walls_job_id: UUID
    walls_attempt: int
    revision_id: UUID
    section: int
    building: int
    floor: int
    pdf_page: int
    view: int
    input_sha256: str
    walls_sha256: str
    dxf_sha256: str
    generator: str
    zones_count: int
    sources: dict[SourceRole, dict[str, str]]
    report: OutlineReport


class OutlineReviewRead(BaseModel):
    job_id: UUID
    status: JobStatus
    error_message: str | None
    result: OutlineReviewResult | None = None


class OutlineReviewState(BaseModel):
    available: bool
    reviews: list[OutlineReviewRead]
