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


MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.NOT_FOUND: "Объект не найден",
    ErrorCode.VALIDATION_FAILED: "Некорректные данные запроса",
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
}

# HTTP-статус зависит от кода: клиенту важно отличать свою ошибку от отказа инфраструктуры.
STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ErrorCode.VALIDATION_FAILED: status.HTTP_422_UNPROCESSABLE_CONTENT,
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
    code: ErrorCode, status_code: int | None = None, message: str | None = None
) -> HTTPException:
    return HTTPException(
        status_code=status_code or STATUS_CODES[code],
        detail={"code": code.value, "message": message or MESSAGES[code]},
    )
