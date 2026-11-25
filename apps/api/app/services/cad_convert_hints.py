"""Повторное преобразование страницы с подсказками из открытых замечаний (CAD, QA-контур).

Замечания `missing_wall` и `missing_door` превращаются в рамки поиска для движка. Параметры нового
задания - копия параметров исходного (масштаб или калибровка листа, профиль оформления, лимиты),
масштаб здесь не вычисляется. Рамка только указывает область; метры и площади считает движок.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from copy import deepcopy
from typing import Any, Final

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.cad_convert_hints import (
    MAX_CONVERT_HINTS,
    MAX_HINT_COMMENT_LENGTH,
    MAX_HINT_ID_LENGTH,
    CadConvertHint,
    CadConvertHints,
    CadHatchClass,
)
from app.core.config import Settings
from app.domain import JobType
from app.errors import DomainError, ErrorCode
from app.models import CadRemark, DocumentRevision, Job, Project
from app.services import cad as cad_service
from app.services import cad_remarks

HINT_REMARK_TYPES: Final = ("missing_wall", "missing_door")
OPEN_STATUS: Final = "open"


def hints_from_remarks(remarks: Sequence[CadRemark], page: int) -> CadConvertHints | None:
    """Открытые замечания двух типов -> подсказки страницы `page` (с 1); нет подходящих - None.

    Рамка с нулевой или перевёрнутой площадью пропускается; больше `MAX_CONVERT_HINTS` рамок -
    берутся первые по порядку замечаний.
    """
    hints: list[CadConvertHint] = []
    seen: set[str] = set()
    for remark in remarks:
        if remark.status != OPEN_STATUS or remark.type not in HINT_REMARK_TYPES:
            continue
        if remark.remark_key in seen or len(remark.remark_key) > MAX_HINT_ID_LENGTH:
            continue
        x0, x1 = sorted((remark.bbox_x0, remark.bbox_x1))
        y0, y1 = sorted((remark.bbox_y0, remark.bbox_y1))
        if not (x0 < x1 and y0 < y1):
            continue
        seen.add(remark.remark_key)
        hints.append(
            CadConvertHint.model_validate(
                {
                    "id": remark.remark_key,
                    "type": remark.type,
                    "bbox_pt": [x0, y0, x1, y1],
                    "comment": remark.comment[:MAX_HINT_COMMENT_LENGTH],
                }
            )
        )
        if len(hints) >= MAX_CONVERT_HINTS:
            break
    if not hints:
        return None
    return CadConvertHints(page=page, hints=hints)


def hatch_classes_of(job: Job) -> list[CadHatchClass]:
    """Классы подписей штриховки, с которыми выполнено преобразование; нет или битые - пусто."""
    params = job.payload.get("params")
    hints = params.get("convert_hints") if isinstance(params, dict) else None
    raw = hints.get("hatch_classes") if isinstance(hints, dict) else None
    if not isinstance(raw, list):
        return []
    try:
        return [CadHatchClass.model_validate(item) for item in raw]
    except ValidationError:
        return []


def _source_params(job: Job, page_index: int) -> dict[str, Any]:
    """Параметры исходного задания для одной страницы: те же масштаб, профиль и лимиты."""
    raw = job.payload.get("params")
    if not isinstance(raw, dict):
        raise DomainError(ErrorCode.CAD_PARAMS_INVALID, "У задания нет параметров преобразования")
    scales = raw.get("scales")
    scale = scales.get(str(page_index)) if isinstance(scales, dict) else None
    if not isinstance(scale, dict):
        raise DomainError(ErrorCode.CAD_PARAMS_INVALID, "Страница не входила в исходное задание")
    params = deepcopy(raw)
    params["pages"] = [page_index]
    params["scales"] = {str(page_index): scale}
    params.pop("convert_hints", None)
    return params


def reconvert_params(
    convert_job: Job,
    page_index: int,
    *,
    hints: Sequence[CadConvertHint],
    hatch_classes: Sequence[CadHatchClass],
) -> dict[str, Any]:
    """Параметры повторного преобразования страницы: копия исходных с новыми подсказками."""
    if convert_job.job_type is not JobType.CAD_PDF_CONVERT:
        raise DomainError(ErrorCode.CAD_PARAMS_INVALID, "Задание не является преобразованием PDF")
    params = _source_params(convert_job, page_index)
    params["convert_hints"] = CadConvertHints(
        page=page_index + 1, hints=list(hints), hatch_classes=list(hatch_classes)
    ).to_params()
    return params


async def enqueue_reconvert(
    session: AsyncSession, convert_job: Job, params: dict[str, Any], settings: Settings
) -> Job:
    """Ставит преобразование с готовыми параметрами; ключ идемпотентности - от параметров."""
    project = await session.get(Project, convert_job.project_id)
    revision = await session.get(
        DocumentRevision, uuid.UUID(str(convert_job.payload.get("revision_id")))
    )
    if project is None or revision is None:
        raise DomainError(ErrorCode.CAD_INPUT_INVALID, "Проект или ревизия задания не найдены")
    style = convert_job.payload.get("style_profile")
    return await cad_service.enqueue_convert(
        session,
        project=project,
        revision=revision,
        params=params,
        style_ref=style if isinstance(style, dict) else None,
        settings=settings,
    )


async def schedule_reconvert_by_remarks(
    session: AsyncSession,
    convert_job: Job,
    page_index: int,
    view: int,
    settings: Settings,
) -> Job:
    """Новое преобразование той же ревизии и страницы с подсказками из открытых замечаний вида.

    Классы подписей штриховки текущего преобразования сохраняются: иначе оформление, найденное
    ранее, пропало бы при перестроении по замечаниям.
    """
    if convert_job.job_type is not JobType.CAD_PDF_CONVERT:
        raise DomainError(ErrorCode.CAD_PARAMS_INVALID, "Задание не является преобразованием PDF")
    result = cad_service.current_result(convert_job)
    attempt = result.get("attempt")
    if type(attempt) is not int:
        raise DomainError(ErrorCode.CAD_RESULT_NOT_READY)
    remarks = await cad_remarks.list_remarks(
        session, job=convert_job, attempt=attempt, page_index=page_index, view=view
    )
    hints = hints_from_remarks(remarks, page_index + 1)
    if hints is None:
        raise DomainError(
            ErrorCode.CAD_PARAMS_INVALID,
            "У вида нет открытых замечаний «нет стены» или «нет двери» с ненулевой рамкой",
        )
    params = reconvert_params(
        convert_job, page_index, hints=hints.hints, hatch_classes=hatch_classes_of(convert_job)
    )
    return await enqueue_reconvert(session, convert_job, params, settings)
