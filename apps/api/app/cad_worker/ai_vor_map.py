"""Сопоставление позиций ВОР Заказчика с объектами Quantor моделью Claude (ручной запуск).

В пакет для модели идут только текстовые описания: позиции ВОР (id, строка, код, наименование,
единица, раздел) и объекты Quantor (ключ, вид, описание, названия единиц, листы-источники).
Количества Заказчика и Quantor в пакет не попадают, от модели числа не принимаются. Результат -
предложения связей; связь создаёт человек существующим запросом связей.

Какие позиции ВОР идут в пакет: единица измерения распознана движком (`vor_fill.normalize_unit`,
иначе позиция не сводится к объекту) и позиция относится к конструктиву, дверям или отделке - есть
подсказка вида (`kind_hint`) либо слова наименования (двери и поверхности отделки из `vor_fill`
плюс слова конструктива ниже). Объекты - тот же расчёт, что у `GET /vor/fill`.
"""

import json
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cad_worker.ai_vor_map_cli import PACKAGE_FILES
from app.cad_worker.handler import CadError, _run_while_owned, _still_owned
from app.contracts.ai_vor_map import (
    MAX_VOR_ITEMS,
    MAX_VOR_OBJECTS,
    AiVorMapReport,
    AiVorMapResult,
)
from app.contracts.cad_ai_review import AiLoopPilot, AiUsage
from app.contracts.vor_fill import VorObjectRead, VorQuantityUnit
from app.core.config import Settings
from app.domain import JobStatus, JobType
from app.errors import DomainError, ErrorCode
from app.models import AiPromptVersion, CadVorDocument, CadVorItem, Job
from app.services import cad, jobs, vor_fill
from app.storage.base import ObjectStorage

log = structlog.get_logger(__name__)
_CLI = Path(__file__).with_name("ai_vor_map_cli.py")
_MAX_REPORT_BYTES = 512 * 1024
_MAX_NAME = 400
_MAX_SOURCES = 20
ROLE: Final = "vor_mapper"
CONSTRUCTION_WORDS: Final = (
    "кладк",
    "перегород",
    "монолит",
    "бетон",
    "блок",
    "кирпич",
    "перемыч",
    "плит",
    "колонн",
    "пилон",
    "стен",
    "гкл",
    "гипсокартон",
    "шахт",
    "лестнич",
    "отделк",
)
_RELEVANT_WORDS: Final = (
    *vor_fill.DOOR_WORDS,
    *(word for words in vor_fill.SURFACE_WORDS.values() for word in words),
    *CONSTRUCTION_WORDS,
)
_UNIT_NAMES: Final[Mapping[VorQuantityUnit, str]] = {
    "m3": "м³",
    "m2": "м²",
    "m": "м",
    "pcs": "шт",
}
_KIND_NAMES: Final[Mapping[str, str]] = {
    "construction": "конструкция",
    "door": "дверь",
    "finish": "отделка",
}


def pilot_for_project(project_id: uuid.UUID, settings: Settings) -> AiLoopPilot | None:
    """Пилот ИИ из настройки `cad_ai_loop`, если он включён для этого проекта; иначе None."""
    if not settings.cad_ai_loop:
        return None
    try:
        pilot = AiLoopPilot.model_validate_json(settings.cad_ai_loop)
    except ValidationError:
        log.error("cad_ai_loop_pilot_invalid")
        return None
    return pilot if pilot.project_id == project_id else None


def is_relevant(item: CadVorItem) -> bool:
    if vor_fill.normalize_unit(item.unit) is None:
        return False
    return item.kind_hint is not None or any(word in item.name_norm for word in _RELEVANT_WORDS)


async def select_items(session: AsyncSession, document_id: uuid.UUID) -> list[CadVorItem]:
    rows = await session.scalars(
        select(CadVorItem)
        .where(CadVorItem.document_id == document_id)
        .order_by(CadVorItem.sheet, CadVorItem.row_no)
    )
    return [item for item in rows if is_relevant(item)]


def package_item(item: CadVorItem) -> dict[str, Any]:
    """Позиция для модели: белый список полей, без количества."""
    return {
        "id": str(item.id),
        "row": item.row_no,
        "sheet": item.sheet,
        "code": item.code,
        "name": item.name[:_MAX_NAME],
        "unit": item.unit,
        "section": None if item.section is None else item.section[:_MAX_NAME],
    }


def object_kind(obj: VorObjectRead) -> str:
    if obj.kind == "construction" and obj.group_key.endswith("|lintel"):
        return "перемычка"
    return _KIND_NAMES[obj.kind]


def package_object(obj: VorObjectRead) -> dict[str, Any]:
    """Объект для модели: названия единиц без значений, листы-источники без заданий."""
    labels = list(dict.fromkeys(source.label for source in obj.sources))[:_MAX_SOURCES]
    return {
        "group_key": obj.group_key,
        "kind": object_kind(obj),
        "description": obj.title,
        "units": [_UNIT_NAMES[quantity.unit] for quantity in obj.quantities],
        "sources": labels,
    }


def sanitize_report(
    report: AiVorMapReport, item_ids: set[str], group_keys: set[str]
) -> tuple[AiVorMapReport, list[str]]:
    """Отбрасывает чужие позиции и ключи объектов; что отброшено - строками для результата."""
    dropped: list[str] = []
    merged: dict[str, dict[str, Any]] = {}
    foreign_items = foreign_keys = empty = 0
    for match in report.matches:
        if match.vor_item_id not in item_ids:
            foreign_items += 1
            continue
        keys = list(dict.fromkeys(key for key in match.group_keys if key in group_keys))
        foreign_keys += len(match.group_keys) - sum(1 for key in match.group_keys if key in keys)
        if not keys:
            empty += 1
            continue
        entry = merged.get(match.vor_item_id)
        if entry is None:
            merged[match.vor_item_id] = {"match": match, "keys": keys}
        else:
            entry["keys"] = list(dict.fromkeys([*entry["keys"], *keys]))[:50]
    matches = [
        entry["match"].model_copy(update={"group_keys": entry["keys"]}) for entry in merged.values()
    ]
    unmatched = [row for row in report.unmatched_objects if row.group_key in group_keys]
    foreign_unmatched = len(report.unmatched_objects) - len(unmatched)
    if foreign_items:
        dropped.append(f"Отброшено сопоставлений с позициями вне пакета: {foreign_items}")
    if foreign_keys:
        dropped.append(f"Отброшено ключей объектов вне пакета: {foreign_keys}")
    if empty:
        dropped.append(f"Отброшено сопоставлений без объектов: {empty}")
    if foreign_unmatched:
        dropped.append(f"Отброшено объектов вне пакета в unmatched_objects: {foreign_unmatched}")
    clean = report.model_copy(update={"matches": matches, "unmatched_objects": unmatched})
    return clean, dropped


async def latest_job(session: AsyncSession, project_id: uuid.UUID) -> Job | None:
    rows = await session.scalars(
        select(Job)
        .where(Job.job_type == JobType.CAD_AI_VOR_MAP, Job.project_id == project_id)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    )
    return rows.first()


async def enqueue_for_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    settings: Settings,
    document: CadVorDocument | None,
    objects: Sequence[VorObjectRead],
) -> Job:
    """Ручной запуск; идущее задание не дублируется. Нет пилота, ВОР или данных - 409."""
    pilot = pilot_for_project(project_id, settings)
    if pilot is None:
        raise DomainError(
            ErrorCode.CAD_RESULT_NOT_READY, "ИИ-сопоставление недоступно для этого проекта"
        )
    last = await latest_job(session, project_id)
    if last is not None and last.status in (JobStatus.QUEUED, JobStatus.RUNNING):
        return last
    if document is None:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "ВОР Заказчика не загружен")
    if not objects:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY, "В проекте нет объектов Quantor")
    if len(objects) > MAX_VOR_OBJECTS:
        raise DomainError(
            ErrorCode.CAD_RESULT_NOT_READY,
            f"Объектов Quantor {len(objects)}, больше допустимых {MAX_VOR_OBJECTS}",
        )
    items = await select_items(session, document.id)
    if not items:
        raise DomainError(
            ErrorCode.CAD_RESULT_NOT_READY, "В ВОР нет позиций конструктива, дверей и отделки"
        )
    if len(items) > MAX_VOR_ITEMS:
        raise DomainError(
            ErrorCode.CAD_RESULT_NOT_READY,
            f"Подходящих позиций ВОР {len(items)}, больше допустимых {MAX_VOR_ITEMS}",
        )
    payload: dict[str, Any] = {
        "document_id": str(document.id),
        "item_ids": [str(item.id) for item in items],
        "objects": [package_object(obj) for obj in objects],
        "model": pilot.model,
    }
    return await jobs.enqueue(
        session,
        job_type=JobType.CAD_AI_VOR_MAP,
        project_id=project_id,
        workspace_id=workspace_id,
        idempotency_key=f"cad-ai-vor-map:v1:{project_id}:{uuid.uuid4().hex}",
        payload=payload,
    )


async def _prepare(session: AsyncSession, job: Job, root: Path) -> dict[str, Any]:
    payload = job.payload
    document = await session.get(CadVorDocument, uuid.UUID(payload["document_id"]))
    if document is None or document.project_id != job.project_id:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Документ ВОР недоступен")
    wanted = [uuid.UUID(raw) for raw in payload["item_ids"]]
    rows = await session.scalars(
        select(CadVorItem)
        .where(CadVorItem.document_id == document.id, CadVorItem.id.in_(wanted))
        .order_by(CadVorItem.sheet, CadVorItem.row_no)
    )
    items = [package_item(item) for item in rows]
    if len(items) != len(wanted) or not items:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Позиции ВОР изменились: запустите заново")
    prompt = await session.scalar(
        select(AiPromptVersion).where(
            AiPromptVersion.role == ROLE, AiPromptVersion.status == "active"
        )
    )
    if prompt is None:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Нет активного промта «сопоставление ВОР»")
    prompt_ref: dict[str, Any] = {
        "prompt_version_id": str(prompt.id),
        "prompt_version": prompt.version,
    }
    job.payload = {**job.payload, **prompt_ref}
    # Текст дословно, без перекодирования: по этим байтам считается prompt_sha256.
    (root / "prompt.txt").write_bytes(prompt.text.encode())
    (root / "vor_items.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (root / "objects.json").write_text(
        json.dumps(payload["objects"], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    manifest = {
        "schema": "quantor.cad_ai_vor_map.v1",
        "project_id": str(job.project_id),
        "document_id": payload["document_id"],
        "model": payload["model"],
        "role": ROLE,
        "items_count": len(items),
        "objects_count": len(payload["objects"]),
        **prompt_ref,
    }
    (root / "manifest.json").write_bytes(cad.params_bytes(manifest))
    (root / "schema.json").write_text(
        json.dumps(AiVorMapReport.model_json_schema(), ensure_ascii=False), encoding="utf-8"
    )
    missing = [name for name in PACKAGE_FILES if not (root / name).is_file()]
    if missing:
        raise CadError(ErrorCode.CAD_INPUT_INVALID, "Пакет сопоставления неполон")
    return manifest


async def execute_ai_vor_map(
    session: AsyncSession, job: Job, storage: ObjectStorage, settings: Settings
) -> Job:
    owner, attempt = job.worker_id, job.attempt
    await jobs.start(session, job=job, stage="cad_ai_vor_map")
    await session.commit()
    try:
        if not settings.cad_review_ssh_config or not settings.cad_engine_python:
            raise CadError(ErrorCode.CAD_ENGINE_UNAVAILABLE, "SSH для сопоставления не настроен")
        with tempfile.TemporaryDirectory(prefix="quantor-ai-vor-map-") as directory:
            root = Path(directory)
            manifest = await _prepare(session, job, root)
            await session.commit()
            if not await _still_owned(session, job, owner, attempt):
                return job
            timeout = settings.cad_ai_timeout_seconds
            outcome = await _run_while_owned(
                session,
                job,
                owner,
                attempt,
                [
                    settings.cad_engine_python,
                    "-I",
                    str(_CLI),
                    directory,
                    settings.cad_review_ssh_config,
                    str(timeout),
                ],
                limit_seconds=timeout + 60,
                poll_interval=settings.worker_heartbeat_interval_seconds,
                memory_limit_mb=settings.cad_max_memory_mb,
            )
            if outcome is None:
                return job
            code, _ = outcome
            if code == 124:
                raise CadError(ErrorCode.JOB_TIMEOUT, "Claude не уложился во время сопоставления")
            if code == 255:
                raise CadError(
                    ErrorCode.CAD_ENGINE_UNAVAILABLE, "Нет подключения по SSH к kg_claude"
                )
            if code != 0:
                log.warning("cad_ai_vor_map_process_failed", job_id=str(job.id), exit_code=code)
                raise CadError(
                    ErrorCode.CAD_ENGINE_FAILED,
                    "Сопоставление завершилось с ошибкой при подготовке пакета или вызове Claude",
                )
            with (root / "vor_map.json").open("rb") as report_file:
                raw_report = report_file.read(_MAX_REPORT_BYTES + 1)
            if len(raw_report) > _MAX_REPORT_BYTES:
                raise ValueError("Отчёт сопоставления больше допустимого")
            response = json.loads(raw_report)
            report, dropped = sanitize_report(
                AiVorMapReport.model_validate(response["report"]),
                {str(raw) for raw in job.payload["item_ids"]},
                {str(row["group_key"]) for row in job.payload["objects"]},
            )
            result = AiVorMapResult(
                document_id=uuid.UUID(manifest["document_id"]),
                model=str(response.get("model", manifest["model"])),
                prompt_version_id=uuid.UUID(manifest["prompt_version_id"]),
                prompt_version=manifest["prompt_version"],
                prompt_sha256=response["prompt_sha256"],
                bundle_sha256=response["bundle_sha256"],
                items_count=manifest["items_count"],
                objects_count=manifest["objects_count"],
                usage=AiUsage.model_validate(response.get("usage") or {}),
                report=report,
                dropped=dropped,
            )
    except (OSError, ValueError, KeyError, TypeError) as error:
        # ValidationError - подкласс ValueError.
        log.warning("cad_ai_vor_map_invalid", job_id=str(job.id), error=type(error).__name__)
        failure = CadError(
            ErrorCode.CAD_ENGINE_FAILED, "Не удалось подготовить или прочитать отчёт"
        )
    except CadError as error:
        failure = error
    else:
        if not await _still_owned(session, job, owner, attempt, lock=True):
            return job
        return await jobs.succeed(
            session, job=job, payload={"ai_vor_map": result.model_dump(mode="json")}
        )
    if await _still_owned(session, job, owner, attempt, lock=True):
        return await jobs.fail(
            session, job=job, error_code=failure.code.value, error_message=failure.message
        )
    return job
