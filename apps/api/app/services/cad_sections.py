"""Задание «Разрезы» (`cad_sections`): уровни АР по тексту PDF, решения человека, высота для трасс.

Генератор `cad_mep/run_sections.py` движка (PyMuPDF) запускает только cad-worker подпроцессом; сюда
он не импортируется. Версия генератора и sha256 параметров - пин `cad_mep` из pins.json (отдельного
пина у разрезов нет). Результат - кандидаты `cad_section_levels`; в расчёт попадает только то, что
принял человек: принятая высота «чистый пол - низ плиты» уходит в запуск трасс механики.

Повторный запуск для той же ревизии заменяет строки прежних заданий, а решения переносятся на
новые строки с теми же значениями (страница, линия разреза, отметка, высота, толщина).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_sections import (
    SectionLevelRead,
    SectionsFile,
)
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode, not_found
from app.models import (
    CadSectionLevel,
    DocQuestionAnswer,
    DocumentRevision,
    Job,
    Project,
    SheetPassport,
)
from app.services import cad as cad_service
from app.services import cad_construction_store
from app.services import cad_mep as cad_mep_service
from app.services import feature_flags as flags_service
from app.services import jobs as jobs_service
from app.services.consistency.doc_questions import DocQuestionCode

SECTIONS_JSON: Final = "sections.json"
SECTIONS_SCHEMA: Final = "cad_sections.v2"
RUNNER_NAME: Final = "run_sections.py"
RESULT_READY: Final = "sections_ready"

# Пределы, которые принимает генератор трасс (`--clear-height-mm`, `--slab-thickness-mm`).
CLEAR_HEIGHT_MIN_MM: Final = cad_mep_service.CLEAR_HEIGHT_MIN_MM
CLEAR_HEIGHT_MAX_MM: Final = cad_mep_service.CLEAR_HEIGHT_MAX_MM
SLAB_THICKNESS_MIN_MM: Final = cad_mep_service.SLAB_THICKNESS_MIN_MM
SLAB_THICKNESS_MAX_MM: Final = cad_mep_service.SLAB_THICKNESS_MAX_MM

LEVELS_SOURCE_SECTION: Final = "section"
LEVELS_SOURCE_DOC_ANSWER: Final = "doc_answer"
LEVELS_SOURCE_PROJECT_SLAB: Final = "project_slab"
LEVELS_SOURCE_NONE: Final = "none"
WARNING_AMBIGUOUS: Final = "section_level_ambiguous"
# Принятые разрезы есть, но отметка этажа листа не известна: уровни пропущены.
WARNING_FLOOR_ELEVATION_UNKNOWN: Final = "section_floor_elevation_unknown"
WARNING_DOC_AMBIGUOUS: Final = "doc_answer_ambiguous"
WARNING_DOC_OUT_OF_RANGE: Final = "doc_answer_out_of_range"
CONSISTENCY_FLAG: Final = "project.consistency"


def runner_path(settings: Settings) -> Path | None:
    """CLI разрезов лежит рядом с генератором трасс; генератор не настроен - разрезов тоже нет."""
    mep_runner = cad_mep_service.runner_path(settings)
    return mep_runner.with_name(RUNNER_NAME) if mep_runner is not None else None


def idempotency_key(
    revision_id: uuid.UUID,
    *,
    params_sha256: str,
    generator_version: str,
    page_indexes: list[int] | None,
) -> str:
    """Та же ревизия, параметры, версия генератора и набор страниц - то же задание."""
    pages = "all" if page_indexes is None else ",".join(str(i) for i in sorted(page_indexes))
    digest = hashlib.sha256(
        "|".join((str(revision_id), params_sha256, generator_version, pages)).encode()
    ).hexdigest()
    return f"cadsections:{digest[:48]}"


def normalized_pages(page_indexes: list[int] | None) -> list[int] | None:
    """Страницы без повторов по возрастанию; пусто (`None`) - все страницы PDF."""
    if page_indexes is None:
        return None
    if len(set(page_indexes)) != len(page_indexes):
        raise DomainError(ErrorCode.CAD_PARAMS_INVALID, "page_indexes: индексы без повторов")
    return sorted(page_indexes)


async def schedule(
    session: AsyncSession,
    *,
    project: Project,
    revision: DocumentRevision,
    page_indexes: list[int] | None,
    settings: Settings,
) -> Job:
    """Задание `cad_sections` по исходному PDF ревизии; тот же ключ - то же задание."""
    if not cad_service.is_pdf(revision):
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "Источник ревизии не PDF")
    pages = normalized_pages(page_indexes)
    params = cad_mep_service.load_params(settings)
    return await jobs_service.enqueue(
        session,
        job_type=JobType.CAD_SECTIONS,
        workspace_id=project.workspace_id,
        project_id=project.id,
        idempotency_key=idempotency_key(
            revision.id,
            params_sha256=params.sha256,
            generator_version=params.generator_version,
            page_indexes=pages,
        ),
        payload={
            "revision_id": str(revision.id),
            "page_indexes": pages,
            "params_sha256": params.sha256,
            "generator_version": params.generator_version,
            "engine_version": params.generator_version,
        },
    )


async def latest_jobs(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID, revision_id: uuid.UUID
) -> tuple[Job | None, Job | None]:
    """Последнее задание ревизии и последнее выполненное; задания - только своего пространства."""
    base = select(Job).where(
        Job.job_type == JobType.CAD_SECTIONS,
        Job.workspace_id == workspace_id,
        Job.project_id == project_id,
        Job.payload["revision_id"].astext == str(revision_id),
    )
    latest = await session.scalar(
        base.order_by(Job.created_at.desc(), Job.id)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if latest is None:
        return None, None
    if latest.status is JobStatus.SUCCEEDED:
        return latest, latest
    done = await session.scalar(
        base.where(Job.status == JobStatus.SUCCEEDED)
        .order_by(Job.created_at.desc(), Job.id)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    return latest, done


# ------------------------------------------------------------------ публикация и чтение уровней

_DecisionKey = tuple[int, str | None, int, int | None, int | None]


def _decision_key(
    page_index: int,
    cut: str | None,
    elevation_mm: int,
    clear_height_mm: int | None,
    structure_mm: int | None,
) -> _DecisionKey:
    return (page_index, cut, elevation_mm, clear_height_mm, structure_mm)


async def publish_levels(
    session: AsyncSession,
    *,
    job: Job,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    revision_id: uuid.UUID,
    document: SectionsFile,
) -> int:
    """Строки уровней задания; строки прежних заданий ревизии удаляются, решения переносятся.

    Решение переносится на новую строку с тем же (страница, линия разреза, отметка, высота в свету,
    толщина): статус и автор с временем копируются. Решения к исчезнувшим строкам теряются.
    Вызывается в транзакции записи успеха задания. Возвращает число новых строк.
    """
    previous = list(
        (
            await session.scalars(
                select(CadSectionLevel).where(
                    CadSectionLevel.project_id == project_id,
                    CadSectionLevel.revision_id == revision_id,
                    CadSectionLevel.job_id != job.id,
                )
            )
        ).all()
    )
    carried: dict[_DecisionKey, tuple[str, uuid.UUID, datetime]] = {}
    for old in previous:
        if old.status != "candidate" and old.decided_by is not None and old.decided_at is not None:
            key = _decision_key(
                old.page_index, old.cut, old.elevation_mm, old.clear_height_mm, old.structure_mm
            )
            carried[key] = (old.status, old.decided_by, old.decided_at)
        await session.delete(old)
    await session.flush()

    seq = 0
    for page in document.sections:
        for level in page.levels:
            decision = carried.get(
                _decision_key(
                    page.page_index,
                    level.cut,
                    level.elevation_mm,
                    level.clear_height_mm,
                    level.structure_mm,
                )
            )
            session.add(
                CadSectionLevel(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    job_id=job.id,
                    revision_id=revision_id,
                    seq=seq,
                    page_index=page.page_index,
                    cut=level.cut,
                    corps=page.corps,
                    section=page.section,
                    floor=level.floor,
                    elevation_mm=level.elevation_mm,
                    upper_elevation_mm=level.upper_elevation_mm,
                    clear_height_mm=level.clear_height_mm,
                    structure_mm=level.structure_mm,
                    evidence=level.evidence,
                    markup=level.markup.model_dump(mode="json"),
                    status="candidate" if decision is None else decision[0],
                    decided_by=None if decision is None else decision[1],
                    decided_at=None if decision is None else decision[2],
                )
            )
            seq += 1
    await session.flush()
    return seq


async def list_levels(
    session: AsyncSession, *, project_id: uuid.UUID, revision_id: uuid.UUID
) -> list[CadSectionLevel]:
    rows = await session.scalars(
        select(CadSectionLevel)
        .where(CadSectionLevel.project_id == project_id, CadSectionLevel.revision_id == revision_id)
        .order_by(CadSectionLevel.page_index, CadSectionLevel.seq, CadSectionLevel.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


def level_read(row: CadSectionLevel) -> SectionLevelRead:
    """Строка -> ответ API; статус и разметка проверяются моделью (`markup` - типизированная)."""
    return SectionLevelRead.model_validate(row, from_attributes=True)


def _decidable(row: CadSectionLevel) -> str | None:
    """Почему уровень нельзя принять; `None` - можно."""
    if row.clear_height_mm is None:
        return "у уровня нет высоты в свету"
    if not CLEAR_HEIGHT_MIN_MM <= row.clear_height_mm <= CLEAR_HEIGHT_MAX_MM:
        return (
            f"высота в свету {row.clear_height_mm} мм вне пределов "
            f"{CLEAR_HEIGHT_MIN_MM}-{CLEAR_HEIGHT_MAX_MM} мм"
        )
    return None


async def decide(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    level_ids: list[uuid.UUID],
    decision: str,
    user_id: uuid.UUID,
) -> list[CadSectionLevel]:
    """Решение человека по уровням: `accept`, `reject` или `reset` (обратно в кандидаты).

    Чужой проект или пространство - 404 (строки чужого проекта не находятся). Принять уровень без
    высоты в свету (или с высотой вне пределов генератора трасс) нельзя: 422, ничего не меняется.
    """
    unique = set(level_ids)
    rows = list(
        (
            await session.scalars(
                select(CadSectionLevel)
                .where(
                    CadSectionLevel.id.in_(unique),
                    CadSectionLevel.project_id == project_id,
                    CadSectionLevel.workspace_id == workspace_id,
                )
                .order_by(CadSectionLevel.page_index, CadSectionLevel.seq, CadSectionLevel.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(rows) != len(unique):
        raise not_found("Уровень разреза")
    if decision == "accept":
        problems = [(row, _decidable(row)) for row in rows]
        failed = [
            f"стр. {row.page_index + 1}, отметка {row.elevation_mm} мм: {why}"
            for row, why in problems
            if why
        ]
        if failed:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "Принять нельзя - " + "; ".join(failed[:5]),
            )
    now = datetime.now(UTC)
    for row in rows:
        if decision == "reset":
            row.status, row.decided_by, row.decided_at = "candidate", None, None
        else:
            row.status = "accepted" if decision == "accept" else "rejected"
            row.decided_by, row.decided_at = user_id, now
    await session.flush()
    return rows


# ------------------------------------------------------------------ источник уровней для трасс


@dataclass(frozen=True, slots=True)
class DocAnswerOrigin:
    """Происхождение высоты из ответа к документации (для manual файл и страница пусты)."""

    answer_id: uuid.UUID
    question_code: str
    answer_source: str
    file_name: str | None
    page_index: int | None

    def to_payload(self) -> dict[str, str | int | None]:
        return {
            "answer_id": str(self.answer_id),
            "question_code": self.question_code,
            "answer_source": self.answer_source,
            "file_name": self.file_name,
            "page_index": self.page_index,
        }


@dataclass(frozen=True, slots=True)
class RouteLevels:
    """Что уходит в запуск трасс: высота в свету, толщина плиты либо ничего; оба сразу - никогда."""

    clear_height_mm: int | None = None
    slab_thickness_mm: int | None = None
    source: str = LEVELS_SOURCE_NONE
    section_level_ids: tuple[uuid.UUID, ...] = ()
    warnings: tuple[str, ...] = ()
    doc_answer: DocAnswerOrigin | None = None


_RANGE: Final = re.compile(r"(\d+)\s*[-\u2013\u2014]\s*(\d+)")
_WORDS: Final = re.compile(r"корпус\w*|корп\.?|секци\w*|сек\.?", re.IGNORECASE)
_TOKEN: Final = re.compile(r"\d+[a-zа-я]?|\b[a-zа-я]\b")
_MAX_RANGE: Final = 100


def marks(value: str | None) -> frozenset[str]:
    """Метки корпуса или секции: «9» -> {9}, «2-4» -> {2, 3, 4}, «1, 2» -> {1, 2}."""
    if value is None:
        return frozenset()
    text = _WORDS.sub(" ", value.casefold())
    found: set[str] = set()

    def expand(match: re.Match[str]) -> str:
        low, high = int(match.group(1)), int(match.group(2))
        if low <= high and high - low <= _MAX_RANGE:
            found.update(str(number) for number in range(low, high + 1))
        return " "

    text = _RANGE.sub(expand, text)
    found.update(token for token in _TOKEN.findall(text))
    return frozenset(found)


def _narrow(
    rows: list[CadSectionLevel], wanted: frozenset[str], field: str
) -> list[CadSectionLevel]:
    """Уровни, чей корпус (секция) пересекается с заданным; пусто - сужение не применяется."""
    if not wanted:
        return rows
    kept = [row for row in rows if marks(getattr(row, field)) & wanted]
    return kept or rows


def _distinct(rows: list[CadSectionLevel]) -> set[int]:
    return {row.clear_height_mm for row in rows if row.clear_height_mm is not None}


async def _plan_passport_marks(
    session: AsyncSession, *, revision_id: uuid.UUID, page_index: int
) -> tuple[frozenset[str], frozenset[str]]:
    """Корпус и секция листа плана из подтверждённого паспорта листа; иное - не источник."""
    row = await session.scalar(
        select(SheetPassport).where(
            SheetPassport.revision_id == revision_id,
            SheetPassport.page_index == page_index,
            SheetPassport.status == "confirmed",
        )
    )
    if row is None:
        return frozenset(), frozenset()
    return marks(row.building), marks(row.section)


# Вопросы каталога, которые принимает движок трасс, по приоритету: высота в свету главнее плиты.
_DOC_QUESTIONS: Final = (
    (DocQuestionCode.CLEAR_HEIGHT.value, CLEAR_HEIGHT_MIN_MM, CLEAR_HEIGHT_MAX_MM),
    (DocQuestionCode.SLAB_THICKNESS.value, SLAB_THICKNESS_MIN_MM, SLAB_THICKNESS_MAX_MM),
)
_DOC_SOURCES: Final = ("document", "manual")


def _first_number(row: DocQuestionAnswer) -> int | None:
    value = row.value
    numbers = value.get("numbers") if isinstance(value, dict) else None
    if not isinstance(numbers, list) or not numbers:
        return None
    first = numbers[0]
    return first if isinstance(first, int) and not isinstance(first, bool) else None


def _scope_rank(
    row: DocQuestionAnswer, building: frozenset[str], section: frozenset[str]
) -> int | None:
    """Точность области ответа для листа: 3 корпус+секция, 2 корпус, 1 секция, 0 проект.

    Не подошёл листу - `None`; в том числе область задана, а метки листа неизвестны (нет
    подтверждённого паспорта).
    """
    row_building, row_section = marks(row.scope_building), marks(row.scope_section)
    if row.scope_building is None and row.scope_section is None:
        return 0
    if row.scope_building is not None and not (row_building & building):
        return None
    if row.scope_section is not None and not (row_section & section):
        return None
    return (2 if row.scope_building is not None else 0) + (
        1 if row.scope_section is not None else 0
    )


async def _doc_answer_levels(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    plan_revision_id: uuid.UUID,
    plan_page_index: int,
) -> tuple[RouteLevels | None, tuple[str, ...]]:
    """Высота из подтверждённых ответов к документации: `(уровни | None, предупреждения)`.

    Берутся только `document` и `manual` с числом; `not_in_project` и `norm_assumption` - никогда.
    Сначала `clear_height`, иначе `slab_thickness`: решает первый вопрос, у которого есть
    подходящие листу ответы. Из них берётся самая точная область; разные значения на ней или
    значение вне пределов генератора - источник не применяется, предупреждение.
    """
    rows = list(
        (
            await session.scalars(
                select(DocQuestionAnswer)
                .where(
                    DocQuestionAnswer.project_id == project_id,
                    DocQuestionAnswer.question_code.in_([code for code, _, _ in _DOC_QUESTIONS]),
                    DocQuestionAnswer.source.in_(_DOC_SOURCES),
                    DocQuestionAnswer.value.is_not(None),
                )
                .order_by(DocQuestionAnswer.confirmed_at.desc(), DocQuestionAnswer.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if not rows:
        return None, ()
    building, section = await _plan_passport_marks(
        session, revision_id=plan_revision_id, page_index=plan_page_index
    )
    for code, low, high in _DOC_QUESTIONS:
        ranked = [
            (rank, row)
            for row in rows
            if row.question_code == code
            and _first_number(row) is not None
            and (rank := _scope_rank(row, building, section)) is not None
        ]
        if not ranked:
            continue
        best = max(rank for rank, _ in ranked)
        top = [row for rank, row in ranked if rank == best]
        if len({_first_number(row) for row in top}) > 1:
            return None, (WARNING_DOC_AMBIGUOUS,)
        chosen = top[0]
        number = _first_number(chosen)
        if number is None or not low <= number <= high:
            return None, (WARNING_DOC_OUT_OF_RANGE,)
        origin = DocAnswerOrigin(
            answer_id=chosen.id,
            question_code=chosen.question_code,
            answer_source=chosen.source,
            file_name=chosen.file_name,
            page_index=chosen.page_index,
        )
        is_clear = code == DocQuestionCode.CLEAR_HEIGHT.value
        return (
            RouteLevels(
                clear_height_mm=number if is_clear else None,
                slab_thickness_mm=None if is_clear else number,
                source=LEVELS_SOURCE_DOC_ANSWER,
                doc_answer=origin,
            ),
            (),
        )
    return None, ()


async def _doc_answers_enabled(
    session: AsyncSession, settings: Settings, workspace_id: uuid.UUID
) -> bool:
    """Флаг `project.consistency` пространства - тем же провайдером, что и `require_feature`."""
    evaluated = await flags_service.evaluate_all(
        session, settings, flags_service.EvaluationContext(workspace_id=workspace_id)
    )
    return evaluated[CONSISTENCY_FLAG].value


async def resolve_route_levels(
    session: AsyncSession,
    *,
    settings: Settings,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    floor_elevation_mm: int | None,
    plan_revision_id: uuid.UUID,
    plan_page_index: int,
) -> RouteLevels:
    """Источник уровней для запуска трасс: разрезы, ответы к документации, плита проекта, ничего.

    Известна отметка этажа листа - берутся принятые уровни проекта с этой отметкой. Одно значение
    высоты в свету -> `section`. Разные -> сужение по корпусу и секции листа плана (подтверждённый
    паспорт листа; нет паспорта или метка не совпала ни с одним уровнем - не сужаем); всё ещё
    разные -> ничего и предупреждение `section_level_ambiguous` (документация и плита не берутся).
    Принятых уровней нет (или отметка этажа не известна) -> подтверждённые ответы к документации
    (`doc_answer`, только при включённом флаге `project.consistency`), затем толщина плиты проекта,
    если задана, иначе ничего. Оба значения не уходят никогда. Отметка этажа не известна, но
    принятые уровни в проекте есть -> к любому исходу добавляется `section_floor_elevation_unknown`:
    разрезы пропущены не молча.
    """
    skipped: tuple[str, ...] = ()
    if floor_elevation_mm is None:
        has_accepted = await session.scalar(
            select(CadSectionLevel.id)
            .where(
                CadSectionLevel.project_id == project_id,
                CadSectionLevel.status == "accepted",
                CadSectionLevel.clear_height_mm.is_not(None),
                CadSectionLevel.clear_height_mm.between(CLEAR_HEIGHT_MIN_MM, CLEAR_HEIGHT_MAX_MM),
            )
            .limit(1)
        )
        if has_accepted is not None:
            skipped = (WARNING_FLOOR_ELEVATION_UNKNOWN,)
    if floor_elevation_mm is not None:
        rows = list(
            (
                await session.scalars(
                    select(CadSectionLevel)
                    .where(
                        CadSectionLevel.project_id == project_id,
                        CadSectionLevel.status == "accepted",
                        CadSectionLevel.elevation_mm == floor_elevation_mm,
                        CadSectionLevel.clear_height_mm.is_not(None),
                        CadSectionLevel.clear_height_mm.between(
                            CLEAR_HEIGHT_MIN_MM, CLEAR_HEIGHT_MAX_MM
                        ),
                    )
                    .order_by(CadSectionLevel.page_index, CadSectionLevel.seq, CadSectionLevel.id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        if rows:
            if len(_distinct(rows)) > 1:
                building, section = await _plan_passport_marks(
                    session, revision_id=plan_revision_id, page_index=plan_page_index
                )
                rows = _narrow(rows, building, "corps")
                if len(_distinct(rows)) > 1:
                    rows = _narrow(rows, section, "section")
            heights = _distinct(rows)
            if len(heights) == 1:
                return RouteLevels(
                    clear_height_mm=heights.pop(),
                    source=LEVELS_SOURCE_SECTION,
                    section_level_ids=tuple(row.id for row in rows),
                )
            return RouteLevels(warnings=(WARNING_AMBIGUOUS,))
    doc_warnings: tuple[str, ...] = ()
    if await _doc_answers_enabled(session, settings, workspace_id):
        doc_levels, doc_warnings = await _doc_answer_levels(
            session,
            project_id=project_id,
            plan_revision_id=plan_revision_id,
            plan_page_index=plan_page_index,
        )
        if doc_levels is not None:
            return replace(doc_levels, warnings=skipped + doc_levels.warnings)
    slab = await cad_construction_store.load_project_slab(session, project_id=project_id)
    if slab is not None and SLAB_THICKNESS_MIN_MM <= slab.thickness_mm <= SLAB_THICKNESS_MAX_MM:
        return RouteLevels(
            slab_thickness_mm=slab.thickness_mm,
            source=LEVELS_SOURCE_PROJECT_SLAB,
            warnings=skipped + doc_warnings,
        )
    return RouteLevels(warnings=skipped + doc_warnings)
