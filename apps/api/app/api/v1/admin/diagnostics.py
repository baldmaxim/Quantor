"""Эксплуатационная диагностика.

Отдельно от `/health/ready`: та отвечает балансировщику, эта — человеку. Поэтому
закрыта правами, подробнее и допускает подсказку к починке.

Обновление — по запросу. Автоматический опрос добавляет нагрузку ровно тогда, когда
система и так нездорова, а сюда приходят именно в этот момент.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.v1.deps import SettingsDep, require
from app.auth.permissions import Permission
from app.schemas import ComponentDiagnosticsRead, DiagnosticsReport
from app.services import diagnostics as diagnostics_service

router = APIRouter(prefix="/diagnostics")


@router.get(
    "",
    response_model=DiagnosticsReport,
    summary="Состояние установки",
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
async def read_diagnostics(settings: SettingsDep) -> DiagnosticsReport:
    """Что работает, что нет и что с этим делать.

    Ни одна проба не может уронить ответ: отказ превращается в состояние компонента.
    Общий предел времени гарантирует, что страница ответит даже при мёртвой зависимости.
    """
    probes = diagnostics_service.build_probes(settings)
    components = await diagnostics_service.run_probes(probes)

    return DiagnosticsReport(
        status=diagnostics_service.overall(components, probes),
        generated_at=datetime.now(UTC),
        components=[
            ComponentDiagnosticsRead(
                name=item.name,
                title=item.title,
                status=item.status,
                source=item.source,
                checked_at=item.checked_at,
                duration_ms=item.duration_ms,
                detail=item.detail,
                remediation=item.remediation,
                facts=item.facts,
            )
            for item in components
        ],
    )
