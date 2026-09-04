"""Безопасные коды ошибок.

Наружу уходит код и короткое сообщение на русском; подробности остаются в логах.
Список пополняется по мере появления операций — сейчас здесь то, что нужно API промта 03.
"""

from __future__ import annotations

from enum import StrEnum

from fastapi import HTTPException, status


class ErrorCode(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    CONTENT_NOT_AVAILABLE = "CONTENT_NOT_AVAILABLE"
    JOB_TRANSITION_INVALID = "JOB_TRANSITION_INVALID"


MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.NOT_FOUND: "Объект не найден",
    ErrorCode.VALIDATION_FAILED: "Некорректные данные запроса",
    ErrorCode.STORAGE_UNAVAILABLE: "Хранилище файлов недоступно",
    ErrorCode.DATABASE_UNAVAILABLE: "База данных недоступна",
    ErrorCode.CONTENT_NOT_AVAILABLE: "Файл ревизии недоступен",
    ErrorCode.JOB_TRANSITION_INVALID: "Недопустимый переход состояния задания",
}


class DomainError(Exception):
    """Ошибка предметной области с безопасным кодом."""

    def __init__(self, code: ErrorCode, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or MESSAGES[code]
        super().__init__(self.detail)


def not_found(what: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": ErrorCode.NOT_FOUND.value, "message": f"{what} не найден"},
    )


def http_error(code: ErrorCode, status_code: int, message: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code.value, "message": message or MESSAGES[code]},
    )
