"""Отдельный исполнитель PDF -> CAD (QA-контур).

Берёт только `cad_pdf_convert`, `cad_mep_route`, `cad_walls`, `cad_floor3d_dxf`, `cad_zones`,
`cad_outline_review` (проверка контуров, пилот ЖК Знаки), `cad_ai_review` (ИИ-проверка вида),
`cad_ai_vor_map` (сопоставление ВОР), `cad_sections`, `cad_facades` (виды фасадов, ADR-0048),
`cad_eom_route` (ЭОМ и СС этажа,
генератор `cad_eom`) и `cad_style_preview` (предпросмотр профиля оформления по образцам, ADR-0049,
runner `style`) и `model_ifc_import`
(модель здания из IFC, генератор `cad_model`):
свой реестр передаётся общему `Worker`, захват фильтруется по нему, и основной
`python -m app.worker` эти типы не трогает.
Движок, генератор трасс, скрипт конструкций и выгрузка 3D DXF - подпроцессы в своём окружении
(`tools/cad_engine` и генераторы `cad_mep`, `cad_walls` из репозитория движка по пину
`tools/cad_engine/pins.json`); в этом пакете они не импортируются.
Разметка зон - CLI `cad_mep/run_zones.py` тем же интерпретатором, рядом с генератором трасс;
уровни по разрезам - CLI `cad_mep/run_sections.py` там же.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from app.cad_worker.ai_review import execute_ai_review
from app.cad_worker.ai_vor_map import execute_ai_vor_map
from app.cad_worker.eom_handler import execute_cad_eom_route
from app.cad_worker.facades_handler import execute_cad_facades
from app.cad_worker.floor3d_dxf_handler import execute_cad_floor3d_dxf
from app.cad_worker.handler import execute_cad_pdf_convert
from app.cad_worker.mep_handler import execute_cad_mep_route
from app.cad_worker.model_handler import execute_model_ifc_import
from app.cad_worker.outline_review import execute_outline_review
from app.cad_worker.sections_handler import execute_cad_sections
from app.cad_worker.style_preview_handler import execute_cad_style_preview
from app.cad_worker.walls_handler import execute_cad_walls
from app.cad_worker.zones_handler import execute_cad_zones
from app.domain import JobType
from app.worker.registry import JobHandler

HANDLERS: Final[MappingProxyType[JobType, JobHandler]] = MappingProxyType(
    {
        JobType.CAD_PDF_CONVERT: execute_cad_pdf_convert,
        JobType.CAD_MEP_ROUTE: execute_cad_mep_route,
        JobType.CAD_WALLS: execute_cad_walls,
        JobType.CAD_OUTLINE_REVIEW: execute_outline_review,
        JobType.CAD_AI_REVIEW: execute_ai_review,
        JobType.CAD_AI_VOR_MAP: execute_ai_vor_map,
        JobType.CAD_FLOOR3D_DXF: execute_cad_floor3d_dxf,
        JobType.CAD_ZONES: execute_cad_zones,
        JobType.CAD_SECTIONS: execute_cad_sections,
        JobType.CAD_FACADES: execute_cad_facades,
        JobType.CAD_EOM_ROUTE: execute_cad_eom_route,
        JobType.CAD_STYLE_PREVIEW: execute_cad_style_preview,
        JobType.MODEL_IFC_IMPORT: execute_model_ifc_import,
    }
)
