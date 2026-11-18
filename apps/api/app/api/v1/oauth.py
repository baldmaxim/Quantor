"""Вход ИИ-чатов по OAuth 2.1 (ADR-0054): метаданные, регистрация, выдача и страница согласия.

Публичное (`/auth/oauth/*`, под тем же пределом частоты nginx, что вход по паролю): метаданные
сервера входа и ресурса MCP (их отдаёт и `/.well-known/…` через сервер страниц), регистрация
клиента и точка выдачи - их зовёт сервер чата, у него нет сеанса портала. Ответы этих адресов -
в форме OAuth (`{"error", "error_description"}`), а не портала, и в схему клиента не входят.

Защищённое (`/oauth/authorize`): страница согласия спрашивает, что за чат и что он просит, и
передаёт решение человека. Только сеанс браузера: токеном нельзя выдать доступ другому чату.
"""

from __future__ import annotations

import json
from typing import Final
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import AuthDep, SessionDep, SettingsDep, require
from app.auth.context import AuthContext, CredentialKind
from app.auth.permissions import Permission
from app.contracts.oauth import OAuthAuthorizeDecision, OAuthAuthorizeInfo, OAuthAuthorizeRedirect
from app.core.config import Settings
from app.core.logging import get_logger
from app.domain import AuditAction
from app.errors import DomainError, ErrorCode
from app.models import Workspace
from app.services import audit as audit_service
from app.services import oauth as oauth_service

log = get_logger(__name__)

public_router = APIRouter(prefix="/auth/oauth", tags=["oauth"])
router = APIRouter(prefix="/oauth", tags=["oauth"])

_NO_STORE: Final = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_METADATA_CACHE: Final = {"Cache-Control": "public, max-age=300"}
_MAX_FORM_BYTES: Final = 16 * 1024
_MAX_REGISTRATION_BYTES: Final = 64 * 1024


def _oauth_error(error: oauth_service.OAuthError) -> JSONResponse:
    headers = dict(_NO_STORE)
    if error.status_code == status.HTTP_401_UNAUTHORIZED:
        headers["WWW-Authenticate"] = 'Basic realm="quantor"'
    return JSONResponse(
        {"error": error.error, "error_description": error.description},
        status_code=error.status_code,
        headers=headers,
    )


@public_router.get("/metadata/authorization-server", include_in_schema=False)
async def oauth_authorization_server_metadata(settings: SettingsDep) -> JSONResponse:
    """RFC 8414: `/.well-known/oauth-authorization-server`."""
    return JSONResponse(
        oauth_service.authorization_server_metadata(settings), headers=_METADATA_CACHE
    )


@public_router.get("/metadata/protected-resource", include_in_schema=False)
async def oauth_protected_resource_metadata(settings: SettingsDep) -> JSONResponse:
    """RFC 9728: `/.well-known/oauth-protected-resource/api/v1/mcp`."""
    return JSONResponse(
        oauth_service.protected_resource_metadata(settings), headers=_METADATA_CACHE
    )


@public_router.post("/register", include_in_schema=False)
async def oauth_register_client(
    request: Request, session: SessionDep, settings: SettingsDep
) -> JSONResponse:
    """RFC 7591: чат регистрирует себя; адреса возврата - только из белого списка портала."""
    body = await request.body()
    if len(body) > _MAX_REGISTRATION_BYTES:
        return _oauth_error(
            oauth_service.OAuthError("invalid_client_metadata", "Слишком большое тело")
        )
    try:
        metadata = json.loads(body)
    except (ValueError, RecursionError):
        return _oauth_error(oauth_service.OAuthError("invalid_client_metadata", "Тело не JSON"))
    try:
        answer = await oauth_service.register_client(session, settings, metadata)
    except oauth_service.OAuthError as error:
        log.info("oauth_client_rejected", error=error.error, reason=error.description[:200])
        return _oauth_error(error)
    await session.commit()
    log.info(
        "oauth_client_registered",
        client_id=answer["client_id"],
        client_name=answer["client_name"],
        redirect_hosts=sorted({oauth_service.redirect_host(u) for u in answer["redirect_uris"]}),
        auth_method=answer["token_endpoint_auth_method"],
    )
    return JSONResponse(answer, status_code=status.HTTP_201_CREATED, headers=_NO_STORE)


@public_router.post("/token", include_in_schema=False)
async def oauth_token(request: Request, session: SessionDep, settings: SettingsDep) -> JSONResponse:
    """RFC 6749 §3.2: код на доступ и обновление, обновление на новую пару."""
    if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        return _oauth_error(
            oauth_service.OAuthError(
                "invalid_request", "Нужен Content-Type: application/x-www-form-urlencoded"
            )
        )
    body = await request.body()
    if len(body) > _MAX_FORM_BYTES:
        return _oauth_error(oauth_service.OAuthError("invalid_request", "Слишком большое тело"))
    try:
        pairs = parse_qsl(body.decode("utf-8"), keep_blank_values=True, strict_parsing=False)
    except UnicodeDecodeError:
        return _oauth_error(oauth_service.OAuthError("invalid_request", "Тело не UTF-8"))
    form: dict[str, str] = {}
    for key, value in pairs:
        if key in form:
            return _oauth_error(
                oauth_service.OAuthError("invalid_request", f"Параметр {key} повторён")
            )
        form[key] = value
    try:
        answer = await oauth_service.exchange(
            session, settings, form, request.headers.get("authorization")
        )
    except oauth_service.OAuthError as error:
        # Отзыв разрешения при повторе кода или обновления должен остаться и при ответе ошибкой.
        await session.commit()
        log.info("oauth_token_rejected", error=error.error, grant_type=form.get("grant_type"))
        return _oauth_error(error)
    await session.commit()
    return JSONResponse(answer, headers=_NO_STORE)


def _session_only(context: AuthContext) -> None:
    if context.credential not in (CredentialKind.SESSION, CredentialKind.DEV):
        raise DomainError(
            ErrorCode.PERMISSION_DENIED, "Доступ чату разрешает человек в сеансе портала"
        )


def _single(request: Request) -> dict[str, str]:
    params = request.query_params
    repeated = [key for key in params if len(params.getlist(key)) > 1]
    if repeated:
        raise DomainError(ErrorCode.VALIDATION_FAILED, f"Параметр {repeated[0]} повторён")
    return dict(params)


async def _workspace_name(session: AsyncSession, context: AuthContext) -> str:
    workspace = await session.get(Workspace, context.tenant)
    return workspace.name if workspace is not None else ""


async def _parse(
    session: AsyncSession, settings: Settings, params: dict[str, str]
) -> oauth_service.AuthorizationRequest:
    try:
        return await oauth_service.parse_authorization_request(session, settings, params)
    except oauth_service.AuthorizeError as error:
        raise DomainError(ErrorCode.VALIDATION_FAILED, str(error)) from error


@router.get(
    "/authorize",
    response_model=OAuthAuthorizeInfo,
    summary="Запрос ИИ-чата на доступ: что показать на странице согласия",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def oauth_authorize_check(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    context: AuthDep,
    # Объявлены ради схемы клиента страницы; читаются все разом из адреса (`_single`).
    client_id: str | None = None,
    redirect_uri: str | None = None,
    response_type: str | None = None,
    state: str | None = None,
    scope: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
    resource: str | None = None,
) -> OAuthAuthorizeInfo:
    del client_id, redirect_uri, response_type, state, scope
    del code_challenge, code_challenge_method, resource
    _session_only(context)
    try:
        parsed = await _parse(session, settings, _single(request))
    except oauth_service.AuthorizeRedirectError as redirect:
        return OAuthAuthorizeInfo(error_redirect=redirect.url)
    existing = await oauth_service.active_grant(
        session,
        user_id=context.principal.user_id,
        workspace_id=context.tenant,
        client=parsed.client,
    )
    return OAuthAuthorizeInfo(
        client_name=parsed.client.client_name,
        redirect_host=oauth_service.redirect_host(parsed.redirect_uri),
        local_app=oauth_service.redirect_host(parsed.redirect_uri)
        in ("localhost", "127.0.0.1", "::1"),
        scopes=list(parsed.scopes),
        scope_titles={scope: oauth_service.SCOPE_TITLES[scope] for scope in parsed.scopes},
        workspace_name=await _workspace_name(session, context),
        already_connected=existing is not None,
    )


@router.post(
    "/authorize",
    response_model=OAuthAuthorizeRedirect,
    summary="Решение человека: разрешить ИИ-чату доступ или отказать",
    dependencies=[require(Permission.WORKSPACE_READ)],
)
async def oauth_authorize_decide(
    body: OAuthAuthorizeDecision, session: SessionDep, settings: SettingsDep, context: AuthDep
) -> OAuthAuthorizeRedirect:
    _session_only(context)
    try:
        parsed = await _parse(session, settings, body.params)
    except oauth_service.AuthorizeRedirectError as redirect:
        return OAuthAuthorizeRedirect(redirect_to=redirect.url)
    if not body.approve:
        log.info("oauth_denied", client_id=parsed.client.client_id)
        return OAuthAuthorizeRedirect(redirect_to=oauth_service.deny_redirect(settings, parsed))
    grant, created, url = await oauth_service.approve(
        session,
        settings,
        parsed,
        user_id=context.principal.user_id,
        workspace_id=context.tenant,
        scopes=body.scopes,
    )
    await audit_service.record(
        session,
        context,
        action=AuditAction.API_ACCESS_CREATED,
        resource_type="api_token",
        resource_id=str(grant.id),
        after={
            "name": grant.name,
            "oauth_client": parsed.client.client_id,
            "client_name": parsed.client.client_name,
            "redirect_host": oauth_service.redirect_host(parsed.redirect_uri),
            "scopes": list(grant.scopes),
            "renewed": not created,
        },
    )
    await session.commit()
    return OAuthAuthorizeRedirect(redirect_to=url)
