"""Граница рабочего пространства.

Аутентификации на Stage 1 нет — это временный dev-режим, и он явно помечен как временный.
Смысл абстракции в том, чтобы каждый запрос уже сейчас фильтровался по workspace_id: когда
появятся настоящие пользователи и арендаторы, поменяется только источник контекста, а не
все запросы и таблицы.

Наружу портал в этом виде выставлять нельзя: любой, кто дотянется до API, увидит все проекты.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

# Фиксированный идентификатор dev-пространства: одинаков между перезапусками, иначе после
# рестарта уже созданные проекты стали бы невидимыми.
DEV_WORKSPACE_ID: Final[uuid.UUID] = uuid.UUID("00000000-0000-4000-8000-000000000001")


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    """Контекст текущего запроса. Позже сюда добавится пользователь и его права."""

    workspace_id: uuid.UUID
    is_dev_mode: bool


def get_workspace_context() -> WorkspaceContext:
    """FastAPI-зависимость. Пока всегда возвращает dev-пространство."""
    return WorkspaceContext(workspace_id=DEV_WORKSPACE_ID, is_dev_mode=True)
