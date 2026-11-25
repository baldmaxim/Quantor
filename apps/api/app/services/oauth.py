"""Вход ИИ-чатов по OAuth 2.1 (ADR-0054): портал сам выдаёт доступ чатам Claude и ChatGPT.

Путь чата: метаданные (RFC 9728 о ресурсе MCP, RFC 8414 о сервере входа) → регистрация клиента
(RFC 7591) → страница портала «Разрешить» (код с PKCE S256, ответ с `iss` по RFC 9207) → обмен кода
на доступ `qoa_` (час) и обновление `qor_` (30 дней, одноразовое, с заменой) → `POST /api/v1/mcp`.

Разрешение человека - строка `api_tokens` с `oauth_client_id`: пространство, области (`read`,
`upload`) и отзыв те же, что у личного токена. Доступ чата годится только для MCP: снаружи - только
`/api/v1/mcp`, внутри - вызовы его инструментов с секретом процесса (`internal_headers`).
Адреса возврата - только из белого списка настроек: страницу согласия нельзя подсунуть
посторонним сайтом, который зарегистрировал бы себя клиентом.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ApiToken, OAuthClient, OAuthToken
from app.services import api_tokens as api_tokens_service

ACCESS_PREFIX: Final = "qoa_"
REFRESH_PREFIX: Final = "qor_"
CODE_PREFIX: Final = "qac_"
CLIENT_PREFIX: Final = "qoc_"
SECRET_PREFIX: Final = "qos_"  # noqa: S105 - префикс значения, не секрет

CODE_TTL: Final = timedelta(minutes=5)
ACCESS_TTL: Final = timedelta(hours=1)
REFRESH_TTL: Final = timedelta(days=30)
# Повтор уже обменянного обновления в эту минуту - гонка параллельных запросов одного чата, позже -
# признак кражи: тогда разрешение отзывается целиком.
REPLAY_GRACE: Final = timedelta(seconds=60)

OAUTH_SCOPES: Final = (api_tokens_service.SCOPE_READ, api_tokens_service.SCOPE_UPLOAD)
SCOPE_TITLES: Final = {
    api_tokens_service.SCOPE_READ: "читать проекты, документы, модель и координационный файл",
    api_tokens_service.SCOPE_UPLOAD: (
        "загружать IFC своего раздела и собирать модель («отправить в 3D»)"
    ),
}
GRANT_TYPES: Final = ("authorization_code", "refresh_token")
PUBLIC_AUTH_METHOD: Final = "none"
AUTH_METHODS: Final = (PUBLIC_AUTH_METHOD, "client_secret_post", "client_secret_basic")

MCP_PATH: Final = "/api/v1/mcp"
AUTHORIZE_PATH: Final = "/oauth/authorize"
TOKEN_PATH: Final = "/api/v1/auth/oauth/token"  # noqa: S105 - адрес, не секрет
REGISTER_PATH: Final = "/api/v1/auth/oauth/register"
RESOURCE_METADATA_PATH: Final = "/.well-known/oauth-protected-resource"

MAX_REDIRECT_URIS: Final = 5
MAX_URI_LENGTH: Final = 2000
MAX_STATE_LENGTH: Final = 2000
DEFAULT_CLIENT_NAME: Final = "ИИ-клиент"
GRANT_PREFIX_LABEL: Final = "oauth"
_TOKEN_BYTES: Final = 30
_PKCE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_LOOPBACK_HOSTS: Final = ("localhost", "127.0.0.1", "::1")
# Области, которые чаты просят по своим правилам и которые порталу не нужны: молча пропускаются.
_IGNORED_SCOPES: Final = ("offline_access", "openid", "profile", "email")

# Секрет внутренних вызовов MCP: свой у каждого процесса, наружу не выходит. По нему доступ чата
# пускают во внутренние адреса, которые зовут инструменты MCP, и никуда больше.
INTERNAL_HEADER: Final = "X-Quantor-Internal"
_INTERNAL_SECRET: Final = secrets.token_urlsafe(32)


class OAuthError(Exception):
    """Ошибка протокола для машины: `{"error", "error_description"}` (RFC 6749 §5.2, RFC 7591)."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


class AuthorizeError(Exception):
    """Запрос разрешения нельзя вернуть клиенту: неизвестен клиент или адрес возврата.

    Показывается человеку на странице портала; переадресация на непроверенный адрес - подарок
    фишингу (RFC 6749 §4.1.2.1).
    """


class AuthorizeRedirectError(Exception):
    """Ошибка запроса, о которой клиенту сообщают переадресацией с `error`."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    client: OAuthClient
    redirect_uri: str
    state: str | None
    scopes: tuple[str, ...]
    code_challenge: str
    resource: str | None


def internal_headers() -> dict[str, str]:
    return {INTERNAL_HEADER: _INTERNAL_SECRET}


def is_internal_call(headers: Mapping[str, str]) -> bool:
    value = headers.get(INTERNAL_HEADER)
    if not value:
        return False
    return hmac.compare_digest(value, _INTERNAL_SECRET)


def issuer(settings: Settings) -> str:
    return settings.portal_base_url.rstrip("/")


def resource_url(settings: Settings) -> str:
    return issuer(settings) + MCP_PATH


def resource_metadata_url(settings: Settings) -> str:
    return issuer(settings) + RESOURCE_METADATA_PATH + MCP_PATH


def www_authenticate(settings: Settings, *, invalid_token: bool = False) -> str:
    """Заголовок отказа MCP: где лежат метаданные ресурса и какие области просить.

    `invalid_token` (RFC 6750 §3.1) - токен был, но не годится (истёк, отозван): чат обновляет его.
    """
    challenge = (
        f'Bearer resource_metadata="{resource_metadata_url(settings)}", '
        f'scope="{" ".join(OAUTH_SCOPES)}"'
    )
    return challenge + (', error="invalid_token"' if invalid_token else "")


def authorization_server_metadata(settings: Settings) -> dict[str, Any]:
    base = issuer(settings)
    return {
        "issuer": base,
        "authorization_endpoint": base + AUTHORIZE_PATH,
        "token_endpoint": base + TOKEN_PATH,
        "registration_endpoint": base + REGISTER_PATH,
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": list(GRANT_TYPES),
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": list(AUTH_METHODS),
        # offline_access - чтобы Claude просил обновление; выдаётся оно и без него.
        "scopes_supported": [*OAUTH_SCOPES, "offline_access"],
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": base + "/projects",
    }


def protected_resource_metadata(settings: Settings) -> dict[str, Any]:
    return {
        "resource": resource_url(settings),
        "authorization_servers": [issuer(settings)],
        "scopes_supported": list(OAUTH_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_name": "Quantor",
    }


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _is_loopback(uri: str) -> bool:
    parts = urlsplit(uri)
    return parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS


def _without_port(uri: str) -> str:
    parts = urlsplit(uri)
    host = parts.hostname or ""
    return urlunsplit((parts.scheme, host, parts.path, parts.query, ""))


def redirect_allowed(settings: Settings, uri: str) -> bool:
    """Адрес возврата годится для регистрации: белый список или этот компьютер."""
    if not uri or len(uri) > MAX_URI_LENGTH:
        return False
    parts = urlsplit(uri)
    if parts.fragment or not parts.hostname or parts.username or parts.password:
        return False
    if _is_loopback(uri):
        return settings.oauth_allow_loopback
    if parts.scheme != "https":
        return False
    return any(
        uri == allowed or (allowed.endswith("/") and uri.startswith(allowed))
        for allowed in settings.oauth_redirect_allowlist
    )


def redirect_matches(registered: list[str], uri: str) -> bool:
    """Точное совпадение; у адреса этого компьютера порт не сравнивается (RFC 8252 §7.3)."""
    if uri in registered:
        return True
    if not _is_loopback(uri):
        return False
    target = _without_port(uri)
    return any(_is_loopback(item) and _without_port(item) == target for item in registered)


def with_query(uri: str, params: Mapping[str, str | None]) -> str:
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _str_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise OAuthError("invalid_client_metadata", f"{field}: нужен список строк")
    return list(value)


async def register_client(
    session: AsyncSession, settings: Settings, metadata: object
) -> dict[str, Any]:
    """Регистрация клиента (RFC 7591). Ответ - метаданные клиента, секрет - один раз."""
    if not isinstance(metadata, dict):
        raise OAuthError("invalid_client_metadata", "Тело регистрации - объект JSON")
    redirect_uris = _str_list(metadata.get("redirect_uris"), "redirect_uris")
    if not redirect_uris or len(redirect_uris) > MAX_REDIRECT_URIS:
        raise OAuthError(
            "invalid_redirect_uri", f"Нужен от 1 до {MAX_REDIRECT_URIS} адресов возврата"
        )
    for uri in redirect_uris:
        if not redirect_allowed(settings, uri):
            raise OAuthError(
                "invalid_redirect_uri",
                f"Адрес возврата не разрешён порталом: {uri[:200]}",
            )
    grant_types = _str_list(metadata.get("grant_types"), "grant_types") or list(GRANT_TYPES)
    if "authorization_code" not in grant_types or not set(grant_types) <= set(GRANT_TYPES):
        raise OAuthError(
            "invalid_client_metadata", "grant_types: только authorization_code и refresh_token"
        )
    response_types = _str_list(metadata.get("response_types"), "response_types") or ["code"]
    if set(response_types) != {"code"}:
        raise OAuthError("invalid_client_metadata", "response_types: только code")
    # Умолчание RFC 7591 - client_secret_basic; чаты MCP присылают none явно.
    method = metadata.get("token_endpoint_auth_method") or "client_secret_basic"
    if method not in AUTH_METHODS:
        raise OAuthError(
            "invalid_client_metadata",
            "token_endpoint_auth_method: none, client_secret_post или client_secret_basic",
        )
    raw_name = metadata.get("client_name")
    name = raw_name.strip()[:200] if isinstance(raw_name, str) and raw_name.strip() else ""
    secret = (
        None
        if method == PUBLIC_AUTH_METHOD
        else SECRET_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    )
    client = OAuthClient(
        client_id=CLIENT_PREFIX + secrets.token_urlsafe(18),
        client_name=name or DEFAULT_CLIENT_NAME,
        redirect_uris=redirect_uris,
        token_endpoint_auth_method=method,
        client_secret_hash=None if secret is None else _hash(secret),
    )
    session.add(client)
    await session.flush()
    answer: dict[str, Any] = {
        "client_id": client.client_id,
        "client_id_issued_at": int(_now().timestamp()),
        "client_name": client.client_name,
        "redirect_uris": redirect_uris,
        "grant_types": list(GRANT_TYPES),
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
    }
    if secret is not None:
        answer["client_secret"] = secret
        answer["client_secret_expires_at"] = 0
    return answer


async def _client(session: AsyncSession, client_id: str | None) -> OAuthClient | None:
    if not client_id or len(client_id) > 64:
        return None
    row: OAuthClient | None = await session.scalar(
        select(OAuthClient).where(OAuthClient.client_id == client_id)
    )
    return row


def _same_resource(settings: Settings, value: str) -> bool:
    return value.rstrip("/") == resource_url(settings)


async def parse_authorization_request(
    session: AsyncSession, settings: Settings, params: Mapping[str, str]
) -> AuthorizationRequest:
    """Проверка запроса разрешения (RFC 6749 §4.1.1 + PKCE + RFC 8707)."""
    client = await _client(session, params.get("client_id"))
    if client is None:
        raise AuthorizeError("Чат не зарегистрирован на портале: начните подключение в чате заново")
    redirect_uri = params.get("redirect_uri")
    if not redirect_uri:
        if len(client.redirect_uris) != 1:
            raise AuthorizeError("В запросе нет адреса возврата")
        redirect_uri = client.redirect_uris[0]
    elif not redirect_matches(client.redirect_uris, redirect_uri):
        raise AuthorizeError("Адрес возврата не совпадает с зарегистрированным у этого чата")

    state = params.get("state")
    if state is not None and len(state) > MAX_STATE_LENGTH:
        raise AuthorizeError("Слишком длинный параметр state")
    base = issuer(settings)

    def fail(error: str, description: str) -> AuthorizeRedirectError:
        return AuthorizeRedirectError(
            with_query(
                redirect_uri,
                {"error": error, "error_description": description, "state": state, "iss": base},
            )
        )

    if params.get("response_type") != "code":
        raise fail("unsupported_response_type", "Только response_type=code")
    challenge = params.get("code_challenge") or ""
    if params.get("code_challenge_method") != "S256" or not _PKCE.match(challenge):
        raise fail("invalid_request", "Нужен PKCE: code_challenge и code_challenge_method=S256")
    resource = params.get("resource")
    if resource is not None and not _same_resource(settings, resource):
        raise fail("invalid_target", f"Портал выдаёт доступ только к {resource_url(settings)}")
    asked = set((params.get("scope") or "").split()) - set(_IGNORED_SCOPES)
    scopes = tuple(scope for scope in OAUTH_SCOPES if scope in asked) or (
        api_tokens_service.SCOPE_READ,
    )
    return AuthorizationRequest(
        client=client,
        redirect_uri=redirect_uri,
        state=state,
        scopes=scopes,
        code_challenge=challenge,
        resource=resource,
    )


def deny_redirect(settings: Settings, request: AuthorizationRequest) -> str:
    return with_query(
        request.redirect_uri,
        {
            "error": "access_denied",
            "error_description": "Доступ не разрешён",
            "state": request.state,
            "iss": issuer(settings),
        },
    )


async def active_grant(
    session: AsyncSession, *, user_id: uuid.UUID, workspace_id: uuid.UUID, client: OAuthClient
) -> ApiToken | None:
    row: ApiToken | None = await session.scalar(
        select(ApiToken)
        .where(
            ApiToken.user_id == user_id,
            ApiToken.workspace_id == workspace_id,
            ApiToken.oauth_client_id == client.id,
            ApiToken.revoked_at.is_(None),
        )
        .order_by(ApiToken.created_at.desc())
        .limit(1)
    )
    return row


async def approve(
    session: AsyncSession,
    settings: Settings,
    request: AuthorizationRequest,
    *,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    scopes: list[str] | None,
) -> tuple[ApiToken, bool, str]:
    """Разрешение человека: строка разрешения (новая или прежняя этого чата) и код.

    `scopes` - что человек оставил отмеченным (None - всё, что просил чат); чтение есть всегда.
    Возвращает разрешение, признак «новое» и адрес возврата с кодом.
    """
    kept = set(request.scopes if scopes is None else scopes)
    chosen: list[str] = [
        scope for scope in OAUTH_SCOPES if scope in request.scopes and scope in kept
    ] or [api_tokens_service.SCOPE_READ]
    if api_tokens_service.SCOPE_READ not in chosen:
        chosen.insert(0, api_tokens_service.SCOPE_READ)
    grant = await active_grant(
        session, user_id=user_id, workspace_id=workspace_id, client=request.client
    )
    created = grant is None
    if grant is None:
        grant = ApiToken(
            user_id=user_id,
            workspace_id=workspace_id,
            name=f"{request.client.client_name} (чат)"[:100],
            prefix=GRANT_PREFIX_LABEL,
            # Значения `qtk_` у разрешения нет: хеш случайной строки, которую никто не видел.
            token_hash=_hash(secrets.token_urlsafe(32)),
            scopes=chosen,
            oauth_client_id=request.client.id,
        )
        session.add(grant)
    else:
        grant.scopes = chosen
    await session.flush()
    code = CODE_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    session.add(
        OAuthToken(
            token_hash=_hash(code),
            kind="code",
            grant_id=grant.id,
            client_id=request.client.id,
            expires_at=_now() + CODE_TTL,
            code_challenge=request.code_challenge,
            redirect_uri=request.redirect_uri,
            resource=request.resource,
        )
    )
    await session.flush()
    url = with_query(
        request.redirect_uri, {"code": code, "state": request.state, "iss": issuer(settings)}
    )
    return grant, created, url


def _basic_credentials(header: str | None) -> tuple[str, str] | None:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    client_id, sep, secret = raw.partition(":")
    if not sep:
        return None
    # RFC 6749 §2.3.1: обе части закодированы application/x-www-form-urlencoded.
    from urllib.parse import unquote_plus

    return unquote_plus(client_id), unquote_plus(secret)


async def _authenticate_client(
    session: AsyncSession, form: Mapping[str, str], authorization: str | None
) -> OAuthClient:
    basic = _basic_credentials(authorization)
    client_id = basic[0] if basic else form.get("client_id")
    client = await _client(session, client_id)
    if client is None:
        raise OAuthError("invalid_client", "Неизвестный клиент", 401)
    if client.token_endpoint_auth_method == PUBLIC_AUTH_METHOD:
        return client
    secret = basic[1] if basic else form.get("client_secret")
    if not secret or client.client_secret_hash is None:
        raise OAuthError("invalid_client", "Нужен секрет клиента", 401)
    if not hmac.compare_digest(_hash(secret), client.client_secret_hash):
        raise OAuthError("invalid_client", "Секрет клиента неверен", 401)
    return client


def _pkce_ok(verifier: str | None, challenge: str | None) -> bool:
    if not verifier or not challenge or not _PKCE.match(verifier):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(expected, challenge)


async def _locked_token(session: AsyncSession, value: str | None, kind: str) -> OAuthToken | None:
    if not value or len(value) > 200:
        return None
    row: OAuthToken | None = await session.scalar(
        select(OAuthToken)
        .where(OAuthToken.token_hash == _hash(value), OAuthToken.kind == kind)
        .with_for_update()
    )
    return row


async def _revoke_grant(session: AsyncSession, grant_id: uuid.UUID) -> None:
    grant = await session.get(ApiToken, grant_id)
    if grant is not None:
        await api_tokens_service.revoke(session, grant)


async def _issue(
    session: AsyncSession, grant: ApiToken, client: OAuthClient, resource: str | None
) -> dict[str, Any]:
    now = _now()
    access = ACCESS_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    refresh = REFRESH_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)
    # Старые значения этого разрешения, истёкшие больше суток назад, больше не нужны даже
    # для распознавания повтора.
    await session.execute(
        delete(OAuthToken).where(
            OAuthToken.grant_id == grant.id, OAuthToken.expires_at < now - timedelta(days=1)
        )
    )
    for value, kind, ttl in ((access, "access", ACCESS_TTL), (refresh, "refresh", REFRESH_TTL)):
        session.add(
            OAuthToken(
                token_hash=_hash(value),
                kind=kind,
                grant_id=grant.id,
                client_id=client.id,
                expires_at=now + ttl,
                resource=resource,
            )
        )
    await session.flush()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": " ".join(grant.scopes),
    }


async def exchange(
    session: AsyncSession,
    settings: Settings,
    form: Mapping[str, str],
    authorization: str | None,
) -> dict[str, Any]:
    """Точка выдачи (RFC 6749 §4.1.3, §6): код на доступ и обновление; обновление на новую пару.

    Отзыв разрешения при повторе кода или старого обновления фиксируется в базе до ответа
    ошибкой: вызывающий коммитит сессию и при `OAuthError`.
    """
    grant_type = form.get("grant_type")
    if grant_type not in GRANT_TYPES:
        raise OAuthError("unsupported_grant_type", "Только authorization_code и refresh_token")
    client = await _authenticate_client(session, form, authorization)
    resource = form.get("resource")
    if resource is not None and not _same_resource(settings, resource):
        raise OAuthError("invalid_target", f"Доступ выдаётся только к {resource_url(settings)}")
    now = _now()

    if grant_type == "authorization_code":
        row = await _locked_token(session, form.get("code"), "code")
        if row is None or row.client_id != client.id:
            raise OAuthError("invalid_grant", "Код неизвестен")
        if row.consumed_at is not None:
            # Повтор кода (RFC 6749 §4.1.2): всё, что выдано по нему, отзывается.
            await _revoke_grant(session, row.grant_id)
            raise OAuthError("invalid_grant", "Код уже использован")
        if row.expires_at <= now:
            raise OAuthError("invalid_grant", "Код истёк")
        redirect_uri = form.get("redirect_uri")
        if redirect_uri is not None and redirect_uri != row.redirect_uri:
            raise OAuthError("invalid_grant", "Адрес возврата не тот, что при запросе кода")
        if not _pkce_ok(form.get("code_verifier"), row.code_challenge):
            raise OAuthError("invalid_grant", "PKCE: code_verifier не подходит")
        row.consumed_at = now
        grant = await session.get(ApiToken, row.grant_id)
        if grant is None or not api_tokens_service.is_active(grant):
            raise OAuthError("invalid_grant", "Разрешение отозвано")
        return await _issue(session, grant, client, resource or row.resource)

    row = await _locked_token(session, form.get("refresh_token"), "refresh")
    if row is None or row.client_id != client.id:
        raise OAuthError("invalid_grant", "Обновление неизвестно")
    if row.consumed_at is not None:
        if now - row.consumed_at > REPLAY_GRACE:
            await _revoke_grant(session, row.grant_id)
        raise OAuthError("invalid_grant", "Обновление уже использовано")
    if row.expires_at <= now:
        raise OAuthError("invalid_grant", "Обновление истекло: подключите чат заново")
    grant = await session.get(ApiToken, row.grant_id)
    if grant is None or not api_tokens_service.is_active(grant):
        raise OAuthError("invalid_grant", "Разрешение отозвано")
    row.consumed_at = now
    return await _issue(session, grant, client, resource or row.resource)


async def find_access_grant(session: AsyncSession, token: str) -> ApiToken | None:
    """Разрешение по доступу `qoa_`: доступ не истёк, разрешение не отозвано."""
    if len(token) > 200:
        return None
    row = await session.scalar(
        select(OAuthToken).where(OAuthToken.token_hash == _hash(token), OAuthToken.kind == "access")
    )
    if row is None or row.expires_at <= _now():
        return None
    grant = await session.get(ApiToken, row.grant_id)
    if grant is None or not api_tokens_service.is_active(grant):
        return None
    return grant


async def client_names(session: AsyncSession, client_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not client_ids:
        return {}
    rows = await session.execute(
        select(OAuthClient.id, OAuthClient.client_name).where(OAuthClient.id.in_(client_ids))
    )
    return {row.id: row.client_name for row in rows}


def redirect_host(uri: str) -> str:
    return urlsplit(uri).hostname or uri
