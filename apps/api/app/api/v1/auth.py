"""Вход, выход и состояние сеанса.

Поток стандартный: Authorization Code + PKCE. Обмен кода выполняет сервер, в браузер
уходит только cookie сеанса — токены провайдера до него не доезжают (ADR-0012).

`/auth/session` публичен намеренно: интерфейс должен уметь спросить «я вошёл?» и получить
честное «нет», а не 401, который в обработчике ошибок неотличим от протухшего сеанса.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from typing import Annotated, Final
from urllib.parse import urljoin

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.api.v1.deps import SessionDep, SettingsDep
from app.auth import csrf, oidc, sessions
from app.auth.dev import DEV_ROLE_HEADER, dev_context
from app.auth.permissions import permissions_for
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import Role
from app.errors import DomainError, ErrorCode
from app.schemas import LogoutResponse, SessionResponse, SessionUser, SessionWorkspace
from app.services import identity as identity_service

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)

# Cookie перехода: живёт между переходом к провайдеру и возвратом. Короткая, HttpOnly,
# и сравнивается с параметром запроса — этим и отсекается подделка входа.
STATE_COOKIE: Final = "quantor_auth_state"
STATE_TTL_SECONDS: Final = 600

CALLBACK_PATH: Final = "/api/v1/auth/callback"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _redirect_uri(request: Request) -> str:
    """Адрес возврата. Собирается из адреса самого API, а не из параметра запроса."""
    return urljoin(str(request.base_url), CALLBACK_PATH.lstrip("/"))


def _safe_next(settings: Settings, raw: str | None) -> str:
    """Куда вернуть браузер после входа.

    Принимается только путь внутри портала. Полный адрес из запроса — это открытая
    переадресация: страница входа портала уводила бы на чужой сайт.
    """
    base = settings.portal_base_url.rstrip("/")
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return f"{base}/"
    return f"{base}{raw}"


def _set_session_cookies(
    response: Response, settings: Settings, *, session_token: str, csrf_token: str
) -> None:
    # Сеанс — HttpOnly: сценарию на странице он недоступен, и кража через XSS не даёт токен.
    response.set_cookie(
        settings.auth_cookie_name,
        session_token,
        httponly=True,
        domain=settings.auth_cookie_domain or None,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
        max_age=settings.auth_session_ttl_seconds,
    )
    # Подтверждение — наоборот, читаемое: интерфейс обязан повторить его заголовком.
    response.set_cookie(
        settings.auth_csrf_cookie_name,
        csrf_token,
        httponly=False,
        domain=settings.auth_cookie_domain or None,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
        max_age=settings.auth_session_ttl_seconds,
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    for name in (settings.auth_cookie_name, settings.auth_csrf_cookie_name):
        response.delete_cookie(
            name,
            path="/",
            domain=settings.auth_cookie_domain or None,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
        )


@router.get(
    "/login",
    response_model=None,
    status_code=307,
    summary="Начать вход",
)
async def begin_login(
    request: Request,
    settings: SettingsDep,
    next_path: Annotated[str | None, Query(alias="next", description="Путь внутри портала")] = None,
) -> RedirectResponse:
    """Переадресует на страницу входа провайдера.

    В dev-режиме провайдера нет: браузер сразу возвращается в портал, где его уже ждёт
    фиксированная личность.
    """
    if settings.auth_mode == "dev":
        return RedirectResponse(_safe_next(settings, next_path), status_code=307)

    discovery = await oidc.discover(settings)

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())

    target = oidc.authorization_url(
        discovery,
        settings,
        redirect_uri=_redirect_uri(request),
        state=state,
        nonce=nonce,
        code_challenge=challenge,
    )
    response = RedirectResponse(target, status_code=307)
    payload = json.dumps(
        {"state": state, "nonce": nonce, "verifier": verifier, "next": next_path or "/"}
    )
    response.set_cookie(
        STATE_COOKIE,
        _b64(payload.encode("utf-8")),
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        max_age=STATE_TTL_SECONDS,
        path="/",
    )
    return response


@router.get(
    "/callback",
    response_model=None,
    status_code=307,
    summary="Завершить вход",
)
async def complete_login(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    code: Annotated[str, Query(description="Код авторизации провайдера")],
    state: Annotated[str, Query(description="Значение состояния")],
) -> RedirectResponse:
    """Меняет код на токены, заводит сеанс и возвращает браузер в портал."""
    if settings.auth_mode == "dev":
        raise DomainError(ErrorCode.AUTH_NOT_CONFIGURED, "Портал работает без провайдера входа")

    stored = _read_state(request)
    # Сравнение состояния из cookie и из запроса — то, чем отсекается навязанный вход.
    if not secrets.compare_digest(stored["state"], state):
        raise DomainError(ErrorCode.OIDC_STATE_INVALID)

    discovery = await oidc.discover(settings)
    tokens = await oidc.exchange_code(
        settings,
        discovery,
        code=code,
        code_verifier=stored["verifier"],
        redirect_uri=_redirect_uri(request),
    )
    claims = oidc.decode_id_token(
        settings, discovery, str(tokens["id_token"]), nonce=stored["nonce"]
    )

    user = await identity_service.upsert_identity(
        session,
        issuer=str(claims["iss"]),
        subject=str(claims["sub"]),
        email=_claim(claims, "email"),
        email_verified=bool(claims.get("email_verified", False)),
        display_name=_claim(claims, "name") or _claim(claims, "preferred_username"),
        platform_admin_hints=settings.bootstrap_platform_admins,
    )

    _, token = await sessions.create(
        session,
        user_id=user.id,
        ttl_seconds=settings.auth_session_ttl_seconds,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    await session.commit()
    log.info("login_succeeded", user_id=str(user.id))

    response = RedirectResponse(_safe_next(settings, stored["next"]), status_code=307)
    _set_session_cookies(response, settings, session_token=token, csrf_token=csrf.new_token())
    response.delete_cookie(STATE_COOKIE, path="/")
    return response


def _read_state(request: Request) -> dict[str, str]:
    raw = request.cookies.get(STATE_COOKIE)
    if not raw:
        raise DomainError(ErrorCode.OIDC_STATE_INVALID, "Переход к провайдеру входа устарел")
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return {key: str(payload[key]) for key in ("state", "nonce", "verifier", "next")}
    except (ValueError, KeyError, TypeError) as error:
        raise DomainError(ErrorCode.OIDC_STATE_INVALID) from error


def _claim(claims: dict[str, object], name: str) -> str | None:
    value = claims.get(name)
    return str(value) if isinstance(value, str) and value.strip() else None


@router.post("/logout", response_model=LogoutResponse, summary="Выйти")
async def logout(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> LogoutResponse:
    """Гасит сеанс и снимает cookie.

    Строка в базе отзывается по-настоящему: cookie можно и не удалять — предъявленный
    после выхода токен всё равно не сработает.
    """
    token = request.cookies.get(settings.auth_cookie_name)
    if token:
        row = await sessions.resolve(session, token)
        if row is not None:
            await sessions.revoke(session, row)
            await session.commit()
            log.info("logout", user_id=str(row.user_id))

    _clear_session_cookies(response, settings)
    return LogoutResponse()


@router.get("/session", response_model=SessionResponse, summary="Текущий сеанс")
async def read_session(
    request: Request, response: Response, session: SessionDep, settings: SettingsDep
) -> SessionResponse:
    """Кто вошёл, куда ему можно и что ему разрешено.

    Публичный маршрут: «не вошёл» — это ответ, а не ошибка.
    """
    if settings.auth_mode == "dev":
        context = dev_context(request.headers.get(DEV_ROLE_HEADER))
        return SessionResponse(
            authenticated=True,
            auth_mode="dev",
            user=SessionUser(
                id=context.principal.user_id,
                email=context.principal.email,
                display_name=context.principal.display_name,
                is_platform_admin=context.principal.is_platform_admin,
            ),
            workspace_id=context.workspace_id,
            role=context.role,
            permissions=sorted(permission.value for permission in context.permissions),
            workspaces=[],
            csrf_token=None,
        )

    token = request.cookies.get(settings.auth_cookie_name)
    row = await sessions.resolve(session, token) if token else None
    if row is None:
        return SessionResponse(authenticated=False, auth_mode="oidc")

    user = await identity_service.get_user(session, row.user_id)
    if user is None or not user.is_active:
        return SessionResponse(authenticated=False, auth_mode="oidc")

    memberships = await identity_service.list_memberships(session, user.id)
    current = memberships[0] if memberships else None
    # Администратор платформы без членства всё равно администратор: иначе первый вход
    # после установки показывал бы портал без единого права.
    role = current.role if current else None
    if user.platform_role is Role.PLATFORM_ADMIN:
        role = Role.PLATFORM_ADMIN

    # Подтверждение могло потеряться вместе с cookie (частный режим, чистка). Выдаём новое
    # здесь же: иначе интерфейс войдёт, но не сможет отправить ни одной формы.
    csrf_token = request.cookies.get(settings.auth_csrf_cookie_name)
    if not csrf_token:
        csrf_token = csrf.new_token()
        response.set_cookie(
            settings.auth_csrf_cookie_name,
            csrf_token,
            httponly=False,
            path="/",
            domain=settings.auth_cookie_domain or None,
            secure=settings.auth_cookie_secure,
            samesite=settings.auth_cookie_samesite,
            max_age=settings.auth_session_ttl_seconds,
        )

    return SessionResponse(
        authenticated=True,
        auth_mode="oidc",
        user=SessionUser(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_platform_admin=user.platform_role is Role.PLATFORM_ADMIN,
        ),
        workspace_id=current.workspace_id if current else None,
        role=role,
        permissions=sorted(p.value for p in permissions_for(role)) if role else [],
        workspaces=[
            SessionWorkspace(
                id=item.workspace_id,
                slug=item.workspace_slug,
                name=item.workspace_name,
                role=item.role,
            )
            for item in memberships
        ],
        csrf_token=csrf_token,
    )


__all__ = ["router"]
