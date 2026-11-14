"""Каркас здания (ADR-0043, этап С2): сборка из паспортов, правка человеком, проверки.

Сборка берёт только подтверждённые паспорта листов последних ревизий PDF проекта. Пересборка
обновляет узлы-кандидаты, но не трогает подтверждённые и отклонённые узлы и поля, правленные
человеком; кандидат из паспортов, которого больше нет в паспортах, удаляется, если под ним нет
узлов, которые остаются, и в нём нет правок человека. Проверки считаются при чтении по
подтверждённым данным и не хранятся. Доступ к проекту проверяет вызывающий.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.building_frame import (
    FrameCheckOut,
    FrameCheckRefOut,
    FrameElevationSource,
    FrameNodeCreate,
    FrameNodeOut,
    FrameNodePatch,
    FrameOut,
    FramePassportRef,
    FrameRebuildOut,
)
from app.errors import ErrorCode, http_error, not_found
from app.models import DocQuestionAnswer, FrameNode, SheetPassport
from app.services.consistency.building_frame import (
    FRAME_VERSION,
    ElevationSource,
    LevelPoint,
    NodeDraft,
    NodeKey,
    NodeKind,
    NodeOrigin,
    NodeStatus,
    PassportRow,
    build_frame,
    derived_heights,
    distinct_elevations,
    level_rank,
)
from app.services.consistency.dictionaries import SheetKind
from app.services.consistency.doc_questions import DocQuestionCode
from app.services.consistency.frame_checks import (
    CHECK_TITLES,
    FRAME_CHECKS_VERSION,
    AnswerView,
    CheckResult,
    LevelView,
    run_frame_checks,
)
from app.services.consistency.register_checks import REGISTER_CHECKS_VERSION, run_register_checks
from app.services.sheet_passports import latest_pdf_revisions
from app.services.sheet_registers import register_check_inputs

_KIND_ORDER: Final = {NodeKind.BUILDING: 0, NodeKind.SECTION: 1, NodeKind.LEVEL: 2}
_LEVEL_FIELDS: Final = ("ordinal", "elevation_m", "height_m")
_FRAME_QUESTIONS: Final = (
    DocQuestionCode.STOREYS.value,
    DocQuestionCode.FLOORS_TOTAL.value,
    DocQuestionCode.FLOOR_HEIGHT.value,
)
_ANSWER_SOURCES: Final = ("document", "manual")


def versions() -> dict[str, str]:
    return {
        "frame": FRAME_VERSION,
        "checks": FRAME_CHECKS_VERSION,
        "register_checks": REGISTER_CHECKS_VERSION,
    }


def _invalid(message: str) -> Exception:
    return http_error(ErrorCode.VALIDATION_FAILED, message=message)


def _key(row: FrameNode) -> NodeKey:
    return NodeKey(NodeKind(row.kind), row.building, row.section, row.code)


def _natural(value: str | None) -> tuple[int, int, str]:
    """«2» раньше «10»; не указанное - первым."""
    if value is None:
        return (0, 0, "")
    return (1, int(value), "") if value.isdigit() else (2, 0, value)


def _manual(row: FrameNode) -> set[str]:
    raw = row.evidence.get("manual")
    return {str(item) for item in raw} if isinstance(raw, list) else set()


# --------------------------------------------------------------------------- входы


def _passport_row(row: SheetPassport) -> PassportRow:
    return PassportRow(
        id=str(row.id),
        file_name=row.file_name,
        page_index=row.page_index,
        section_mark=row.section_mark,
        sheet_kind=row.sheet_kind,
        building=row.building,
        section=row.section,
        level_from=row.level_from,
        level_to=row.level_to,
        level_from_ordinal=row.level_from_ordinal,
        level_to_ordinal=row.level_to_ordinal,
        elevation_m=row.elevation_m,
        title=row.title,
    )


async def _latest_revision_ids(session: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    return [item.id for item in await latest_pdf_revisions(session, project_id=project_id)]


async def confirmed_passports(session: AsyncSession, project_id: uuid.UUID) -> list[PassportRow]:
    """Подтверждённые паспорта последних ревизий PDF проекта."""
    revision_ids = await _latest_revision_ids(session, project_id)
    if not revision_ids:
        return []
    rows = await session.scalars(
        select(SheetPassport)
        .where(
            SheetPassport.project_id == project_id,
            SheetPassport.revision_id.in_(revision_ids),
            SheetPassport.status == NodeStatus.CONFIRMED.value,
        )
        .order_by(SheetPassport.file_name, SheetPassport.page_index, SheetPassport.id)
    )
    return [_passport_row(row) for row in rows]


async def _plan_counts(session: AsyncSession, project_id: uuid.UUID) -> tuple[int, int]:
    """Подтверждённые и непроверенные паспорта планов последних ревизий."""
    revision_ids = await _latest_revision_ids(session, project_id)
    if not revision_ids:
        return 0, 0
    rows = await session.execute(
        select(SheetPassport.status, func.count())
        .where(
            SheetPassport.project_id == project_id,
            SheetPassport.revision_id.in_(revision_ids),
            SheetPassport.sheet_kind == SheetKind.FLOOR_PLAN.value,
        )
        .group_by(SheetPassport.status)
    )
    counts = {str(status): int(count) for status, count in rows.all()}
    return counts.get("confirmed", 0), counts.get("candidate", 0)


async def _answers(session: AsyncSession, project_id: uuid.UUID) -> list[AnswerView]:
    """Подтверждённые ответы ПЗ для каркаса: документ или ручной ввод, одно число."""
    rows = await session.scalars(
        select(DocQuestionAnswer)
        .where(
            DocQuestionAnswer.project_id == project_id,
            DocQuestionAnswer.question_code.in_(_FRAME_QUESTIONS),
            DocQuestionAnswer.source.in_(_ANSWER_SOURCES),
        )
        .order_by(
            DocQuestionAnswer.question_code,
            func.coalesce(DocQuestionAnswer.scope_building, ""),
            func.coalesce(DocQuestionAnswer.scope_section, ""),
        )
    )
    result = []
    for row in rows:
        numbers = (row.value or {}).get("numbers")
        if not isinstance(numbers, list) or not numbers or not isinstance(numbers[0], int):
            continue
        result.append(
            AnswerView(
                id=str(row.id),
                question_code=row.question_code,
                scope_building=row.scope_building,
                scope_section=row.scope_section,
                number=numbers[0],
                value_text=row.value_text or str(numbers[0]),
                file_name=row.file_name,
                page_index=row.page_index,
            )
        )
    return result


async def _nodes(
    session: AsyncSession, project_id: uuid.UUID, *, lock: bool = False
) -> list[FrameNode]:
    query = (
        select(FrameNode)
        .where(FrameNode.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return list(await session.scalars(query))


# --------------------------------------------------------------------------- сборка


def _apply_draft(row: FrameNode, draft: NodeDraft) -> None:
    """Значения и доказательства кандидата; поля, правленные человеком, не трогаются."""
    manual = _manual(row)
    if draft.key.kind is NodeKind.LEVEL:
        if "ordinal" not in manual:
            row.ordinal = draft.ordinal
        if "elevation_m" not in manual:
            row.elevation_m = draft.elevation_m
    evidence: dict[str, Any] = dict(draft.evidence())
    if manual:
        evidence["manual"] = sorted(manual)
    row.evidence = evidence
    row.versions = versions()


async def rebuild(session: AsyncSession, *, project_id: uuid.UUID) -> FrameRebuildOut:
    """Пересобирает кандидатов каркаса из подтверждённых паспортов; см. docstring модуля."""
    drafts = build_frame(await confirmed_passports(session, project_id))
    rows = await _nodes(session, project_id, lock=True)
    by_key = {_key(row): row for row in rows}
    created = updated = kept = removed = 0

    ordered = sorted(drafts.values(), key=lambda item: _KIND_ORDER[item.key.kind])
    for draft in ordered:
        row = by_key.get(draft.key)
        if row is None:
            parent_key = draft.key.parent
            parent = None if parent_key is None else by_key[parent_key]
            row = FrameNode(
                project_id=project_id,
                kind=draft.key.kind.value,
                parent_id=None if parent is None else parent.id,
                building=draft.key.building,
                section=draft.key.section,
                code=draft.key.code,
                status=NodeStatus.CANDIDATE.value,
                origin=NodeOrigin.PASSPORTS.value,
                evidence={},
                versions={},
            )
            row.id = uuid.uuid4()
            _apply_draft(row, draft)
            session.add(row)
            by_key[draft.key] = row
            created += 1
        elif row.status != NodeStatus.CANDIDATE.value:
            kept += 1
        else:
            _apply_draft(row, draft)
            updated += 1
    await session.flush()

    # Кандидаты из паспортов, которых больше нет: снизу вверх, только без остающихся детей.
    children: dict[uuid.UUID, int] = defaultdict(int)
    for row in by_key.values():
        if row.parent_id is not None:
            children[row.parent_id] += 1
    stale = [
        row
        for key, row in by_key.items()
        if key not in drafts
        and row.status == NodeStatus.CANDIDATE.value
        and row.origin == NodeOrigin.PASSPORTS.value
    ]
    for row in sorted(stale, key=lambda item: -_KIND_ORDER[NodeKind(item.kind)]):
        # Узел с детьми или с правкой человека остаётся: правка не теряется молча.
        if children.get(row.id, 0) > 0 or _manual(row):
            row.evidence = {**dict(NodeDraft(key=_key(row)).evidence()), **_manual_part(row)}
            continue
        if row.parent_id is not None:
            children[row.parent_id] -= 1
        await session.delete(row)
        removed += 1
    await session.flush()
    return FrameRebuildOut(created=created, updated=updated, removed=removed, kept_reviewed=kept)


def _manual_part(row: FrameNode) -> dict[str, Any]:
    manual = _manual(row)
    return {"manual": sorted(manual)} if manual else {}


# --------------------------------------------------------------------------- чтение


def _evidence_passports(row: FrameNode) -> list[FramePassportRef]:
    raw = row.evidence.get("passports")
    if not isinstance(raw, list):
        return []
    return [
        FramePassportRef(
            id=str(item.get("id", "")),
            file_name=str(item.get("file_name", "")),
            page_index=int(item.get("page_index", 0)),
            section_mark=None if item.get("section_mark") is None else str(item["section_mark"]),
        )
        for item in raw
        if isinstance(item, dict)
    ]


def _evidence_elevations(row: FrameNode) -> list[ElevationSource]:
    raw = row.evidence.get("elevations")
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("value_m"), int | float):
            result.append(
                ElevationSource(
                    value_m=float(item["value_m"]),
                    passport_id=str(item.get("passport_id", "")),
                    file_name=str(item.get("file_name", "")),
                    page_index=int(item.get("page_index", 0)),
                )
            )
    return result


def _passport_count(row: FrameNode) -> int:
    value = row.evidence.get("passport_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _node_out(row: FrameNode, height_derived: float | None) -> FrameNodeOut:
    sources = _evidence_elevations(row)
    manual = _manual(row)
    values = [] if "elevation_m" in manual else distinct_elevations(sources)
    return FrameNodeOut(
        id=row.id,
        kind=NodeKind(row.kind),
        parent_id=row.parent_id,
        building=row.building,
        section=row.section,
        code=row.code,
        ordinal=row.ordinal,
        elevation_m=row.elevation_m,
        height_m=row.height_m,
        height_derived_m=height_derived,
        status=NodeStatus(row.status),
        origin=NodeOrigin(row.origin),
        passport_count=_passport_count(row),
        passports=_evidence_passports(row),
        elevation_sources=[
            FrameElevationSource(
                value_m=item.value_m,
                passport_id=item.passport_id,
                file_name=item.file_name,
                page_index=item.page_index,
            )
            for item in sources
        ],
        elevation_values=values,
        manual_fields=sorted(manual),
        confirmed_at=row.confirmed_at,
    )


def _sort_key(row: FrameNode) -> tuple[Any, ...]:
    return (
        _natural(row.building),
        _natural(row.section),
        _KIND_ORDER[NodeKind(row.kind)],
        level_rank(row.ordinal, row.code or ""),
        row.code or "",
    )


def _heights(rows: list[FrameNode]) -> dict[str, float]:
    """Выведенные высоты уровней: по отметкам соседних уровней каждой секции."""
    groups: dict[uuid.UUID | None, list[LevelPoint]] = defaultdict(list)
    for row in rows:
        if row.kind == NodeKind.LEVEL.value and row.status != NodeStatus.REJECTED.value:
            groups[row.parent_id].append(LevelPoint(str(row.id), row.ordinal, row.elevation_m))
    result: dict[str, float] = {}
    for points in groups.values():
        result.update(derived_heights(points))
    return result


def _check_out(item: CheckResult) -> FrameCheckOut:
    return FrameCheckOut(
        code=item.code,
        title=CHECK_TITLES[item.code],
        status=item.status,
        message=item.message,
        building=item.building,
        section=item.section,
        level=item.level,
        refs=[
            FrameCheckRefOut(
                kind=ref.kind,
                id=ref.id,
                label=ref.label,
                file_name=ref.file_name,
                page_index=ref.page_index,
            )
            for ref in item.refs
        ],
    )


def _confirmed_levels(rows: list[FrameNode], heights: dict[str, float]) -> list[LevelView]:
    """Подтверждённые уровни, у которых ни секция, ни корпус не отклонены."""
    by_id = {row.id: row for row in rows}

    def alive(row: FrameNode) -> bool:
        current: FrameNode | None = row
        while current is not None:
            if current.status == NodeStatus.REJECTED.value:
                return False
            current = None if current.parent_id is None else by_id.get(current.parent_id)
        return True

    result = []
    for row in rows:
        if row.kind != NodeKind.LEVEL.value or row.status != NodeStatus.CONFIRMED.value:
            continue
        if not alive(row) or row.code is None:
            continue
        manual = _manual(row)
        values = (
            () if "elevation_m" in manual else tuple(distinct_elevations(_evidence_elevations(row)))
        )
        result.append(
            LevelView(
                id=str(row.id),
                building=row.building,
                section=row.section,
                code=row.code,
                ordinal=row.ordinal,
                elevation_m=row.elevation_m,
                height_m=row.height_m if row.height_m is not None else heights.get(str(row.id)),
                elevation_values=values if len(values) > 1 else (),
            )
        )
    return result


async def frame_view(session: AsyncSession, *, project_id: uuid.UUID) -> FrameOut:
    rows = sorted(await _nodes(session, project_id), key=_sort_key)
    heights = _heights(rows)
    passports = await confirmed_passports(session, project_id)
    checks = run_frame_checks(
        _confirmed_levels(rows, heights), passports, await _answers(session, project_id)
    )
    registers, register_candidates, register_sheets = await register_check_inputs(
        session, project_id
    )
    checks += run_register_checks(registers, register_sheets, candidates=register_candidates)
    confirmed_plans, candidate_plans = await _plan_counts(session, project_id)
    return FrameOut(
        nodes=[_node_out(row, heights.get(str(row.id))) for row in rows],
        checks=[_check_out(item) for item in checks],
        confirmed_plans=confirmed_plans,
        candidate_plans=candidate_plans,
        versions=versions(),
    )


# --------------------------------------------------------------------------- правка


async def _node(session: AsyncSession, project_id: uuid.UUID, node_id: uuid.UUID) -> FrameNode:
    row = await session.scalar(
        select(FrameNode)
        .where(FrameNode.id == node_id, FrameNode.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise not_found("Узел каркаса")
    return row


async def _node_out_by_id(
    session: AsyncSession, project_id: uuid.UUID, node_id: uuid.UUID
) -> FrameNodeOut:
    rows = await _nodes(session, project_id)
    heights = _heights(rows)
    for row in rows:
        if row.id == node_id:
            return _node_out(row, heights.get(str(row.id)))
    raise not_found("Узел каркаса")


def _stamp(row: FrameNode, status: NodeStatus, user_id: uuid.UUID) -> None:
    row.status = status.value
    if status is NodeStatus.CANDIDATE:
        row.confirmed_by = None
        row.confirmed_at = None
    else:
        row.confirmed_by = user_id
        row.confirmed_at = datetime.now(UTC)


async def patch_node(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    node_id: uuid.UUID,
    patch: FrameNodePatch,
    user_id: uuid.UUID,
) -> FrameNodeOut:
    """Правка уровня и/или статуса; правленое поле уровня помечается `manual`."""
    row = await _node(session, project_id, node_id)
    touched = [name for name in _LEVEL_FIELDS if name in patch.model_fields_set]
    if touched and row.kind != NodeKind.LEVEL.value:
        raise _invalid("номер, отметка и высота бывают только у уровня")
    manual = _manual(row)
    for name in touched:
        setattr(row, name, getattr(patch, name))
        manual.add(name)
    if touched:
        row.evidence = {**row.evidence, "manual": sorted(manual)}
    if patch.status is not None:
        _stamp(row, patch.status, user_id)
    await session.flush()
    return await _node_out_by_id(session, project_id, node_id)


async def bulk_status(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    ids: list[uuid.UUID],
    status: NodeStatus,
    user_id: uuid.UUID,
) -> int:
    """Единый статус пачке узлов проекта; чужой или неизвестный id - 404, ничего не меняется."""
    unique = set(ids)
    found = await session.scalar(
        select(func.count())
        .select_from(FrameNode)
        .where(FrameNode.project_id == project_id, FrameNode.id.in_(unique))
    )
    if int(found or 0) != len(unique):
        raise not_found("Узел каркаса")
    review = status is not NodeStatus.CANDIDATE
    updated = await session.scalars(
        update(FrameNode)
        .where(FrameNode.project_id == project_id, FrameNode.id.in_(unique))
        .values(
            status=status.value,
            confirmed_by=user_id if review else None,
            confirmed_at=datetime.now(UTC) if review else None,
        )
        .returning(FrameNode.id)
    )
    return len(updated.all())


async def create_node(
    session: AsyncSession, *, project_id: uuid.UUID, body: FrameNodeCreate
) -> FrameNodeOut:
    """Узел, добавленный человеком; недостающие корпус и секция создаются ручными кандидатами.

    Узел с тем же ключом уже есть - 422: правится существующий, а не заводится второй.
    """
    rows = await _nodes(session, project_id, lock=True)
    by_key = {_key(row): row for row in rows}
    target = NodeKey(
        body.kind,
        body.building,
        body.section if body.kind is not NodeKind.BUILDING else None,
        body.code,
    )
    if target in by_key:
        raise _invalid("такой узел каркаса уже есть")

    chain: list[NodeKey] = []
    current: NodeKey | None = target
    while current is not None:
        chain.append(current)
        current = current.parent
    for key in reversed(chain):
        if key in by_key:
            continue
        parent_key = key.parent
        parent = None if parent_key is None else by_key[parent_key]
        is_target = key == target
        manual_fields = (
            [name for name in _LEVEL_FIELDS if getattr(body, name) is not None] if is_target else []
        )
        row = FrameNode(
            project_id=project_id,
            kind=key.kind.value,
            parent_id=None if parent is None else parent.id,
            building=key.building,
            section=key.section,
            code=key.code,
            ordinal=body.ordinal if is_target else None,
            elevation_m=body.elevation_m if is_target else None,
            height_m=body.height_m if is_target else None,
            status=NodeStatus.CANDIDATE.value,
            origin=NodeOrigin.MANUAL.value,
            evidence={"manual": manual_fields} if manual_fields else {},
            versions=versions(),
        )
        row.id = uuid.uuid4()
        session.add(row)
        by_key[key] = row
    await session.flush()
    return await _node_out_by_id(session, project_id, by_key[target].id)


async def delete_node(session: AsyncSession, *, project_id: uuid.UUID, node_id: uuid.UUID) -> None:
    """Удаляет узел, добавленный человеком, с детьми; узел из паспортов - только отклонить."""
    row = await _node(session, project_id, node_id)
    if row.origin != NodeOrigin.MANUAL.value:
        raise _invalid("узел из паспортов листов не удаляется - его можно отклонить")
    rows = await _nodes(session, project_id)
    below = {row.id}
    for kind in (NodeKind.SECTION, NodeKind.LEVEL):
        below |= {item.id for item in rows if item.kind == kind.value and item.parent_id in below}
    if any(item.id in below and item.origin != NodeOrigin.MANUAL.value for item in rows):
        raise _invalid("под узлом есть узлы из паспортов листов - узел можно только отклонить")
    await session.delete(row)
    await session.flush()
