"""Вход классификации внутриквартирных перегородок: ответ «Вопросов к документации» и зоны листа.

Высоту маячного ряда (ПЗ АР: перегородки выкладываются «маячным рядом» высотой 188 мм, на всю
высоту их возводит собственник) принимает человек в «Вопросах к документации»; здесь читается
последний принятый ответ проекта и переводятся в мм DXF зоны помещений листа (квартиры и МОП) по
кадру вида - тем же кодом, что у зон двери 3D-вида. Классификация и выбор высоты - чистые функции
`cad_constructions`. Модель чисел не выдаёт; ответ `norm_assumption` и «в проекте нет» не берутся.
Нет кадра вида или зон - зон нет, причина видна как предупреждение `apartment_zones_missing`.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ErrorCode, http_error
from app.models import DocQuestionAnswer, Job
from app.services import cad as cad_service
from app.services import cad_floor3d, cad_views, cad_zones
from app.services.cad_constructions import PartitionContext, PartitionHeight, PartitionZone
from app.services.consistency.doc_questions import DocQuestionCode, question_by_code
from app.storage.base import ObjectNotFoundError, ObjectStorage, StorageUnavailableError

ROOM_KINDS: Final = ("room_apartment", "room_mop")
# Ответы, которые считаются подтверждёнными данными проекта; `document` - прочитано из документа.
_ANSWER_SOURCES: Final = ("document", "manual")


def _first_number(value: Any) -> int | None:
    numbers = value.get("numbers") if isinstance(value, dict) else None
    if not isinstance(numbers, list) or not numbers:
        return None
    first = numbers[0]
    return first if isinstance(first, int) and not isinstance(first, bool) else None


async def apartment_partition_height(
    session: AsyncSession, *, project_id: uuid.UUID
) -> PartitionHeight | None:
    """Последний принятый ответ проекта «высота маячного ряда»; нет ответа или число вне пределов -
    `None`. Происхождение: из документа - `observed`, введено человеком - `manual`."""
    question = question_by_code(DocQuestionCode.APARTMENT_PARTITION_HEIGHT)
    rows = await session.scalars(
        select(DocQuestionAnswer)
        .where(
            DocQuestionAnswer.project_id == project_id,
            DocQuestionAnswer.question_code == question.code.value,
            DocQuestionAnswer.source.in_(_ANSWER_SOURCES),
            DocQuestionAnswer.value.is_not(None),
        )
        .order_by(DocQuestionAnswer.confirmed_at.desc(), DocQuestionAnswer.id)
        .execution_options(populate_existing=True)
    )
    for row in rows:
        number = _first_number(row.value)
        if number is None or not question.min_mm <= number <= question.max_mm:
            continue
        return PartitionHeight(
            height_mm=number,
            source="observed" if row.source == "document" else "manual",
            answer_id=row.id,
            file_name=row.file_name,
            page_index=row.page_index,
            quote=row.quote,
        )
    return None


async def _artifact_json(
    storage: ObjectStorage, parent: Job, revision_id: uuid.UUID, attempt: int, name: str
) -> Any:
    artifact = cad_service.find_artifact(parent, name, attempt)
    if artifact is None:
        return None
    key = cad_service.artifact_storage_key(revision_id, parent.id, attempt, name)
    if artifact.get("key") != key:
        return None
    try:
        return await cad_views.read_json(storage, key)
    except ObjectNotFoundError:
        return None
    except StorageUnavailableError as error:
        raise http_error(ErrorCode.STORAGE_UNAVAILABLE) from error
    except (cad_views.ArtifactTooLargeError, ValueError):
        return None


async def sheet_partition_zones(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    parent: Job,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> list[PartitionZone]:
    """Зоны квартир и МОП листа в мм DXF вида; нет зон, кадра или геометрии страницы - пусто."""
    rows = [
        zone
        for zone in await cad_zones.list_zones(
            session, revision_id=revision_id, page_index=page_index
        )
        if zone.kind in ROOM_KINDS and len(zone.points) >= 3
    ]
    if not rows:
        return []
    attempt = cad_service.current_result(parent).get("attempt")
    if type(attempt) is not int:
        return []
    folder = cad_service.view_folder(page_index, view)
    scale = cad_views.scale_from(
        await _artifact_json(storage, parent, revision_id, attempt, f"{folder}/scale.json")
    )
    checks = await _artifact_json(
        storage, parent, revision_id, attempt, f"{folder}/cad_checks.json"
    )
    frame = cad_views.frame_from(scale, checks)
    page = (
        await cad_zones.page_scales(session, revision_id=revision_id, page_indexes={page_index})
    ).get(page_index)
    geometry = None if page is None else page.geometry
    origin = frame.origin_pt
    factor = frame.mm_per_pdf_point
    if not frame.confirmed or geometry is None or origin is None or factor is None:
        return []
    result: list[PartitionZone] = []
    for zone in rows:
        mapped = cad_floor3d.room_zones_to_mm(
            [cad_floor3d.RoomZoneNormalized(zone.kind, [list(p) for p in zone.points])],
            page_width_pt=float(geometry.display_width_pt),
            page_height_pt=float(geometry.display_height_pt),
            origin_pt=origin,
            mm_per_pdf_point=factor,
        )
        if mapped:
            result.append(
                PartitionZone(
                    kind=zone.kind,
                    apartment_no=zone.apartment_no,
                    shell=[[x, y] for x, y in mapped[0].shell],
                )
            )
    return result


async def load_partition_context(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    project_id: uuid.UUID,
    parent: Job,
    revision_id: uuid.UUID,
    page_index: int,
    view: int,
) -> PartitionContext:
    """Высота маячного ряда проекта и зоны помещений листа: вход расчёта и 3D этажа."""
    height = await apartment_partition_height(session, project_id=project_id)
    zones = await sheet_partition_zones(
        session,
        storage,
        parent=parent,
        revision_id=revision_id,
        page_index=page_index,
        view=view,
    )
    return PartitionContext(zones=zones, height=height)
