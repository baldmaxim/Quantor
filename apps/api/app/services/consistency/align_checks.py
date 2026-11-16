"""Проверка «план ↔ уровень» (ADR-0043, С3): `consistency.checks.align.v1`.

Итог по каждой секции: каждый план с запущенным совмещением совмещён с уровнем и это подтвердил
человек. Подтверждённый итог «проверить» считается принятым человеком. Совмещение без итога
(нет CAD, осей, эталона), с отказом или отклонённое человеком - замечание; кандидаты с итогом
ждут подтверждения - «не проверено». Модуль чистый; результаты считаются при чтении каркаса.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Final

from app.services.consistency.frame_checks import (
    CheckCode,
    CheckRef,
    CheckResult,
    CheckStatus,
    RefKind,
)
from app.services.consistency.plan_alignment import AlignResult

ALIGN_CHECKS_VERSION: Final = "consistency.checks.align.v1"

ALIGN_REFS_MAX: Final = 20
LISTED_MAX: Final = 10
_PLACED: Final = frozenset({AlignResult.REFERENCE, AlignResult.ALIGNED, AlignResult.CHECK})


@dataclass(frozen=True, slots=True)
class AlignmentView:
    """Совмещение вида плана последней ревизии с уровнем."""

    id: str
    building: str | None
    section: str | None
    label: str
    file_name: str
    page_index: int
    result: AlignResult
    status: str  # candidate / confirmed / rejected
    residual_rms_mm: float | None
    reason: str | None


def _scope(building: str | None, section: str | None) -> str:
    parts = [f"корпус {building}" if building else "", f"секция {section}" if section else ""]
    text = ", ".join(part for part in parts if part)
    return text or "корпус и секция не указаны"


def _ref(item: AlignmentView) -> CheckRef:
    return CheckRef(
        kind=RefKind.ALIGNMENT,
        id=item.id,
        label=item.label,
        file_name=item.file_name,
        page_index=item.page_index,
    )


def _problem(item: AlignmentView) -> str:
    if item.status == "rejected":
        return f"{item.label}: совмещение отклонено"
    reason = f" ({item.reason})" if item.reason else ""
    word = "не совмещён" if item.result is AlignResult.FAILED else "не совмещался"
    return f"{item.label}: {word}{reason}"


def _section_check(
    building: str | None, section: str | None, items: list[AlignmentView]
) -> CheckResult:
    problems = [item for item in items if item.status == "rejected" or item.result not in _PLACED]
    pending = [item for item in items if item not in problems and item.status != "confirmed"]
    placed = [item for item in items if item not in problems and item.status == "confirmed"]
    scope = _scope(building, section)
    if problems:
        listed = "; ".join(_problem(item) for item in problems[:LISTED_MAX])
        more = f" и ещё {len(problems) - LISTED_MAX}" if len(problems) > LISTED_MAX else ""
        return CheckResult(
            code=CheckCode.PLANS_ALIGNED,
            status=CheckStatus.MISMATCH,
            message=f"{scope}: планов без совмещения - {len(problems)}: {listed}{more}.",
            building=building,
            section=section,
            refs=tuple(_ref(item) for item in problems[:ALIGN_REFS_MAX]),
        )
    if pending:
        return CheckResult(
            code=CheckCode.PLANS_ALIGNED,
            status=CheckStatus.NOT_RUN,
            message=(
                f"{scope}: совмещений ждут подтверждения - {len(pending)}, "
                f"подтверждено - {len(placed)}."
            ),
            building=building,
            section=section,
            refs=tuple(_ref(item) for item in pending[:ALIGN_REFS_MAX]),
        )
    residuals = [item.residual_rms_mm for item in placed if item.residual_rms_mm is not None]
    worst = f", невязка до {max(residuals):.0f} мм" if residuals else ""
    return CheckResult(
        code=CheckCode.PLANS_ALIGNED,
        status=CheckStatus.MATCH,
        message=f"{scope}: совмещено планов - {len(placed)}{worst}.",
        building=building,
        section=section,
    )


def run_align_checks(alignments: list[AlignmentView]) -> list[CheckResult]:
    """По итогу на секцию; совмещение не запускалось - один итог «не проверено» с причиной."""
    if not alignments:
        return [
            CheckResult(
                code=CheckCode.PLANS_ALIGNED,
                status=CheckStatus.NOT_RUN,
                message=(
                    "Совмещение планов не запускалось или подтверждённых планов этажей нет: "
                    "запустите совмещение планов."
                ),
            )
        ]
    groups: dict[tuple[str | None, str | None], list[AlignmentView]] = defaultdict(list)
    for item in alignments:
        groups[(item.building, item.section)].append(item)

    def order(key: tuple[str | None, str | None]) -> tuple[str, str]:
        return (key[0] or "", key[1] or "")

    return [_section_check(b, s, groups[(b, s)]) for b, s in sorted(groups, key=order)]
