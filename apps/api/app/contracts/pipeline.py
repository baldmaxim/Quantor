"""Контракт будущего конвейера обработки.

На Stage 1 реален ровно один тип задания — `legacy_import`. Всё, что ниже, описывает форму
будущих шагов, чтобы их можно было добавлять по одному, не переделывая ни хранение
состояния, ни интерфейс.

Никакой из этих шагов сейчас не исполняется: это типы и правила, а не реализация.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class PipelineStage(StrEnum):
    """Шаги будущего конвейера — от приёма файла до выгрузки результата.

    Порядок не жёсткий: часть шагов выполняется параллельно по листам. Важно другое —
    каждый шаг отдельное задание со своим состоянием, входом и выходом.
    """

    INGEST = "ingest"
    SHEET_PARSE = "sheet_parse"
    OCR_LAYOUT = "ocr_layout"
    VECTOR_EXTRACT = "vector_extract"
    SYMBOL_DETECT = "symbol_detect"
    SEMANTIC_LINK = "semantic_link"
    MEASURE = "measure"
    QUANTITY_CALCULATE = "quantity_calculate"
    VERIFY = "verify"
    EXPORT = "export"


@dataclass(frozen=True, slots=True)
class StageContract:
    """Требования, которым обязан удовлетворять любой шаг конвейера.

    Они выведены не из красоты, а из свойств задачи: обработка длинная, падает по разным
    причинам и должна объяснять свой результат.
    """

    stage: PipelineStage
    # Повтор с тем же входом даёт тот же результат и не создаёт вторую копию объектов.
    idempotent: bool = True
    # Шаг можно перезапустить после сбоя, не откатывая весь конвейер.
    retryable: bool = True
    # Шаг можно прервать по требованию пользователя.
    cancellable: bool = True
    # Шаг возобновляется с последней завершённой части, а не с начала.
    resumable: bool = False
    # Требуется ли обращение к модели: определяет, нужен ли шлюз и куда уходят данные.
    uses_models: bool = False


# Форма будущего конвейера. Таблица нужна, чтобы новый шаг добавляли осознанно,
# а не копированием соседнего.
STAGE_CONTRACTS: dict[PipelineStage, StageContract] = {
    PipelineStage.INGEST: StageContract(PipelineStage.INGEST),
    PipelineStage.SHEET_PARSE: StageContract(PipelineStage.SHEET_PARSE, resumable=True),
    PipelineStage.OCR_LAYOUT: StageContract(
        PipelineStage.OCR_LAYOUT, resumable=True, uses_models=True
    ),
    PipelineStage.VECTOR_EXTRACT: StageContract(PipelineStage.VECTOR_EXTRACT, resumable=True),
    PipelineStage.SYMBOL_DETECT: StageContract(
        PipelineStage.SYMBOL_DETECT, resumable=True, uses_models=True
    ),
    PipelineStage.SEMANTIC_LINK: StageContract(PipelineStage.SEMANTIC_LINK, uses_models=True),
    PipelineStage.MEASURE: StageContract(PipelineStage.MEASURE),
    # Считает детерминированный сервис. Модель никогда не является калькулятором:
    # результат должен воспроизводиться и проверяться, а не угадываться.
    PipelineStage.QUANTITY_CALCULATE: StageContract(
        PipelineStage.QUANTITY_CALCULATE, uses_models=False
    ),
    PipelineStage.VERIFY: StageContract(PipelineStage.VERIFY),
    PipelineStage.EXPORT: StageContract(PipelineStage.EXPORT),
}


@dataclass(frozen=True, slots=True)
class Provenance:
    """Происхождение результата шага.

    Без этих полей результат невозможно объяснить: непонятно, какая версия алгоритма или
    модели его получила и из каких входных артефактов.
    """

    stage: PipelineStage
    input_artifact_ids: tuple[str, ...] = ()
    output_artifact_ids: tuple[str, ...] = ()
    algorithm_version: str | None = None
    model_provider_id: str | None = None
    model_id: str | None = None
    rule_version: str | None = None


@dataclass(frozen=True, slots=True)
class StageProgress:
    """Прогресс по шагу. Проценты считаются от единиц работы, а не выдумываются."""

    stage: PipelineStage
    completed_units: int = 0
    total_units: int = 0
    detail: str | None = None

    @property
    def fraction(self) -> float:
        if self.total_units <= 0:
            return 0.0
        return min(self.completed_units / self.total_units, 1.0)


@dataclass(frozen=True, slots=True)
class PipelineRun:
    """Один прогон конвейера над ревизией документа."""

    revision_id: str
    stages: tuple[PipelineStage, ...] = ()
    provenance: tuple[Provenance, ...] = field(default_factory=tuple)
