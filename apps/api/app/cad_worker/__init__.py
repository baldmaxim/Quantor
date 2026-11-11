"""Отдельный исполнитель PDF -> CAD (QA-контур).

Берёт только `cad_pdf_convert`, `cad_mep_route`, `cad_walls` и `cad_floor3d_dxf`: свой реестр
передаётся общему `Worker`, захват фильтруется по нему, и основной `python -m app.worker` эти
типы не трогает.
Движок, генератор трасс, скрипт конструкций и выгрузка 3D DXF - подпроцессы в своём окружении
(`tools/cad_engine`, `tools/cad_mep`, `tools/cad_walls`); в этом пакете они не импортируются.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.cad_worker.floor3d_dxf_handler import execute_cad_floor3d_dxf
from app.cad_worker.handler import execute_cad_pdf_convert
from app.cad_worker.mep_handler import execute_cad_mep_route
from app.cad_worker.walls_handler import execute_cad_walls
from app.domain import JobType
from app.worker.registry import JobHandler

HANDLERS: Final[MappingProxyType[JobType, JobHandler]] = MappingProxyType(
    {
        JobType.CAD_PDF_CONVERT: execute_cad_pdf_convert,
        JobType.CAD_MEP_ROUTE: execute_cad_mep_route,
        JobType.CAD_WALLS: execute_cad_walls,
        JobType.CAD_FLOOR3D_DXF: execute_cad_floor3d_dxf,
    }
)
