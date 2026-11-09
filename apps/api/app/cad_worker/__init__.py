"""Отдельный исполнитель PDF -> CAD (QA-контур).

Берёт только `cad_pdf_convert`: свой реестр передаётся общему `Worker`, захват фильтруется
по нему, и основной `python -m app.worker` этот тип не трогает. Движок — подпроцесс runner
(`tools/cad_engine`) в своём окружении; в этом пакете он не импортируется.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.cad_worker.handler import execute_cad_pdf_convert
from app.domain import JobType
from app.worker.registry import JobHandler

HANDLERS: Final[MappingProxyType[JobType, JobHandler]] = MappingProxyType(
    {JobType.CAD_PDF_CONVERT: execute_cad_pdf_convert}
)
