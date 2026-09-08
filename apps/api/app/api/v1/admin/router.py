"""Сборка административных маршрутов.

Право `system.admin` требуется на входе в контур целиком, а не на каждой операции по
отдельности: контур управления платформой — это одна поверхность, и частичный доступ к
ней означал бы, что кто-то видит настройки, но не видит, кто их менял.

Отдельные операции дополнительно объявляют своё право: запрет по умолчанию отвечает
«кто это», право — «что ему можно».
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin import audit, feature_flags, integrations, jobs, settings
from app.api.v1.deps import require
from app.auth.permissions import Permission

admin_router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[require(Permission.SYSTEM_ADMIN)],
)
admin_router.include_router(settings.router)
admin_router.include_router(feature_flags.router)
admin_router.include_router(integrations.router)
admin_router.include_router(jobs.router)
admin_router.include_router(audit.router)
