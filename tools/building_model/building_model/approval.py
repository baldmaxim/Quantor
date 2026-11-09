"""Подтверждение человеком: акт `quantor.model_approval.v1`.

Подтверждение — решение человека, что масштаб листа и модель листа приняты. Ни код, ни тесты не
создают подтверждений на реальных данных: команду `approve` запускает человек с собственным именем.
Файл привязан к конкретному файлу модели хешем его байтов: изменилась модель — подтверждение
недействительно.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from building_model.canonical import BuildingModel
from building_model.reader import Excluded, load_document, read_sheet

APPROVAL_SCHEMA = "quantor.model_approval.v1"
# Единственный блокер модели, который человек может принять явно (флаг --accept-noise).
NOISE_BLOCKER = "openings_noise"


class ApprovalOut(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_id: Literal["quantor.model_approval.v1"] = Field(
        default="quantor.model_approval.v1", alias="schema"
    )
    page: int
    model_sha256: str
    mm_per_pt: float
    by: str
    at: str
    note: str | None = None
    # Блокеры модели, которые человек принял явно; сейчас допустим только `openings_noise`.
    accepted_blockers: list[str] = []

    @field_validator("accepted_blockers")
    @classmethod
    def _only_noise_sorted(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - {NOISE_BLOCKER})
        if unknown:
            raise ValueError(f"принять можно только {NOISE_BLOCKER}, не {', '.join(unknown)}")
        return sorted(set(value))


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_approval(
    input_path: Path,
    model_path: Path,
    page: int,
    by: str,
    note: str | None = None,
    now: str | None = None,
    accept_noise: bool = False,
) -> ApprovalOut:
    """Собирает акт. Проверяет, что модель относится к этой странице и что у листа есть масштаб.

    Шумный лист (блокер `openings_noise`) подтверждается только с `accept_noise`.
    """
    name = by.strip()
    if not name:
        raise ValueError("--by: имя подтверждающего не может быть пустым")
    sheet = read_sheet(load_document(input_path), page)
    if isinstance(sheet, Excluded):
        raise ValueError(f"страница {page} не лист-план ({sheet.reason}): подтверждать нечего")
    mm_per_pt = sheet.scale.mm_per_pt
    if mm_per_pt is None:
        raise ValueError(f"у страницы {page} нет масштаба: подтверждать нечего")
    raw = model_path.read_bytes()
    model = BuildingModel.model_validate_json(raw)
    sheet_stats = model.stats.get("sheet")
    model_page = sheet_stats.get("page") if isinstance(sheet_stats, dict) else None
    if model_page != page:
        raise ValueError(f"модель построена для другой страницы, не для {page}")
    noisy = any(i.code == NOISE_BLOCKER and i.severity == "blocker" for i in model.review.items)
    if noisy and not accept_noise:
        raise ValueError(
            f"у страницы {page} блокер {NOISE_BLOCKER} (шумный лист): сначала проверьте разметку, "
            "затем подтвердите с флагом --accept-noise"
        )
    return ApprovalOut(
        page=page,
        model_sha256=hashlib.sha256(raw).hexdigest(),
        mm_per_pt=mm_per_pt,
        by=name,
        at=now if now is not None else utc_now_iso(),
        note=note,
        accepted_blockers=[NOISE_BLOCKER] if noisy and accept_noise else [],
    )


def dumps_approval(approval: ApprovalOut) -> str:
    data = approval.model_dump(mode="json", by_alias=True)
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def load_approval(path: Path) -> ApprovalOut:
    return ApprovalOut.model_validate_json(path.read_text(encoding="utf-8"))
