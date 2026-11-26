"""Вход пилота и отчёт ИИ-проверки вида обводки (модель Claude через Claude CLI на kg_claude)."""

import math
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.contracts.cad import CadRemarkType
from app.domain import JobStatus

AiRole = Literal["corrector", "verifier"]
AI_ROLES = ("corrector", "verifier")
# Роли версий промтов: две роли проверки вида и сопоставление ВОР. Старт проверки вида - `AiRole`.
AiPromptRole = Literal["corrector", "verifier", "vor_mapper", "style"]
# Роль задания `cad_ai_review`: `style` - оформление (классы подписей штриховки, до конструкций);
# ручной старт и результат проверки вида (`AiReviewStart`, `AiReviewResult`) берут только `AiRole`.
AiJobRole = Literal["corrector", "verifier", "style"]
Priority = Literal["blocking", "major", "minor"]

_SOURCE_KEY = re.compile(r"^[a-z_]{2,32}$")


class AiLoopPilot(BaseModel):
    """Пилот: проект, модель и источники (абсолютные пути `.md` на kg_claude)."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    model: str = Field(
        default="claude-opus-5-5", min_length=1, max_length=64, pattern=r"^[a-z0-9.-]+$"
    )
    max_iterations: int = Field(default=3, ge=1, le=5)
    sources: dict[str, str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def verify_sources(self) -> "AiLoopPilot":
        if any(not _SOURCE_KEY.fullmatch(role) for role in self.sources):
            raise ValueError("Ключ источника: строчные латинские буквы и «_», 2-32 символа")
        if any(
            not path.startswith("/") or not path.endswith(".md") for path in self.sources.values()
        ):
            raise ValueError("Укажите абсолютные пути к Markdown на kg_claude")
        return self


def _check_bbox_px(value: list[float]) -> list[float]:
    x0, y0, x1, y1 = value
    if not all(math.isfinite(item) for item in value) or x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
        raise ValueError("нужны конечные x0 >= 0, y0 >= 0, x1 > x0, y1 > y0")
    return value


BboxPx = Annotated[list[float], Field(min_length=4, max_length=4), AfterValidator(_check_bbox_px)]


class AiFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: CadRemarkType
    priority: Priority
    # Прямоугольник в пикселях plan.png от левого верхнего угла: x0, y0, x1, y1.
    bbox_px: BboxPx
    construction_ids: list[str] = Field(max_length=20)
    observation: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=1000)
    suggested_fix: str = Field(min_length=1, max_length=1000)


class AiPropSuggestion(BaseModel):
    """Предложение правки свойств конструкции: только хранится и показывается, не применяется."""

    model_config = ConfigDict(extra="forbid")

    construction_id: str = Field(min_length=1, max_length=100)
    material: str | None = Field(default=None, max_length=200)
    thickness_mm: float | None = Field(default=None, gt=0, le=2000)
    height_mm: float | None = Field(default=None, gt=0, le=20000)
    count_openings: bool | None = None
    evidence: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def verify_change(self) -> "AiPropSuggestion":
        if (
            self.material is None
            and self.thickness_mm is None
            and self.height_mm is None
            and self.count_openings is None
        ):
            raise ValueError("Нужно задать хотя бы одно свойство для правки")
        return self


class AiVorCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vor_ref: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=400)
    status: Literal["found", "absent_on_view", "not_applicable", "unclear"]
    construction_ids: list[str] = Field(max_length=50)
    note: str = Field(max_length=1000)


SlabFindingKind = Literal[
    "slab_missing_area",
    "slab_missing_hole",
    "slab_false_hole",
    "slab_terrace_balcony",
    "slab_level_drop",
]

OpeningClassKind = Literal[
    "window",
    "balcony_door",
    "entry_door",
    "fire_door",
    "lift_door",
    "interior_door",
    "gate",
    "false_gap",
]

FacadeSide = Literal["north", "south", "east", "west", "court", "unknown"]


class AiLevelSuggestion(BaseModel):
    """Предложение по высотам/уровням этажа со ссылкой на разрез/КР/ПЗ (кандидат до приёмки)."""

    model_config = ConfigDict(extra="forbid")

    floor_elevation_mm: int | None = Field(
        default=None,
        ge=-50_000,
        le=500_000,
        description="Отметка чистого пола этажа от +-0.000, мм",
    )
    floor_height_mm: int | None = Field(
        default=None,
        ge=1_500,
        le=20_000,
        description="Высота этажа от чистого пола до чистого пола выше, мм",
    )
    slab_thickness_mm: int | None = Field(
        default=None,
        ge=100,
        le=1_000,
        description="Толщина монолитной плиты перекрытия, мм",
    )
    floor_finish_mm: int | None = Field(
        default=None,
        ge=0,
        le=1_000,
        description="Толщина пирога пола (чистый пол минус верх плиты), мм",
    )
    door_height_mm: int | None = Field(
        default=None,
        ge=1_500,
        le=5_000,
        description="Типовая высота дверного проёма от чистого пола, мм",
    )
    window_sill_mm: int | None = Field(
        default=None,
        ge=0,
        le=5_000,
        description="Высота подоконника ОТ ЧИСТОГО ПОЛА этажа (не абсолютная отметка), мм",
    )
    window_head_mm: int | None = Field(
        default=None,
        ge=500,
        le=10_000,
        description="Высота верха окна ОТ ЧИСТОГО ПОЛА этажа (не абсолютная отметка), мм",
    )
    source_ref: str = Field(min_length=1, max_length=200)
    evidence: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def verify_levels(self) -> "AiLevelSuggestion":
        values = (
            self.floor_elevation_mm,
            self.floor_height_mm,
            self.slab_thickness_mm,
            self.floor_finish_mm,
            self.door_height_mm,
            self.window_sill_mm,
            self.window_head_mm,
        )
        if all(value is None for value in values):
            raise ValueError("Нужно задать хотя бы один высотный параметр")
        if (
            self.window_sill_mm is not None
            and self.window_head_mm is not None
            and self.window_head_mm <= self.window_sill_mm
        ):
            raise ValueError("window_head_mm должен быть больше window_sill_mm")
        return self


class AiSlabFinding(BaseModel):
    """Находка по плите перекрытия, отверстиям (лифты/ЛК/шахты) и балконам/террасам."""

    model_config = ConfigDict(extra="forbid")

    kind: SlabFindingKind
    priority: Priority
    bbox_px: BboxPx
    hole_id: str | None = Field(default=None, max_length=64)
    elevation_mm: int | None = Field(default=None, ge=-50_000, le=500_000)
    observation: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=1000)
    suggested_fix: str = Field(min_length=1, max_length=1000)


class AiOpeningClassification(BaseModel):
    """Классификация проёма `walls.json` (окно фасада, дверь, противопожарная, ложный разрыв)."""

    model_config = ConfigDict(extra="forbid")

    opening_id: str = Field(min_length=1, max_length=100)
    kind: OpeningClassKind
    facade_side: FacadeSide | None = None
    facade_view_key: str | None = Field(default=None, max_length=64)
    fire_rating: str | None = Field(default=None, max_length=32)
    evidence: str = Field(min_length=1, max_length=1000)


class AiReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["ready_for_human_review", "needs_correction", "insufficient_evidence"]
    findings: list[AiFinding] = Field(max_length=40)
    props: list[AiPropSuggestion] = Field(max_length=60)
    vor_check: list[AiVorCheck] = Field(max_length=80)
    limitations: list[str] = Field(max_length=12)
    # Расширение полноконтекстного аудита (обратно совместимо со старыми прогонами в БД).
    level_suggestions: list[AiLevelSuggestion] = Field(default_factory=list, max_length=12)
    slab_findings: list[AiSlabFinding] = Field(default_factory=list, max_length=40)
    opening_classifications: list[AiOpeningClassification] = Field(
        default_factory=list, max_length=400
    )

    @model_validator(mode="after")
    def verify_verdict(self) -> "AiReviewReport":
        has_actionable = bool(
            self.findings
            or self.props
            or self.slab_findings
            or self.level_suggestions
            or any(row.kind == "false_gap" for row in self.opening_classifications)
        )
        if self.verdict == "needs_correction" and not has_actionable:
            raise ValueError("Нужны находки или правки свойств")
        if self.verdict == "ready_for_human_review" and (
            any(row.priority != "minor" for row in self.findings)
            or any(row.priority != "minor" for row in self.slab_findings)
        ):
            raise ValueError("Существенные находки требуют исправления")
        return self


class AiSourceCopy(BaseModel):
    filename: str
    sha256: str


class AiUsage(BaseModel):
    cost_usd: float | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class AiRender(BaseModel):
    # Участок страницы в pt (от левого верхнего угла), который покрывает plan.png, и масштаб px/pt.
    clip: list[float] = Field(min_length=4, max_length=4)
    zoom: float = Field(gt=0)


class AiReviewResult(BaseModel):
    walls_job_id: UUID
    walls_attempt: int
    cad_job_id: UUID
    revision_id: UUID
    page_index: int
    view: int
    role: AiRole
    iteration: int
    model: str
    input_sha256: str
    walls_sha256: str
    dxf_sha256: str
    # Версия промта из `ai_prompt_versions`; у результатов до версионирования их нет.
    prompt_version_id: UUID | None = None
    prompt_version: int | None = None
    prompt_sha256: str
    bundle_sha256: str
    sources: dict[str, AiSourceCopy]
    usage: AiUsage
    render: AiRender
    remark_keys: list[str]
    report: AiReviewReport


class AiReviewStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: AiRole


class AiReviewRead(BaseModel):
    job_id: UUID
    status: JobStatus
    error_message: str | None
    result: AiReviewResult | None = None


class AiReviewState(BaseModel):
    available: bool
    max_iterations: int
    reviews: list[AiReviewRead]
