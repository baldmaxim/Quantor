"""Вопросы к документации (ADR-0043, шаг 2, В3): задание поиска кандидатов по тексту страниц.

Задание берёт последние PDF-ревизии проекта, паспорта их страниц (раздел, тип листа, корпус,
секция, уровень) и сохранённый текст страниц (`revision_page_texts`), гонит чистый поиск
`consistency.doc_search` и сохраняет кандидатов. Модель чисел не выдаёт: значения берутся
шаблонами каталога `consistency.doc_questions.v1`. Кандидат - не ответ: ответом его делает
человек (`doc_answers`).

Память. `search_doc_questions` принимает синхронный итератор страниц, а текст читается
асинхронно, поэтому используется тот же алгоритм постранично: `search_page` на одну страницу
и слияние `rank_candidates` с усечением (как внутри `search_doc_questions`). В памяти одновременно
одна страница и не более `_COMPACT_AT` находок на вопрос (после усечения - `_COMPACT_KEEP`);
текст проекта целиком не держится. Кандидаты ревизии вливаются в общий итог только после того,
как ревизия прочитана целиком: оборванная ревизия не оставляет половину находок.

Повторный поиск заменяет кандидатов проекта (status = candidate); отклонённые (rejected)
сохраняются, и такой же кандидат (вопрос, ревизия, страница, значение) не воскресает. Доступ к
проекту проверяет вызывающий.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Final

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.doc_questions import DocSearchSummary
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import JobStatus, JobType
from app.errors import ErrorCode
from app.models import (
    CadSectionLevel,
    DocQuestionCandidate,
    DocumentRevision,
    Job,
    Project,
    RevisionPageText,
    SheetPassport,
)
from app.services import jobs as jobs_service
from app.services.consistency.dictionaries import SheetKind
from app.services.consistency.doc_questions import (
    DOC_QUESTIONS,
    DOC_QUESTIONS_VERSION,
    DocQuestionCode,
    DocValueKind,
    is_customer_document,
    question_by_code,
)
from app.services.consistency.doc_search import (
    DEFAULT_TOP_N,
    DocCandidate,
    DocScope,
    DocSearchPage,
    DocValue,
    doc_search_versions,
    rank_candidates,
    search_page,
)
from app.services.consistency.page_texts import PAGE_TEXT_FORMAT, iter_page_texts
from app.services.consistency.sheet_passport import PassportCandidate
from app.services.sheet_passports import latest_pdf_revisions
from app.storage.base import ObjectStorage

log = get_logger(__name__)

SEARCH_FAILED_CODE: Final = ErrorCode.DOC_QUESTIONS_SEARCH_FAILED.value
MAX_REPORTED_FILES: Final = 50
_ACTIVE: Final = (JobStatus.QUEUED, JobStatus.RUNNING)
# Потоковое слияние находок вопроса: как `_COMPACT_AT` / `_COMPACT_KEEP` в doc_search.
_COMPACT_AT: Final = 2000
_COMPACT_KEEP: Final = 500
_MM_KINDS: Final = (DocValueKind.LENGTH_MM, DocValueKind.RANGE_MM, DocValueKind.SECTION_MM)
# Кандидаты из уровней по разрезам: принятый человеком выше любой текстовой находки (при равных
# очках выигрывает меньший `source_rank`), непринятый - средняя оценка.
SECTION_SOURCE_LABEL: Final = "Уровни по разрезам АР"
SECTION_ACCEPTED_SCORE: Final = 100
SECTION_CANDIDATE_SCORE: Final = 60
_SECTION_ACCEPTED_RANK: Final = -1
_SECTION_LISTED_ELEVATIONS: Final = 3


# --------------------------------------------------------------------------- значения


def value_to_json(value: DocValue) -> dict[str, Any]:
    return {
        "kind": value.kind.value,
        "display": value.display,
        "numbers": list(value.numbers),
        "qualifier": value.qualifier,
        "code": value.code,
    }


def value_text_of(value: dict[str, Any]) -> str:
    """Строка для показа: единица мм у размерных значений и «не менее / не более»."""
    display = str(value.get("display", ""))
    if value.get("kind") not in {kind.value for kind in _MM_KINDS}:
        return display
    prefix = {"min": "не менее ", "max": "не более "}.get(str(value.get("qualifier")), "")
    return f"{prefix}{display} мм"


def value_key(value: dict[str, Any]) -> str:
    """Канонический вид значения: по нему кандидат узнаётся при повторном поиске."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _no_nul(text: str) -> str:
    """PostgreSQL не принимает 0x00 ни в text, ни в jsonb."""
    return text.replace("\x00", "")


def _level_text(level_from: str | None, level_to: str | None) -> str | None:
    if level_from and level_to and level_from != level_to:
        return f"{level_from} - {level_to}"
    return level_from or level_to or None


# --------------------------------------------------------------------------- постановка


async def schedule_search(session: AsyncSession, *, project: Project) -> Job:
    """Ставит задание поиска; уже есть активное - возвращает его.

    Строка проекта берётся под блокировкой: два нажатия подряд не ставят задание дважды.
    """
    await session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    active = await session.scalar(
        select(Job)
        .where(
            Job.job_type == JobType.DOC_QUESTIONS_SEARCH,
            Job.project_id == project.id,
            Job.status.in_(_ACTIVE),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if active is not None:
        return active
    return await jobs_service.enqueue(
        session,
        job_type=JobType.DOC_QUESTIONS_SEARCH,
        workspace_id=project.workspace_id,
        project_id=project.id,
        payload={"project_id": str(project.id)},
    )


# --------------------------------------------------------------------------- исполнитель


class _Collector:
    """Находки по вопросам с усечением: память ограничена, порядок входа на итог не влияет."""

    def __init__(self) -> None:
        self._by_question: dict[str, list[DocCandidate]] = defaultdict(list)

    def add(self, candidates: Iterable[DocCandidate]) -> None:
        for candidate in candidates:
            bucket = self._by_question[candidate.question.value]
            bucket.append(candidate)
            if len(bucket) > _COMPACT_AT:
                self._by_question[candidate.question.value] = rank_candidates(bucket, _COMPACT_KEEP)

    def merge(self, other: _Collector) -> None:
        for items in other._by_question.values():
            self.add(rank_candidates(items, _COMPACT_KEEP))

    def top(self, code: str, count: int) -> list[DocCandidate]:
        return rank_candidates(self._by_question.get(code, []), count)


def _passport_of(row: SheetPassport) -> PassportCandidate:
    try:
        kind = None if row.sheet_kind is None else SheetKind(row.sheet_kind)
    except ValueError:
        kind = None
    return PassportCandidate(
        page_index=row.page_index,
        section_mark=row.section_mark,
        sheet_kind=kind,
        building=row.building,
        section=row.section,
        level_from=row.level_from,
        level_to=row.level_to,
    )


async def _passports_of(
    session: AsyncSession, revision_id: uuid.UUID
) -> dict[int, PassportCandidate]:
    """Паспорта страниц ревизии; отклонённый человеком паспорт - как будто его нет."""
    rows = await session.scalars(
        select(SheetPassport).where(
            SheetPassport.revision_id == revision_id, SheetPassport.status != "rejected"
        )
    )
    return {row.page_index: _passport_of(row) for row in rows}


async def _scan_revision(
    storage: ObjectStorage,
    *,
    storage_key: str,
    max_bytes: int,
    revision_id: uuid.UUID,
    file_name: str,
    passports: dict[int, PassportCandidate],
) -> _Collector:
    """Постраничный поиск по одной ревизии; бросает PageTextError / ObjectNotFoundError."""
    collector = _Collector()
    customer: bool | None = None
    async for page in iter_page_texts(storage, storage_key, max_bytes=max_bytes):
        if customer is None:
            # Договор и ТЗ опознаются по заголовку первой страницы, а применяются ко всем.
            customer = is_customer_document(file_name, page.text)
        search = DocSearchPage(
            file_name=file_name,
            page_index=page.page_index,
            text=page.text,
            revision_id=str(revision_id),
            label=page.label,
            passport=passports.get(page.page_index),
            is_customer_doc=customer,
        )
        # Регулярки на больших страницах - в потоке, чтобы не держать цикл событий.
        collector.add(await asyncio.to_thread(search_page, search))
    return collector


async def _rejected_keys(
    session: AsyncSession, project_id: uuid.UUID
) -> tuple[set[tuple[str, uuid.UUID, int, str]], dict[str, int]]:
    rows = await session.execute(
        select(
            DocQuestionCandidate.question_code,
            DocQuestionCandidate.revision_id,
            DocQuestionCandidate.page_index,
            DocQuestionCandidate.value,
        ).where(
            DocQuestionCandidate.project_id == project_id,
            DocQuestionCandidate.status == "rejected",
        )
    )
    keys: set[tuple[str, uuid.UUID, int, str]] = set()
    per_question: dict[str, int] = defaultdict(int)
    for code, revision_id, page_index, value in rows:
        keys.add((code, revision_id, page_index, value_key(value)))
        per_question[code] += 1
    return keys, per_question


def _row_of(
    project_id: uuid.UUID, candidate: DocCandidate, value: dict[str, Any]
) -> DocQuestionCandidate:
    return DocQuestionCandidate(
        project_id=project_id,
        question_code=candidate.question.value,
        catalog_version=DOC_QUESTIONS_VERSION,
        value_kind=candidate.value.kind.value,
        value=value,
        value_text=_no_nul(value_text_of(value)),
        quote=_no_nul(candidate.quote),
        revision_id=uuid.UUID(str(candidate.revision_id)),
        page_index=candidate.page_index,
        page_label=None if candidate.page_label is None else _no_nul(candidate.page_label),
        file_name=_no_nul(candidate.file_name),
        building=candidate.scope.building,
        section=candidate.scope.section,
        level=_level_text(candidate.scope.level_from, candidate.scope.level_to),
        score=candidate.score,
        occurrences=candidate.occurrences,
        status="candidate",
        versions=doc_search_versions(),
    )


def _elevation_text(elevation_mm: int) -> str:
    return f"{elevation_mm / 1000:+.3f}"


def _clear_height_of(level: CadSectionLevel) -> int | None:
    return level.clear_height_mm


def _slab_thickness_of(level: CadSectionLevel) -> int | None:
    return level.structure_mm


def _common(values: Iterable[str | None]) -> str | None:
    """Единственное общее значение метки (корпус, секция); разные или пустые - None."""
    distinct = set(values)
    return distinct.pop() if len(distinct) == 1 else None


def section_level_candidates(
    levels: Sequence[tuple[CadSectionLevel, str]],
) -> list[DocCandidate]:
    """Кандидаты `clear_height` и `slab_thickness` из уровней по разрезам; отклонённые не берутся.

    Одно значение - один кандидат: отметки уровней перечисляются в цитате, ссылка (ревизия,
    страница) - на первый принятый уровень значения, а если принятых нет - на первый по порядку.
    Принят хотя бы один уровень значения - кандидат с высокой оценкой, иначе со средней. Значения
    вне границ вопроса отбрасываются. `levels` - пары (уровень, имя файла ревизии).
    """
    fields: tuple[tuple[DocQuestionCode, str, Callable[[CadSectionLevel], int | None]], ...] = (
        (DocQuestionCode.CLEAR_HEIGHT, "высота в свету", _clear_height_of),
        (DocQuestionCode.SLAB_THICKNESS, "толщина плиты перекрытия", _slab_thickness_of),
    )
    result: list[DocCandidate] = []
    for code, label, getter in fields:
        question = question_by_code(code)
        groups: dict[int, list[tuple[CadSectionLevel, str]]] = {}
        for pair in levels:
            level = pair[0]
            mm = getter(level)
            if level.status == "rejected" or mm is None:
                continue
            if question.min_mm <= mm <= question.max_mm:
                groups.setdefault(mm, []).append(pair)
        for mm, group in groups.items():
            accepted = [pair for pair in group if pair[0].status == "accepted"]
            reference, file_name = (accepted or group)[0]
            elevations = list(dict.fromkeys(pair[0].elevation_mm for pair in group))
            listed = ", ".join(_elevation_text(e) for e in elevations[:_SECTION_LISTED_ELEVATIONS])
            more = " и др." if len(elevations) > _SECTION_LISTED_ELEVATIONS else ""
            head = f"Разрез, отм. {listed}{more}: {label} "
            quote = f"{head}{mm} мм (уровней: {len(group)})"
            result.append(
                DocCandidate(
                    question=code,
                    value=DocValue(DocValueKind.LENGTH_MM, str(mm), (mm,), None, None),
                    quote=quote,
                    quote_focus=len(head),
                    file_name=file_name,
                    revision_id=str(reference.revision_id),
                    page_index=reference.page_index,
                    page_label=None,
                    source_label=SECTION_SOURCE_LABEL,
                    source_rank=_SECTION_ACCEPTED_RANK if accepted else 0,
                    section_mark="АР",
                    sheet_kind=SheetKind.SECTION,
                    scope=DocScope(
                        building=_common(pair[0].corps for pair in group),
                        section=_common(pair[0].section for pair in group),
                    ),
                    score=SECTION_ACCEPTED_SCORE if accepted else SECTION_CANDIDATE_SCORE,
                    occurrences=len(group),
                )
            )
    return result


async def _section_levels(
    session: AsyncSession, project_id: uuid.UUID, *, skip_revisions: set[uuid.UUID]
) -> list[tuple[CadSectionLevel, str]]:
    """Не отклонённые уровни проекта с именем файла ревизии; ревизии из `skip_revisions` пропущены.

    Нечитаемую ревизию пропускаем: её прежние кандидаты остаются в базе, дубль не нужен.
    """
    rows = await session.execute(
        select(CadSectionLevel, DocumentRevision.source_filename)
        .join(DocumentRevision, DocumentRevision.id == CadSectionLevel.revision_id)
        .where(CadSectionLevel.project_id == project_id, CadSectionLevel.status != "rejected")
        .order_by(CadSectionLevel.revision_id, CadSectionLevel.page_index, CadSectionLevel.seq)
        .execution_options(populate_existing=True)
    )
    return [
        (level, file_name)
        for level, file_name in rows.tuples()
        if level.revision_id not in skip_revisions
    ]


async def _replace_candidates(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    collector: _Collector,
    keep_revisions: set[uuid.UUID],
) -> tuple[int, int]:
    """Заменяет кандидатов проекта новыми; возвращает (вопросов с находками, кандидатов).

    Кандидаты нечитаемых сейчас ревизий остаются: их тексты не перепроверены, терять нечего.
    """
    rejected, rejected_count = await _rejected_keys(session, project_id)
    stale = delete(DocQuestionCandidate).where(
        DocQuestionCandidate.project_id == project_id, DocQuestionCandidate.status == "candidate"
    )
    if keep_revisions:
        stale = stale.where(DocQuestionCandidate.revision_id.not_in(list(keep_revisions)))
    await session.execute(stale)
    collector.add(
        section_level_candidates(
            await _section_levels(session, project_id, skip_revisions=keep_revisions)
        )
    )
    found = total = 0
    for question in DOC_QUESTIONS:
        code = question.code.value
        # Отклонённый кандидат занимает место в рейтинге, поэтому берём с запасом на отказы.
        ranked = collector.top(code, DEFAULT_TOP_N + rejected_count.get(code, 0))
        fresh: list[DocQuestionCandidate] = []
        for candidate in ranked:
            value = value_to_json(candidate.value)
            revision_id = uuid.UUID(str(candidate.revision_id))
            if (code, revision_id, candidate.page_index, value_key(value)) in rejected:
                continue
            fresh.append(_row_of(project_id, candidate, value))
        fresh = fresh[:DEFAULT_TOP_N]
        session.add_all(fresh)
        found += 1 if fresh else 0
        total += len(fresh)
    await session.flush()
    return found, total


async def execute_doc_questions_search(
    session: AsyncSession, job: Job, *, storage: ObjectStorage, settings: Settings
) -> Job:
    """Тело задания `doc_questions_search`: кандидаты-ответы по тексту страниц PDF проекта.

    Ревизии идут по одной, после каждой - коммит прогресса. Ревизия без сохранённого текста
    (`no_text`: паспорта листов не разбирались) и ревизия, текст которой не читается, задание не
    валят: они попадают в итог счётчиком и именами файлов (до 50). Содержимое документов в итог
    и журнал не попадает.
    """
    try:
        project_id = uuid.UUID(str(job.payload.get("project_id")))
    except ValueError:
        return await jobs_service.fail(
            session,
            job=job,
            error_code=SEARCH_FAILED_CODE,
            error_message="в задании нет ссылки на проект",
        )

    await jobs_service.start(session, job=job, stage="search")
    revisions = await latest_pdf_revisions(session, project_id=project_id)
    stored = {
        row.revision_id: row
        for row in await session.scalars(
            select(RevisionPageText).where(
                RevisionPageText.project_id == project_id,
                RevisionPageText.format == PAGE_TEXT_FORMAT,
            )
        )
    }
    await session.commit()

    max_bytes = settings.sheet_passport_page_text_max_mb * 1024 * 1024
    collector = _Collector()
    scanned = 0
    no_text: list[str] = []
    no_text_count = 0
    unreadable: list[str] = []
    unreadable_count = 0
    keep: set[uuid.UUID] = set()
    total = len(revisions)
    for number, revision in enumerate(revisions, start=1):
        file_name = revision.source_filename
        text_row = stored.get(revision.id)
        if text_row is None:
            no_text_count += 1
            if len(no_text) < MAX_REPORTED_FILES:
                no_text.append(file_name)
        else:
            # Отказ базы - не «файл не читается»: он не перехватывается и валит задание.
            passports = await _passports_of(session, revision.id)
            try:
                found = await _scan_revision(
                    storage,
                    storage_key=text_row.storage_key,
                    max_bytes=max_bytes,
                    revision_id=revision.id,
                    file_name=file_name,
                    passports=passports,
                )
            except Exception as error:  # PageTextError, ObjectNotFoundError и сбои разбора
                reason = type(error).__name__
                log.warning("doc_questions_revision_failed", job_id=str(job.id), reason=reason)
                unreadable_count += 1
                keep.add(revision.id)
                if len(unreadable) < MAX_REPORTED_FILES:
                    unreadable.append(file_name)
            else:
                collector.merge(found)
                scanned += 1
        await jobs_service.report_progress(session, job=job, progress=number / total)
        await session.commit()

    questions_found, candidates = await _replace_candidates(
        session, project_id=project_id, collector=collector, keep_revisions=keep
    )
    log.info(
        "doc_questions_search_finished",
        job_id=str(job.id),
        revisions_scanned=scanned,
        revisions_no_text=no_text_count,
        revisions_unreadable=unreadable_count,
        candidates=candidates,
    )
    result = await jobs_service.succeed(
        session,
        job=job,
        payload={
            "revisions_total": total,
            "revisions_scanned": scanned,
            "revisions_no_text": no_text_count,
            "no_text_files": no_text,
            "revisions_unreadable": unreadable_count,
            "unreadable_files": unreadable,
            "questions_found": questions_found,
            "candidates": candidates,
            "versions": doc_search_versions(),
        },
    )
    await session.commit()
    return result


# --------------------------------------------------------------------------- итог поиска


def _payload_int(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _payload_names(payload: dict[str, Any], key: str) -> list[str]:
    raw = payload.get(key)
    return [str(item) for item in raw] if isinstance(raw, list) else []


def _payload_versions(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("versions")
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


async def latest_search_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> DocSearchSummary | None:
    """Последнее задание поиска проекта с итогом из его payload; заданий не было - None."""
    job = await session.scalar(
        select(Job)
        .where(
            Job.workspace_id == workspace_id,
            Job.project_id == project_id,
            Job.job_type == JobType.DOC_QUESTIONS_SEARCH,
        )
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    if job is None:
        return None
    payload: dict[str, Any] = job.payload if isinstance(job.payload, dict) else {}
    return DocSearchSummary(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        stage=job.stage,
        error_code=job.error_code,
        created_at=job.created_at,
        finished_at=job.finished_at,
        questions_found=_payload_int(payload, "questions_found"),
        candidates=_payload_int(payload, "candidates"),
        revisions_total=_payload_int(payload, "revisions_total"),
        revisions_scanned=_payload_int(payload, "revisions_scanned"),
        revisions_no_text=_payload_int(payload, "revisions_no_text"),
        no_text_files=_payload_names(payload, "no_text_files"),
        revisions_unreadable=_payload_int(payload, "revisions_unreadable"),
        unreadable_files=_payload_names(payload, "unreadable_files"),
        versions=_payload_versions(payload),
    )
