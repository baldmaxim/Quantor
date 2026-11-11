"""Ошибки скрипта с кодами выхода CLI."""

from __future__ import annotations

EXIT_INPUT = 2


class WallsError(Exception):
    """Остановка скрипта: `code` уходит в stderr строкой JSON, `exit_code` — код процесса."""

    def __init__(self, code: str, message: str, exit_code: int = EXIT_INPUT) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class Issue:
    """Предупреждение в checks.warnings: код и текст."""

    __slots__ = ("code", "message")

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
