"""Контракты PDF -> CAD (QA-контур). Ключи хранилища и пути файловой системы наружу не отдаются."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain import JobStatus
from app.models import Job
from app.services import cad as cad_service
from app.services import cad_progress


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class CadConvertCreate(BaseModel):
    """Постановка. `pages` — page_index с 0 (как у листов Quantor), null — все плановые листы."""

    model_config = ConfigDict(extra="forbid")

    pages: list[Annotated[int, Field(ge=0)]] | None = None
    finishes: bool = False
    schedules: bool = False


class CadArtifactRead(BaseModel):
    name: str
    sha256: str
    size: int


class CadViewRead(BaseModel):
    view: int
    status: str
    scale_status: str | None
    dxf: str | None
    dxf_entities: int | None


class CadPageRead(BaseModel):
    index: int
    legacy_pdf_page: int
    views: list[CadViewRead]


# ------------------------------------------------------------------ ход попытки


class CadStageRead(BaseModel):
    """Этап вида, как его записал движок. Ключ — один из семи этапов штатного worker."""

    key: Literal["source", "regions", "scale", "geometry", "assemblies", "checks", "export"]
    status: str
    elapsed_s: float | None
    completed: int | None
    total: int | None
    detail: str | None


class CadProgressViewRead(BaseModel):
    page_index: int
    legacy_pdf_page: int
    view: int
    status: str
    stage: str
    ready: bool
    stages: list[CadStageRead]


class CadEngineStateRead(BaseModel):
    status: str
    stage: str
    error: str | None


class CadPagesPlanRead(BaseModel):
    """Страницы PDF по входному контролю движка: всего, плановые, взятые в работу (с 0)."""

    total: int | None
    planned: list[int]
    requested: list[int]


class CadAttemptRead(BaseModel):
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    outcome: Literal["running", "succeeded", "failed", "lost"]
    error_code: str | None
    result_status: str | None
    phase: str | None
    phase_detail: str | None
    pages: CadPagesPlanRead | None
    engine: CadEngineStateRead | None
    views: list[CadProgressViewRead]
    event_count: int
    events_dropped: int
    last_seq: int

    @classmethod
    def of(cls, job: Job, record: dict[str, Any]) -> CadAttemptRead:
        attempt = int(record["attempt"])
        snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else None
        live = job.status is JobStatus.RUNNING and job.attempt == attempt
        outcome: Literal["running", "succeeded", "failed", "lost"]
        error_code = record.get("error_code")
        if record.get("outcome") == "succeeded":
            outcome = "succeeded"
        elif record.get("outcome") == "failed":
            outcome = "failed"
        elif live:
            outcome = "running"
        else:
            # Попытка без итога и без аренды: исполнитель пропал (release_expired).
            outcome = "lost"
            if job.attempt == attempt and job.error_code:
                error_code = job.error_code
            error_code = error_code or "JOB_LEASE_LOST"
        events = _as_list(record.get("events"))
        last_event = events[-1] if events else None
        return cls(
            attempt=attempt,
            started_at=record.get("started_at"),
            finished_at=record.get("finished_at"),
            outcome=outcome,
            error_code=error_code,
            result_status=record.get("result_status"),
            phase=(last_event or {}).get("phase") if last_event else None,
            phase_detail=snapshot.get("phase_detail") if snapshot else None,
            pages=CadPagesPlanRead.model_validate(snapshot["pages"])
            if snapshot and snapshot.get("pages")
            else None,
            engine=CadEngineStateRead.model_validate(snapshot["engine"])
            if snapshot and snapshot.get("engine")
            else None,
            views=[
                CadProgressViewRead(
                    page_index=view["index"],
                    legacy_pdf_page=view["legacy_pdf_page"],
                    view=view["view"],
                    status=view["status"],
                    stage=view["stage"],
                    ready=view["ready"],
                    stages=[CadStageRead.model_validate(stage) for stage in view["stages"]],
                )
                for view in (snapshot or {}).get("views", [])
            ],
            event_count=len(events),
            events_dropped=int(record.get("events_dropped", 0)),
            last_seq=int(record.get("last_seq", 0)),
        )


class CadEventRead(BaseModel):
    seq: int
    at: datetime
    attempt: int
    scope: Literal["document", "view"]
    phase: str | None = None
    page_index: int | None = None
    legacy_pdf_page: int | None = None
    view: int | None = None
    stage: str | None = None
    status: str
    detail: str | None = None
    elapsed_s: float | None = None
    completed: int | None = None
    total: int | None = None


class CadEventsRead(BaseModel):
    job_id: UUID
    attempt: int
    events: list[CadEventRead]
    last_seq: int
    finished: bool


# ------------------------------------------------------------------ задание


def _requested_pages(job: Job) -> list[int] | None:
    params = job.payload.get("params")
    pages = params.get("pages") if isinstance(params, dict) else None
    return [int(p) for p in pages] if isinstance(pages, list) else None


class CadJobSummaryRead(BaseModel):
    job_id: UUID
    status: JobStatus
    attempt: int
    created_at: datetime
    finished_at: datetime | None
    requested_pages: list[int] | None
    result_status: str | None
    error_code: str | None


class CadJobListRead(BaseModel):
    items: list[CadJobSummaryRead]
    server_time: datetime


class CadJobRead(BaseModel):
    job_id: UUID
    revision_id: UUID
    status: JobStatus
    stage: str | None
    attempt: int
    error_code: str | None
    error_message: str | None
    engine_version: str
    result_status: str | None
    review_required: bool
    known_limitation: str | None
    pages: list[CadPageRead]
    artifacts: list[CadArtifactRead]
    # --- ход и история (интерфейс QA-контура) ---
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    server_time: datetime
    requested_pages: list[int] | None
    # Попытка, к которой относятся pages/artifacts/result_status; null — у текущей итога нет.
    result_attempt: int | None
    attempts: list[CadAttemptRead]
    retryable: bool
    retry_blocked_reason: str | None

    @classmethod
    def of(cls, job: Job) -> CadJobRead:
        # Только итог текущей попытки: прошлый результат текущим не выдаётся.
        result: dict[str, Any] = cad_service.current_result(job)
        retryable, reason = cad_service.retry_state(job)
        return cls(
            job_id=job.id,
            revision_id=UUID(str(job.payload["revision_id"])),
            status=job.status,
            stage=job.stage,
            attempt=job.attempt,
            error_code=job.error_code,
            error_message=job.error_message,
            engine_version=str(job.payload.get("engine_version", "")),
            result_status=result.get("result_status"),
            # Любой результат движка — кандидат: проверка инженером обязательна всегда.
            review_required=True,
            known_limitation=result.get("known_limitation"),
            pages=[CadPageRead.model_validate(page) for page in result.get("pages", [])],
            artifacts=[
                CadArtifactRead(name=row["name"], sha256=row["sha256"], size=row["size"])
                for row in result.get("artifacts", [])
            ],
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            server_time=datetime.now(UTC),
            requested_pages=_requested_pages(job),
            result_attempt=result.get("attempt") if result else None,
            attempts=[CadAttemptRead.of(job, row) for row in cad_progress.attempts_of(job.payload)],
            retryable=retryable,
            retry_blocked_reason=reason,
        )


def summary_of(job: Job) -> CadJobSummaryRead:
    result = cad_service.current_result(job)
    return CadJobSummaryRead(
        job_id=job.id,
        status=job.status,
        attempt=job.attempt,
        created_at=job.created_at,
        finished_at=job.finished_at,
        requested_pages=_requested_pages(job),
        result_status=result.get("result_status"),
        error_code=job.error_code,
    )


# ------------------------------------------------------------------ вид: диагностика и просмотр


class CadScaleControlRead(BaseModel):
    chain_id: int | None
    role: str
    label_mm: float | None
    length_pt: float | None
    fitted_measured_mm: float | None
    residual_mm: float | None
    tolerance_mm: float | None
    within_tolerance: bool | None
    axis_angle_deg: float | None
    endpoints_pt: list[tuple[float, float]]


class CadScaleRead(BaseModel):
    """Проверка масштаба движком: подбор по размерным цепочкам и независимая проверка."""

    status: str
    passed: bool
    method: str | None
    mm_per_pdf_point: float | None
    scale_denominator: float | None
    printed_scale_labels: list[float]
    printed_scale_consistent: bool | None
    fit_controls: int
    heldout_controls: int
    fit_chains: int | None
    heldout_chains: int | None
    fit_and_holdout_chains_disjoint: bool | None
    independent_axes: bool | None
    anchored_conflicts: int
    unassociated_numeric_labels: int
    release_allowed: bool
    controls: list[CadScaleControlRead]
    # Причины, по которым масштаб не подтверждён (HOLD). Пусто — подтверждён проверкой.
    hold_reasons: list[str]
    context_crop_pt: list[float] | None


class CadFrameRead(BaseModel):
    """Кадр координат DXF (мм) -> PDF (pt от левого верхнего угла страницы).

    `pt = origin_pt + (x_mm, -y_mm) / mm_per_pdf_point`. Подтверждён, только если масштаб
    прошёл размерную проверку и движок указал начало координат DXF на странице.
    """

    confirmed: bool
    reason: str | None
    units: str | None
    origin_pt: tuple[float, float] | None
    mm_per_pdf_point: float | None


class CadChecksRead(BaseModel):
    audit_errors: int | None
    layers: dict[str, int]
    door_block_inserts: int | None
    gate_block_inserts: int | None
    source_fill_count: int | None
    recognized_monolith_fill_count: int | None
    door_block_count: int | None
    rooms_schedule_rows: int | None
    rooms_recognized_rows: int | None
    region_approved: bool | None
    all_source_fills_valid: bool | None
    quantity_release_allowed: bool


class CadViewDiagnosticsRead(BaseModel):
    job_id: UUID
    attempt: int
    page_index: int
    legacy_pdf_page: int
    view: int
    status: str
    scale_status: str | None
    result_status: str | None
    files: list[CadArtifactRead]
    dxf: CadArtifactRead | None
    preview_available: bool
    scale: CadScaleRead | None
    frame: CadFrameRead
    checks: CadChecksRead | None
    review_required: bool
    # Инженерная приёмка в QA-контуре не выполняется никогда: это отдельный шаг человека.
    engineering_acceptance: Literal["not_accepted"]


class CadPreviewPathRead(BaseModel):
    layer: int
    closed: bool
    fill: bool
    # Плоский список x0, y0, x1, y1, … в мм системы DXF.
    points: list[float]


class CadPreviewRead(BaseModel):
    job_id: UUID
    attempt: int
    page_index: int
    view: int
    units: Literal["mm"]
    dxf_sha256: str
    layers: list[str]
    paths: list[CadPreviewPathRead]
    point_count: int
    truncated: bool
    flatten_mm: float
    bbox: tuple[float, float, float, float] | None
    frame: CadFrameRead


# ------------------------------------------------------------------ замечания проверяющего

REMARKS_SCHEMA = "quantor.cad-remarks.v1"
REMARKS_COORDINATE_SYSTEM = "pdf_pt_top_left"
MAX_REMARKS_PER_FILE = 500
MAX_COMMENT_LENGTH = 4000
MAX_REVIEWER_LENGTH = 200

# Те же значения, что `REMARK_TYPES` в apps/web/src/lib/cad/remarks.ts и CHECK таблицы.
CadRemarkType = Literal[
    "missing_wall",
    "false_wall",
    "missing_door",
    "door_geometry",
    "missing_gate",
    "missing_glazing",
    "monolith",
    "room_boundary",
    "wrong_class",
    "other",
]
CadRemarkStatus = Literal["open", "resolved"]
# Прямоугольник в pt PDF от левого верхнего угла страницы: x0, y0, x1, y1.
CadBboxPt = tuple[float, float, float, float]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _check_bbox(value: CadBboxPt) -> CadBboxPt:
    x0, y0, x1, y1 = value
    if not all(math.isfinite(item) for item in value) or x0 < 0 or y0 < 0 or x1 <= x0 or y1 <= y0:
        raise ValueError("нужны конечные x0 >= 0, y0 >= 0, x1 > x0, y1 > y0")
    return value


def _utc(value: datetime) -> datetime:
    """Время без пояса считается UTC: файл обмена пишет ISO с `Z`, но разбор не должен падать."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class CadRemarkWrite(BaseModel):
    """Создание или изменение замечания: время и автора выставляет сервер."""

    model_config = ConfigDict(extra="forbid")

    type: CadRemarkType
    comment: str = Field(max_length=MAX_COMMENT_LENGTH)
    reviewer: str = Field(default="", max_length=MAX_REVIEWER_LENGTH)
    status: CadRemarkStatus
    bbox_pt: CadBboxPt
    dxf_sha256: Sha256Hex | None = None

    _bbox = field_validator("bbox_pt")(_check_bbox)


class CadRemarkRead(BaseModel):
    """Замечание в том же виде, что `IRemark` интерфейса: `id` — клиентский ключ."""

    id: str
    type: CadRemarkType
    comment: str
    reviewer: str
    status: CadRemarkStatus
    bbox_pt: CadBboxPt
    created_at: datetime
    updated_at: datetime


class CadRemarkFileItem(BaseModel):
    """Замечание в файле обмена; лишние поля игнорируются, как у разбора файла в интерфейсе."""

    id: str = Field(min_length=1, max_length=64)
    type: CadRemarkType
    comment: str = Field(max_length=MAX_COMMENT_LENGTH)
    reviewer: str = Field(default="", max_length=MAX_REVIEWER_LENGTH)
    status: CadRemarkStatus
    bbox_pt: CadBboxPt
    created_at: datetime
    updated_at: datetime

    _bbox = field_validator("bbox_pt")(_check_bbox)
    _created = field_validator("created_at")(_utc)
    _updated = field_validator("updated_at")(_utc)


class CadRemarksFile(BaseModel):
    """Файл `quantor.cad-remarks.v1`. Формат тот же, что строит и разбирает интерфейс."""

    model_config = ConfigDict(populate_by_name=True)

    file_schema: Literal["quantor.cad-remarks.v1"] = Field(alias="schema")
    project_id: str
    revision_id: str
    job_id: str
    attempt: int
    page_index: Annotated[int, Field(ge=0)]
    legacy_pdf_page: int
    view: Annotated[int, Field(ge=0)]
    dxf_sha256: str | None
    coordinate_system: Literal["pdf_pt_top_left"]
    exported_at: datetime
    reviewer: str = Field(max_length=MAX_REVIEWER_LENGTH)
    engineering_acceptance: Literal[False]
    remarks: list[CadRemarkFileItem] = Field(max_length=MAX_REMARKS_PER_FILE)


class CadRemarksImportRead(BaseModel):
    imported: int
    updated: int
