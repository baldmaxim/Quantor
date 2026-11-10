"""Отдельный исполнитель PDF -> CAD (QA-контур).

Берёт только `cad_pdf_convert` и `cad_mep_route`: свой реестр передаётся общему `Worker`, захват
фильтруется по нему, и основной `python -m app.worker` эти типы не трогает. Движок и генератор
трасс - подпроцессы в своём окружении (`tools/cad_engine`, `tools/cad_mep`); в этом пакете они
не импортируются.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.cad_worker.handler import execute_cad_pdf_convert
from app.cad_worker.mep_handler import execute_cad_mep_route
from app.domain import JobType
from app.worker.registry import JobHandler

HANDLERS: Final[MappingProxyType[JobType, JobHandler]] = MappingProxyType(
    {
        JobType.CAD_PDF_CONVERT: execute_cad_pdf_convert,
        JobType.CAD_MEP_ROUTE: execute_cad_mep_route,
    }
)
