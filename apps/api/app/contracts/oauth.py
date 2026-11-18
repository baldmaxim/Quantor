"""Страница согласия на вход ИИ-чата по OAuth (ADR-0054)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OAuthAuthorizeInfo(BaseModel):
    """Что показать человеку перед «Разрешить», либо куда сразу вернуть чат с ошибкой."""

    client_name: str = ""
    # Куда уйдёт ответ: хост адреса возврата (claude.ai, chatgpt.com, localhost).
    redirect_host: str = ""
    # Адрес возврата на этом компьютере: программа, а не веб-чат.
    local_app: bool = False
    scopes: list[str] = Field(default_factory=list)
    scope_titles: dict[str, str] = Field(default_factory=dict)
    workspace_name: str = ""
    # Этот чат уже подключён в этом пространстве: разрешение обновится, а не добавится.
    already_connected: bool = False
    # Ошибка запроса, о которой чату сообщают переадресацией: странице - сразу перейти.
    error_redirect: str | None = None


class OAuthAuthorizeDecision(BaseModel):
    # Параметры запроса чата как пришли в адресе страницы (client_id, redirect_uri, state, …).
    params: dict[str, str]
    approve: bool
    # Что человек оставил отмеченным; пусто (null) - всё, что просил чат. Чтение есть всегда.
    scopes: list[str] | None = None


class OAuthAuthorizeRedirect(BaseModel):
    redirect_to: str
