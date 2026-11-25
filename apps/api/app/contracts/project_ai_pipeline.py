"""Этапы ИИ-проверки проекта (S3-A): прогон чертежей, проверка Claude, верификация, приёмка.

Только чтение сводки и запуск этапов проверки. Числа находок и расход - счётчики заданий, а не
физические величины.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

AiVerdict = Literal["ready_for_human_review", "needs_correction", "insufficient_evidence"]
AiStageStatus = Literal["not_started", "running", "done", "attention"]
# `attention` - вердикт или круги требуют решения человека; `not_started` - ждёт запуска.
AiStageState = Literal["not_started", "running", "ok", "attention", "failed"]
AiRunnableStage = Literal["review", "verify"]


class AiStageSummary(BaseModel):
    """Сводка этапа по проекту: `total` - листов (видов), которые могут пройти этап."""

    stage: int
    title: str
    total: int
    done: int
    running: int
    failed: int
    needs_human: int
    status: AiStageStatus
    # Расход Claude (этапы 2-3): сумма по заданиям; `null` - расход нигде не записан.
    cost_usd: float | None = None
    duration_ms: int | None = None


class AiSheetStage1(BaseModel):
    state: AiStageState
    error_message: str | None = None


class AiSheetStyle(BaseModel):
    """Оформление вида (роль Claude «оформление»): классы подписей штриховки и их применение.

    Только счётчики: найденные классы и регионы, которые взял движок. Площади и объёмы - не здесь.
    """

    state: AiStageState
    # Классов подписей, оставшихся после проверки ответа; `None` - ответа ещё нет.
    classes_found: int | None = None
    # Регионов страницы, взятых движком по классам в последнем преобразовании; `None` - нет отчёта.
    regions_applied: int | None = None
    error_message: str | None = None


class AiSheetStage2(BaseModel):
    state: AiStageState
    rounds_done: int
    rounds_max: int
    # Круги исчерпаны: новая проверка (любой роли) на этом виде не ставится.
    exhausted: bool
    last_verdict: AiVerdict | None = None
    # Вердикт дан по другой попытке конструкций: после перестроения нужен новый круг.
    verdict_stale: bool = False
    last_findings: int | None = None
    running: bool = False
    error_message: str | None = None


class AiSheetStage3(BaseModel):
    state: AiStageState
    claude_verdict: AiVerdict | None = None
    claude_running: bool = False
    codex_available: bool = False
    codex_verdict: AiVerdict | None = None
    codex_running: bool = False
    error_message: str | None = None


class AiSheetStage4(BaseModel):
    open_remarks: int
    approved: bool


class ProjectAiSheetRow(BaseModel):
    document_name: str
    revision_id: UUID
    page_index: int
    # Позиция листа в ревизии (с 1) - для адреса рабочей области.
    sheet_position: int
    sheet_title: str | None
    convert_job_id: UUID | None
    view: int | None
    walls_job_id: UUID | None
    # Для вида есть успешные конструкции и проект - пилот ИИ-проверки.
    review_available: bool
    stage1: AiSheetStage1
    # Оформление перед проверкой Claude; `None` - у вида его нет (не пилот или не план).
    style: AiSheetStyle | None = None
    stage2: AiSheetStage2 | None = None
    stage3: AiSheetStage3 | None = None
    stage4: AiSheetStage4 | None = None


class ProjectAiPipelineRead(BaseModel):
    server_time: datetime
    # Проект - пилот ИИ-проверки (`cad_ai_loop`): без него этапы 2-3 не запускаются.
    available: bool
    max_iterations: int
    # Хотя бы у одного вида доступна проверка Codex.
    codex_available: bool
    # Идёт хотя бы одно задание этапов: интерфейс опрашивает, пока `true`.
    active: bool
    stages: list[AiStageSummary]
    sheets: list[ProjectAiSheetRow]


class AiRunSkip(BaseModel):
    page_index: int
    view: int | None
    document_name: str
    reason: str


class AiRunResult(BaseModel):
    queued: int
    skipped: list[AiRunSkip]
