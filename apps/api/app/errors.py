"""Безопасные коды ошибок.

Наружу уходит стабильный код и короткое сообщение на русском; подробности остаются в логах.
Код — часть контракта: интерфейс опирается на него, а не на текст сообщения.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException, status


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"

    # --- вход и права ---
    UNAUTHENTICATED = "UNAUTHENTICATED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    CREDENTIAL_INVALID = "CREDENTIAL_INVALID"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CSRF_FAILED = "CSRF_FAILED"
    WORKSPACE_FORBIDDEN = "WORKSPACE_FORBIDDEN"
    WORKSPACE_NOT_FOUND = "WORKSPACE_NOT_FOUND"
    MEMBERSHIP_EXISTS = "MEMBERSHIP_EXISTS"
    LAST_ADMIN_REMOVAL = "LAST_ADMIN_REMOVAL"

    # --- контур управления ---
    SETTING_UNKNOWN = "SETTING_UNKNOWN"
    SETTING_VALUE_INVALID = "SETTING_VALUE_INVALID"
    SETTING_SCOPE_INVALID = "SETTING_SCOPE_INVALID"
    FLAG_UNKNOWN = "FLAG_UNKNOWN"
    FLAG_NOT_EDITABLE = "FLAG_NOT_EDITABLE"
    FLAG_SCOPE_INVALID = "FLAG_SCOPE_INVALID"
    TENDERHUB_BINDING_CONFLICT = "TENDERHUB_BINDING_CONFLICT"
    TENDERHUB_BINDING_IMMUTABLE = "TENDERHUB_BINDING_IMMUTABLE"

    # --- провайдер личности ---
    AUTH_NOT_CONFIGURED = "AUTH_NOT_CONFIGURED"
    OIDC_STATE_INVALID = "OIDC_STATE_INVALID"
    OIDC_DISCOVERY_FAILED = "OIDC_DISCOVERY_FAILED"
    OIDC_EXCHANGE_FAILED = "OIDC_EXCHANGE_FAILED"

    # --- приём файлов ---
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    MIME_MISMATCH = "MIME_MISMATCH"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    EMPTY_FILE = "EMPTY_FILE"
    CORRUPT_ARCHIVE = "CORRUPT_ARCHIVE"

    # --- импорт распознанного пакета ---
    ARCHIVE_UNSAFE_PATH = "ARCHIVE_UNSAFE_PATH"
    ARCHIVE_LIMIT_EXCEEDED = "ARCHIVE_LIMIT_EXCEEDED"
    LEGACY_PDF_MISSING = "LEGACY_PDF_MISSING"
    LEGACY_BLOCKS_INVALID = "LEGACY_BLOCKS_INVALID"
    LEGACY_SCHEMA_UNSUPPORTED = "LEGACY_SCHEMA_UNSUPPORTED"
    IMPORT_FAILED = "IMPORT_FAILED"

    # --- инфраструктура ---
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    CONTENT_NOT_AVAILABLE = "CONTENT_NOT_AVAILABLE"

    # --- задания ---
    JOB_TRANSITION_INVALID = "JOB_TRANSITION_INVALID"
    JOB_LEASE_LOST = "JOB_LEASE_LOST"
    JOB_TIMEOUT = "JOB_TIMEOUT"
    JOB_NOT_RETRYABLE = "JOB_NOT_RETRYABLE"
    WORKER_UNAVAILABLE = "WORKER_UNAVAILABLE"

    # --- поставщики моделей ---
    MODEL_PROVIDER_NOT_CONFIGURED = "MODEL_PROVIDER_NOT_CONFIGURED"

    # --- TenderHUB ---
    TENDERHUB_DISABLED = "TENDERHUB_DISABLED"
    TENDERHUB_AUTH_FAILED = "TENDERHUB_AUTH_FAILED"
    TENDERHUB_FORBIDDEN = "TENDERHUB_FORBIDDEN"
    TENDERHUB_RATE_LIMITED = "TENDERHUB_RATE_LIMITED"
    TENDERHUB_UNAVAILABLE = "TENDERHUB_UNAVAILABLE"
    TENDERHUB_TENDER_NOT_FOUND = "TENDERHUB_TENDER_NOT_FOUND"
    TENDERHUB_ALREADY_LINKED = "TENDERHUB_ALREADY_LINKED"


MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.NOT_FOUND: "Объект не найден",
    ErrorCode.VALIDATION_FAILED: "Некорректные данные запроса",
    ErrorCode.UNAUTHENTICATED: "Требуется вход в портал",
    ErrorCode.SESSION_EXPIRED: "Сеанс истёк, войдите снова",
    ErrorCode.CREDENTIAL_INVALID: "Учётные данные недействительны",
    ErrorCode.PERMISSION_DENIED: "Недостаточно прав для этого действия",
    ErrorCode.CSRF_FAILED: "Запрос не подтверждён",
    ErrorCode.WORKSPACE_FORBIDDEN: "Нет доступа к этому рабочему пространству",
    ErrorCode.WORKSPACE_NOT_FOUND: "Рабочее пространство не найдено",
    ErrorCode.MEMBERSHIP_EXISTS: "Участник уже добавлен в пространство",
    ErrorCode.LAST_ADMIN_REMOVAL: "Нельзя убрать последнего администратора пространства",
    ErrorCode.SETTING_UNKNOWN: "Такой настройки нет",
    ErrorCode.SETTING_VALUE_INVALID: "Значение настройки не подходит",
    ErrorCode.SETTING_SCOPE_INVALID: "Настройка не переопределяется на этом уровне",
    ErrorCode.FLAG_UNKNOWN: "Такого флага возможностей нет",
    ErrorCode.FLAG_NOT_EDITABLE: "Флаг закрыт до готовности возможности",
    ErrorCode.FLAG_SCOPE_INVALID: "Флаг не переопределяется на уровне пространства",
    ErrorCode.TENDERHUB_BINDING_CONFLICT: "Этот тендер уже привязан к другому проекту",
    ErrorCode.TENDERHUB_BINDING_IMMUTABLE: "Связь с тендером меняется только администратором",
    ErrorCode.AUTH_NOT_CONFIGURED: "Вход в портал не настроен",
    ErrorCode.OIDC_STATE_INVALID: "Ответ провайдера входа не принят",
    ErrorCode.OIDC_DISCOVERY_FAILED: "Провайдер входа недоступен",
    ErrorCode.OIDC_EXCHANGE_FAILED: "Провайдер входа не подтвердил вход",
    ErrorCode.UNSUPPORTED_FILE_TYPE: "Такой тип файла не поддерживается",
    ErrorCode.MIME_MISMATCH: "Содержимое файла не соответствует расширению",
    ErrorCode.UPLOAD_TOO_LARGE: "Файл слишком большой",
    ErrorCode.EMPTY_FILE: "Файл пуст",
    ErrorCode.CORRUPT_ARCHIVE: "Архив повреждён",
    ErrorCode.ARCHIVE_UNSAFE_PATH: "В архиве есть небезопасный файл",
    ErrorCode.ARCHIVE_LIMIT_EXCEEDED: "Архив превышает допустимые пределы",
    ErrorCode.LEGACY_PDF_MISSING: "В пакете нет исходного PDF",
    ErrorCode.LEGACY_BLOCKS_INVALID: "Файл распознанных областей некорректен",
    ErrorCode.LEGACY_SCHEMA_UNSUPPORTED: "Версия схемы пакета не поддерживается",
    ErrorCode.IMPORT_FAILED: "Импорт пакета не удался",
    ErrorCode.STORAGE_UNAVAILABLE: "Хранилище файлов недоступно",
    ErrorCode.DATABASE_UNAVAILABLE: "База данных недоступна",
    ErrorCode.CONTENT_NOT_AVAILABLE: "Файл ревизии недоступен",
    ErrorCode.JOB_TRANSITION_INVALID: "Недопустимый переход состояния задания",
    ErrorCode.JOB_LEASE_LOST: "Исполнитель перестал отвечать, задание брошено",
    ErrorCode.JOB_TIMEOUT: "Задание не уложилось в отведённое время",
    ErrorCode.JOB_NOT_RETRYABLE: "Этот отказ повтором не чинится",
    ErrorCode.WORKER_UNAVAILABLE: "Исполнитель заданий недоступен",
    ErrorCode.MODEL_PROVIDER_NOT_CONFIGURED: "Поставщик моделей не настроен",
    ErrorCode.TENDERHUB_DISABLED: "Интеграция с TenderHUB не настроена",
    ErrorCode.TENDERHUB_AUTH_FAILED: "TenderHUB не принял ключ доступа",
    ErrorCode.TENDERHUB_FORBIDDEN: "Ключу TenderHUB не выдан доступ к этим данным",
    ErrorCode.TENDERHUB_RATE_LIMITED: "TenderHUB ограничил частоту запросов",
    ErrorCode.TENDERHUB_UNAVAILABLE: "TenderHUB недоступен",
    ErrorCode.TENDERHUB_TENDER_NOT_FOUND: "Тендер не найден в TenderHUB",
    ErrorCode.TENDERHUB_ALREADY_LINKED: "Проект по этому тендеру уже создан",
}

# HTTP-статус зависит от кода: клиенту важно отличать свою ошибку от отказа инфраструктуры.
STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # 401 — «не знаю, кто ты», 403 — «знаю, но нельзя». Чужое рабочее пространство отвечает
    # не отсюда, а обычным 404: 403 подтвердил бы, что объект существует (ADR-0012).
    ErrorCode.UNAUTHENTICATED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.SESSION_EXPIRED: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.CREDENTIAL_INVALID: status.HTTP_401_UNAUTHORIZED,
    ErrorCode.PERMISSION_DENIED: status.HTTP_403_FORBIDDEN,
    ErrorCode.CSRF_FAILED: status.HTTP_403_FORBIDDEN,
    ErrorCode.WORKSPACE_FORBIDDEN: status.HTTP_403_FORBIDDEN,
    ErrorCode.WORKSPACE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.MEMBERSHIP_EXISTS: status.HTTP_409_CONFLICT,
    ErrorCode.LAST_ADMIN_REMOVAL: status.HTTP_409_CONFLICT,
    # Провайдер личности — такая же внешняя система, как TenderHUB, и отвечает так же:
    # не настроен — 503, не отвечает — 502, прислал негодный ответ — 400.
    ErrorCode.SETTING_UNKNOWN: status.HTTP_404_NOT_FOUND,
    ErrorCode.SETTING_VALUE_INVALID: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.SETTING_SCOPE_INVALID: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.FLAG_UNKNOWN: status.HTTP_404_NOT_FOUND,
    # 409, а не 403: право у администратора есть, но возможность ещё не готова —
    # это конфликт с состоянием продукта, а не отказ в доступе.
    ErrorCode.FLAG_NOT_EDITABLE: status.HTTP_409_CONFLICT,
    ErrorCode.FLAG_SCOPE_INVALID: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ErrorCode.TENDERHUB_BINDING_CONFLICT: status.HTTP_409_CONFLICT,
    ErrorCode.TENDERHUB_BINDING_IMMUTABLE: status.HTTP_409_CONFLICT,
    ErrorCode.AUTH_NOT_CONFIGURED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.OIDC_STATE_INVALID: status.HTTP_400_BAD_REQUEST,
    ErrorCode.OIDC_DISCOVERY_FAILED: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.OIDC_EXCHANGE_FAILED: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.UNSUPPORTED_FILE_TYPE: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.MIME_MISMATCH: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.UPLOAD_TOO_LARGE: status.HTTP_413_CONTENT_TOO_LARGE,
    ErrorCode.EMPTY_FILE: status.HTTP_400_BAD_REQUEST,
    ErrorCode.CORRUPT_ARCHIVE: status.HTTP_400_BAD_REQUEST,
    ErrorCode.ARCHIVE_UNSAFE_PATH: status.HTTP_400_BAD_REQUEST,
    ErrorCode.ARCHIVE_LIMIT_EXCEEDED: status.HTTP_413_CONTENT_TOO_LARGE,
    ErrorCode.LEGACY_PDF_MISSING: status.HTTP_400_BAD_REQUEST,
    ErrorCode.LEGACY_BLOCKS_INVALID: status.HTTP_400_BAD_REQUEST,
    ErrorCode.LEGACY_SCHEMA_UNSUPPORTED: status.HTTP_400_BAD_REQUEST,
    ErrorCode.IMPORT_FAILED: status.HTTP_500_INTERNAL_SERVER_ERROR,
    ErrorCode.STORAGE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.DATABASE_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.CONTENT_NOT_AVAILABLE: status.HTTP_404_NOT_FOUND,
    ErrorCode.JOB_TRANSITION_INVALID: status.HTTP_409_CONFLICT,
    # Брошенное задание и исчерпанный срок — это состояние задания, а не ошибка
    # запроса: наружу они уходят в поле задания, а не HTTP-кодом. Статус нужен
    # только на случай, когда их всё же поднимают исключением.
    ErrorCode.JOB_LEASE_LOST: status.HTTP_409_CONFLICT,
    ErrorCode.JOB_TIMEOUT: status.HTTP_409_CONFLICT,
    ErrorCode.JOB_NOT_RETRYABLE: status.HTTP_409_CONFLICT,
    ErrorCode.WORKER_UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.MODEL_PROVIDER_NOT_CONFIGURED: status.HTTP_409_CONFLICT,
    # Отказы внешней системы — 502: клиент не виноват, но и повторять запрос бессмысленно,
    # пока не поправят ключ или доступ на той стороне.
    ErrorCode.TENDERHUB_DISABLED: status.HTTP_503_SERVICE_UNAVAILABLE,
    ErrorCode.TENDERHUB_AUTH_FAILED: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.TENDERHUB_FORBIDDEN: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.TENDERHUB_RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    ErrorCode.TENDERHUB_UNAVAILABLE: status.HTTP_502_BAD_GATEWAY,
    ErrorCode.TENDERHUB_TENDER_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.TENDERHUB_ALREADY_LINKED: status.HTTP_409_CONFLICT,
}


class DomainError(Exception):
    """Ошибка предметной области с безопасным кодом."""

    def __init__(self, code: ErrorCode, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or MESSAGES[code]
        super().__init__(self.detail)

    @property
    def status_code(self) -> int:
        return STATUS_CODES[self.code]


class InvariantError(Exception):
    """Нарушение внутреннего инварианта: данные в базе не такие, какими должны быть.

    Это ошибка портала, а не пользователя, поэтому наружу уходит обычная пятисотка,
    а подробности — в логи.
    """


def not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": ErrorCode.NOT_FOUND.value, "message": f"{what} не найден"},
    )


def http_error(
    code: ErrorCode,
    status_code: int | None = None,
    message: str | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """Ошибка с безопасным кодом.

    headers нужен отказам аутентификации: 401 без `WWW-Authenticate` формально неполон,
    и клиенты, различающие способы входа, по нему ориентируются.
    """
    return HTTPException(
        status_code=status_code or STATUS_CODES[code],
        detail={"code": code.value, "message": message or MESSAGES[code]},
        headers=headers,
    )
