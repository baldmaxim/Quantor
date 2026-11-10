"""Ошибки генератора с кодами выхода CLI."""

from __future__ import annotations

EXIT_INPUT = 2
EXIT_NO_ROUTES = 3


class MepError(Exception):
    """Остановка генератора: `code` уходит в stderr строкой JSON, `exit_code` — код процесса."""

    def __init__(self, code: str, message: str, exit_code: int = EXIT_INPUT) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
