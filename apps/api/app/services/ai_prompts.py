"""Версии промтов ИИ-проверки: чтение, создание, активация, статистика прогонов."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, literal_column, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.ai_prompts import AiPromptCreate, AiPromptStatsRow
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import AiPromptVersion, CadRemark, Job


async def list_versions(session: AsyncSession, role: str | None) -> list[AiPromptVersion]:
    query = select(AiPromptVersion).order_by(AiPromptVersion.role, AiPromptVersion.version.desc())
    if role is not None:
        query = query.where(AiPromptVersion.role == role)
    return list(await session.scalars(query))


async def get_version(session: AsyncSession, prompt_id: uuid.UUID) -> AiPromptVersion:
    row = await session.get(AiPromptVersion, prompt_id)
    if row is None:
        raise not_found("Версия промта")
    return row


async def active_version(session: AsyncSession, role: str) -> AiPromptVersion | None:
    rows = await session.scalars(
        select(AiPromptVersion).where(
            AiPromptVersion.role == role, AiPromptVersion.status == "active"
        )
    )
    return rows.first()


async def create_version(
    session: AsyncSession, body: AiPromptCreate, user_id: uuid.UUID
) -> AiPromptVersion:
    """Новая версия роли в статусе draft; номер - следующий за наибольшим."""
    # Блокировка роли по строкам версий: два параллельных создания не берут один номер.
    await session.execute(
        select(AiPromptVersion.id).where(AiPromptVersion.role == body.role).with_for_update()
    )
    last = await session.scalar(
        select(func.max(AiPromptVersion.version)).where(AiPromptVersion.role == body.role)
    )
    row = AiPromptVersion(
        role=body.role,
        version=(last or 0) + 1,
        text=body.text,
        status="draft",
        note=body.note,
        created_by=user_id,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Номер версии занят, повторите") from error
    await session.refresh(row)
    return row


async def activate_version(session: AsyncSession, prompt_id: uuid.UUID) -> AiPromptVersion:
    """Делает версию активной; прежняя активная той же роли уходит в archived (одна транзакция)."""
    target = await session.scalar(
        select(AiPromptVersion).where(AiPromptVersion.id == prompt_id).with_for_update()
    )
    if target is None:
        raise not_found("Версия промта")
    if target.status == "active":
        return target
    previous = await session.scalar(
        select(AiPromptVersion)
        .where(AiPromptVersion.role == target.role, AiPromptVersion.status == "active")
        .with_for_update()
    )
    try:
        if previous is not None:
            previous.status = "archived"
            # Индекс не отложенный: прежняя активная должна уйти до того, как встанет новая.
            await session.flush()
        target.status = "active"
        target.activated_at = datetime.now(UTC)
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, "Активная версия изменилась, повторите"
        ) from error
    await session.refresh(target)
    return target


def _int(count: int | None) -> int:
    return int(count or 0)


async def stats(session: AsyncSession) -> list[AiPromptStatsRow]:
    """Статистика по версиям тремя запросами (без N+1): прогоны, находки по типам, замечания."""
    versions = await list_versions(session, None)
    prompt_id = Job.payload["prompt_version_id"].astext
    terminal = (JobStatus.SUCCEEDED, JobStatus.FAILED)
    scope = and_(
        Job.job_type == JobType.CAD_AI_REVIEW,
        Job.status.in_(terminal),
        prompt_id.is_not(None),
    )

    cost = Job.payload[("ai_review", "usage", "cost_usd")].as_float()
    duration = Job.payload[("ai_review", "usage", "duration_ms")].as_float()
    verdict = Job.payload[("ai_review", "report", "verdict")].astext
    runs = (
        await session.execute(
            select(
                prompt_id.label("pid"),
                Job.status,
                cost.label("cost"),
                duration.label("duration"),
                verdict.label("verdict"),
            ).where(scope)
        )
    ).all()

    finding = func.jsonb_array_elements(
        Job.payload[("ai_review", "report", "findings")]
    ).table_valued("value")
    finding_type = finding.c.value.op("->>")("type")
    by_type = (
        await session.execute(
            select(prompt_id.label("pid"), finding_type.label("type"), func.count())
            .select_from(Job)
            .join(finding, literal_column("true"))
            .where(scope, Job.status == JobStatus.SUCCEEDED)
            .group_by(prompt_id, finding_type)
        )
    ).all()

    key = func.jsonb_array_elements_text(Job.payload[("ai_review", "remark_keys")]).table_valued(
        "value"
    )
    fate = case((CadRemark.id.is_(None), "deleted"), else_=CadRemark.status)
    remarks = (
        await session.execute(
            select(prompt_id.label("pid"), fate.label("fate"), func.count())
            .select_from(Job)
            .join(key, literal_column("true"))
            .outerjoin(CadRemark, CadRemark.remark_key == key.c.value)
            .where(scope, Job.status == JobStatus.SUCCEEDED)
            .group_by(prompt_id, fate)
        )
    ).all()

    done: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    costs: dict[str, list[float]] = defaultdict(list)
    durations: dict[str, list[float]] = defaultdict(list)
    verdicts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for pid, status, run_cost, run_duration, run_verdict in runs:
        done[pid][status.value] += 1
        if run_cost is not None:
            costs[pid].append(run_cost)
        if run_duration is not None:
            durations[pid].append(run_duration)
        if run_verdict is not None:
            verdicts[pid][run_verdict] += 1
    types: dict[str, dict[str, int]] = defaultdict(dict)
    for pid, kind, count in by_type:
        types[pid][kind or "other"] = _int(count)
    fates: dict[str, dict[str, int]] = defaultdict(dict)
    for pid, state, count in remarks:
        fates[pid][state] = _int(count)

    rows: list[AiPromptStatsRow] = []
    for version in versions:
        pid = str(version.id)
        spent, taken = costs.get(pid, []), durations.get(pid, [])
        rows.append(
            AiPromptStatsRow.model_validate(
                {
                    "prompt_id": version.id,
                    "role": version.role,
                    "version": version.version,
                    "status": version.status,
                    "runs_total": sum(done[pid].values()),
                    "runs_succeeded": done[pid].get(JobStatus.SUCCEEDED.value, 0),
                    "runs_failed": done[pid].get(JobStatus.FAILED.value, 0),
                    "cost_avg_usd": sum(spent) / len(spent) if spent else None,
                    "cost_sum_usd": sum(spent) if spent else None,
                    "duration_avg_ms": sum(taken) / len(taken) if taken else None,
                    "verdicts": dict(verdicts[pid]),
                    "findings_total": sum(types[pid].values()),
                    "findings_by_type": types[pid],
                    "remarks_open": fates[pid].get("open", 0),
                    "remarks_resolved": fates[pid].get("resolved", 0),
                    "remarks_deleted": fates[pid].get("deleted", 0),
                }
            )
        )
    return rows
