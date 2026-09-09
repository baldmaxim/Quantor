"""Сборка маршрутов /api/v1.

Здесь проходит граница запрета по умолчанию. Защищённые маршрутизаторы включаются не
напрямую, а через общий, на котором висит требование аутентификации: забыть добавить
проверку к новому маршруту невозможно, потому что добавлять нечего — достаточно включить
его в нужную группу.

Публичных маршрутов ровно два вида и оба осознанные:

- `/auth/*` — вход и вопрос «я вошёл?». Отвечать на него отказом 401 значит не отличать
  «не вошёл» от «сеанс протух»;
- `/meta` — версии и набор возможностей. Страница входа должна узнать состояние API
  до того, как появится сеанс.

Права на конкретные операции объявлены в самих обработчиках (`dependencies=[require(...)]`).
Тест `test_routes_deny_by_default` перебирает операции и не даёт появиться маршруту без
объявленного права или без места в списке публичных.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1 import auth, documents, integrations, jobs, meta, projects, scale, uploads
from app.api.v1.admin import admin_router
from app.auth.resolver import require_authenticated

api_v1_router = APIRouter(prefix="/api/v1")

# --- публичное ---
api_v1_router.include_router(auth.router)
api_v1_router.include_router(meta.router)

# --- всё остальное только после опознания ---
protected_router = APIRouter(dependencies=[Depends(require_authenticated)])
protected_router.include_router(projects.router)
protected_router.include_router(uploads.router)
protected_router.include_router(documents.router)
protected_router.include_router(scale.router)
protected_router.include_router(jobs.router)
protected_router.include_router(integrations.router)

api_v1_router.include_router(protected_router)

# Контур управления платформой. Отдельной группой, со своим требованием прав на входе.
api_v1_router.include_router(admin_router)
