"""Клиент провайдера входа: discovery, JWKS, обмен кода.

Стандарт, а не SDK вендора. Всё, что нужно знать о провайдере, берётся из его
discovery-документа, поэтому смена Keycloak на authentik или на корпоративный вход —
это правка `OIDC_ISSUER`, а не переписывание модуля (ADR-0012).

Три правила, которые здесь важнее остального:

- **Список алгоритмов задан явно.** `alg: none` и подмена RS256 на HS256 с публичным
  ключом в роли секрета — классические способы подделать токен. Принимаются только
  подписи открытым ключом.
- **Секрет клиента уходит только в тело запроса к провайдеру.** Ни в лог, ни в ответ API,
  ни в сообщение об ошибке.
- **Отказ провайдера — отдельный класс ошибок.** Не отвечает — 502, не настроен — 503,
  прислал негодный ответ — 400. Общее «что-то пошло не так» не подсказывает, что чинить.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import Settings
from app.core.logging import get_logger
from app.errors import DomainError, ErrorCode

log = get_logger(__name__)

DISCOVERY_PATH: Final = "/.well-known/openid-configuration"

# Только подписи открытым ключом. HS* здесь означал бы, что подписать токен может любой,
# кто знает секрет клиента, — а его знает и сам клиент.
ALLOWED_ALGORITHMS: Final[tuple[str, ...]] = ("RS256", "RS384", "RS512", "ES256", "ES384")


@dataclass
class _Discovery:
    """Разобранный документ провайдера с временем протухания."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None
    fetched_at: float = field(default_factory=time.monotonic)


# Кэш на процесс: документ провайдера меняется раз в годы, а ходить за ним на каждый вход
# значит поставить вход в зависимость от ещё одного сетевого запроса.
_discovery_cache: dict[str, _Discovery] = {}
_jwks_clients: dict[str, PyJWKClient] = {}


def _require_configured(settings: Settings) -> str:
    issuer = settings.oidc_issuer.strip().rstrip("/")
    if not issuer:
        raise DomainError(ErrorCode.AUTH_NOT_CONFIGURED)
    return issuer


async def discover(settings: Settings) -> _Discovery:
    """Документ провайдера. Берётся из кэша, пока не истёк срок."""
    issuer = _require_configured(settings)
    cached = _discovery_cache.get(issuer)
    if cached is not None and time.monotonic() - cached.fetched_at < settings.oidc_jwks_ttl_seconds:
        return cached

    url = f"{issuer}{DISCOVERY_PATH}"
    try:
        async with httpx.AsyncClient(timeout=settings.oidc_timeout_seconds) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as error:
        # В журнал — адрес и класс ошибки. Ни секрета клиента, ни тела ответа.
        log.error("oidc_discovery_failed", issuer=issuer, error_type=type(error).__name__)
        raise DomainError(ErrorCode.OIDC_DISCOVERY_FAILED) from error

    try:
        discovery = _Discovery(
            issuer=str(payload["issuer"]),
            authorization_endpoint=str(payload["authorization_endpoint"]),
            token_endpoint=str(payload["token_endpoint"]),
            jwks_uri=str(payload["jwks_uri"]),
            end_session_endpoint=(
                str(payload["end_session_endpoint"])
                if payload.get("end_session_endpoint")
                else None
            ),
        )
    except KeyError as error:
        log.error("oidc_discovery_incomplete", issuer=issuer, missing=str(error))
        raise DomainError(ErrorCode.OIDC_DISCOVERY_FAILED) from error

    _discovery_cache[issuer] = discovery
    _jwks_clients.pop(issuer, None)
    return discovery


def _jwks_client(issuer: str, jwks_uri: str) -> PyJWKClient:
    """Клиент ключей с собственным кэшем.

    `PyJWKClient` сам перечитывает набор при неизвестном идентификаторе ключа, поэтому
    ротация на стороне провайдера не требует перезапуска портала.
    """
    client = _jwks_clients.get(issuer)
    if client is None:
        client = PyJWKClient(jwks_uri, cache_keys=True, lifespan=3600)
        _jwks_clients[issuer] = client
    return client


def reset_caches() -> None:
    """Сбрасывает кэши. Нужно тестам и смене настроек на лету."""
    _discovery_cache.clear()
    _jwks_clients.clear()


def authorization_url(
    discovery: _Discovery,
    settings: Settings,
    *,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    """Адрес страницы входа провайдера."""
    query = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(settings.oidc_scope_list),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{discovery.authorization_endpoint}?{query}"


async def exchange_code(
    settings: Settings,
    discovery: _Discovery,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Меняет код на токены. Выполняется на сервере — в браузер токены не попадают."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": code_verifier,
    }
    secret = settings.oidc_client_secret.get_secret_value()
    if secret:
        data["client_secret"] = secret

    try:
        async with httpx.AsyncClient(timeout=settings.oidc_timeout_seconds) as client:
            response = await client.post(discovery.token_endpoint, data=data)
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
    except (httpx.HTTPError, ValueError) as error:
        log.error("oidc_exchange_failed", error_type=type(error).__name__)
        raise DomainError(ErrorCode.OIDC_EXCHANGE_FAILED) from error

    if "id_token" not in payload:
        log.error("oidc_exchange_without_id_token")
        raise DomainError(ErrorCode.OIDC_EXCHANGE_FAILED)
    return payload


def decode_id_token(
    settings: Settings, discovery: _Discovery, token: str, *, nonce: str
) -> dict[str, Any]:
    """Проверяет подпись и содержимое токена личности.

    Проверяется всё сразу: подпись, издатель, получатель, срок и одноразовое значение.
    Пропущенная проверка nonce означает, что чужой токен, полученный в другом сеансе,
    примут за свой.
    """
    claims = _verify(settings, discovery, token)
    if claims.get("nonce") != nonce:
        log.warning("oidc_nonce_mismatch")
        raise DomainError(ErrorCode.OIDC_STATE_INVALID)
    return claims


async def verify_access_token(settings: Settings, token: str) -> dict[str, Any]:
    """Проверяет токен машинного клиента из заголовка Authorization."""
    discovery = await discover(settings)
    return _verify(settings, discovery, token)


def _verify(settings: Settings, discovery: _Discovery, token: str) -> dict[str, Any]:
    try:
        key = _jwks_client(discovery.issuer, discovery.jwks_uri).get_signing_key_from_jwt(token)
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=list(ALLOWED_ALGORITHMS),
            issuer=discovery.issuer,
            audience=settings.oidc_expected_audience,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError as error:
        # Наружу уходит один код: подсказывать, что именно не сошлось, значит помогать
        # подбирать токен.
        log.warning("oidc_token_rejected", error_type=type(error).__name__)
        raise DomainError(ErrorCode.CREDENTIAL_INVALID) from error
    except (httpx.HTTPError, OSError) as error:
        log.error("oidc_jwks_unavailable", error_type=type(error).__name__)
        raise DomainError(ErrorCode.OIDC_DISCOVERY_FAILED) from error
    return claims
