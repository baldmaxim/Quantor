"""Общие типы контрактов MEP: идентификаторы, листы, уровни, ссылки на профиль, замечания."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION: Final = "0.3.0"

# Координаты листа нормализованы от левого верхнего угла повёрнутой страницы (ADR-0008).
Unit = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NormPoint = tuple[Unit, Unit]

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:\-]+$")]
# Ключ из профиля системы: `класс`, `атрибут`, `тип связи`. Ядро значения не толкует.
ProfileKey = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[a-z0-9._\-]+$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
Millimetres = Annotated[float, Field(allow_inf_nan=False)]

ScalarValue = bool | int | float | str


Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


class ContractModel(BaseModel):
    """Контракт неизменяем и не принимает неизвестных полей: опечатка — ошибка, а не молчание."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def canonical_sha256(model: BaseModel) -> str:
    """Хеш контракта, не зависящий от порядка ключей. Им фиксируются вход и выход."""
    payload = json.dumps(
        model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ScaleStatus(StrEnum):
    """Есть ли у листа явная калибровка. Автоматического масштаба нет (ADR-0018)."""

    CALIBRATED = "calibrated"
    UNCALIBRATED = "uncalibrated"


class SubjectKind(StrEnum):
    """Вид объекта, на который ссылается контракт. Только понятия ядра, без дисциплины."""

    EVIDENCE_ELEMENT = "evidence_element"
    EVIDENCE_RELATION = "evidence_relation"
    INFERENCE_STEP = "inference_step"
    SYSTEM = "system"
    NODE = "node"
    PORT = "port"
    SEGMENT = "segment"
    UNRESOLVED_DECISION = "unresolved_decision"
    SHEET = "sheet"
    LEVEL = "level"
    TOOL = "tool"
    CORPUS = "corpus"


class SubjectRef(ContractModel):
    """Типизированная ссылка: `{"kind": "segment", "id": "seg-b1"}`. Голый id неоднозначен."""

    kind: SubjectKind
    id: Identifier


class ProfileRef(ContractModel):
    """Профиль системы, по которому толкуются ключи графа."""

    profile_id: Identifier
    profile_version: Annotated[str, Field(min_length=1, max_length=32)]
    # `canonical_sha256` профиля. Версия — имя, хеш — содержание: правка без новой версии видна.
    profile_sha256: Sha256 | None = None


class DocumentRef(ContractModel):
    """Исходный документ Quantor. Хеши — неизменяемый вход, а не копия."""

    project_id: Identifier
    revision_id: Identifier
    source_pdf_sha256: Sha256
    package_sha256: Sha256 | None = None


class Level(ContractModel):
    """Уровень здания. Отметка может быть неизвестна — тогда она `None`, а не ноль."""

    level_id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=128)]
    elevation_mm: Millimetres | None = None


class CalibrationSnapshot(ContractModel):
    """Неизменяемый снимок калибровки и геометрии страницы, по которому считаются метры.

    Копия значений, а не только ссылка: граф должен считаться одинаково и после того, как в
    портале появится новая калибровка листа (ADR-0018 — калибровка не правится, а заменяется).
    """

    calibration_id: Identifier
    page_geometry_fingerprint: Sha256
    display_width_pt: Positive
    display_height_pt: Positive
    mm_per_pt: Positive
    verification_state: Literal["unverified", "verified", "disputed"]
    fingerprint: Sha256


def calibration_fingerprint(snapshot: CalibrationSnapshot) -> str:
    """Отпечаток снимка по нормализованным десятичным значениям: `595.2760` и `595.276` — одно."""
    parts = [
        snapshot.calibration_id,
        snapshot.page_geometry_fingerprint,
        f"{snapshot.display_width_pt.normalize():f}",
        f"{snapshot.display_height_pt.normalize():f}",
        f"{snapshot.mm_per_pt.normalize():f}",
        snapshot.verification_state,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class SheetRef(ContractModel):
    """Лист, на котором лежит геометрия, и основание для метрики."""

    sheet_id: Identifier
    page_index: Annotated[int, Field(ge=0)]
    geometry_fingerprint: Sha256
    level_id: Identifier | None = None
    scale_status: ScaleStatus = ScaleStatus.UNCALIBRATED
    scale_calibration_id: Identifier | None = None
    # Обязателен при `calibrated`: без снимка метры нельзя воспроизвести.
    calibration: CalibrationSnapshot | None = None


class Tool(ContractModel):
    """Экстрактор, генератор или правило с версией и хешами — происхождение без догадок."""

    tool_id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=128)]
    version: Annotated[str, Field(min_length=1, max_length=64)]
    model_id: str | None = None
    weights_sha256: Sha256 | None = None
    config_sha256: Sha256 | None = None
    # Источник правила или норматива, если это правило.
    rule_source: str | None = None


class Attribute(ContractModel):
    """Атрибут из профиля. Отсутствие значения — `None` со статусом, а не пустая строка."""

    key: ProfileKey
    value: ScalarValue | None
    unit: str | None = None


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ContractIssue:
    """Замечание проверки. `error` — граф не принимается, `warning` — принимается с оговоркой."""

    code: str
    severity: IssueSeverity
    subject_id: str | None
    message: str


def issue(
    code: str, subject_id: str | None, message: str, *, warning: bool = False
) -> ContractIssue:
    severity = IssueSeverity.WARNING if warning else IssueSeverity.ERROR
    return ContractIssue(code, severity, subject_id, message)


GeometryKind = Literal["point", "bbox", "polyline", "polygon"]
